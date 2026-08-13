"""パイプライン全体のオーケストレーション（Stage 0 → 1 → 2 → 3 → 起票）。

判定と起票は別レイヤー:
  - **判定**はチャンクハッシュ単位でキャッシュする
  - **起票**は該当チャンクを含む**全ファイルインスタンス**に展開する
    （同じ内容のファイルが複数置かれていても、片方だけ指摘する事故を防ぐ）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.egov.snapshot import ChangeEvent
from app.index import ChunkIndex
from app.llm.client import CostLog, Embedder
from app.pipeline import stage0, stage1, stage2, stage3
from app.pipeline.cache import JudgementCache, cache_key, document_hash
from app.pipeline.models import (
    Alert,
    Change,
    ChangeResult,
    Finding,
    FunnelStats,
    PipelineResult,
)


@dataclass
class ModelSet:
    """段階ごとのモデル割り当て（`orcarouter/auto` は使わない）。"""

    stage0: str
    stage2: str
    stage3: str
    escalation: str | None = None


def run_pipeline(
    event: ChangeEvent,
    index: ChunkIndex,
    chat,
    models: ModelSet,
    embedder: Embedder | None = None,
    locations: dict[str, str] | None = None,
    linked_doc_ids: set[str] | None = None,
    cache: JudgementCache | None = None,
    max_changes: int | None = None,
    cost_log: CostLog | None = None,
    progress=None,
) -> PipelineResult:
    """1イベント（改正1件）を処理する。"""
    cost_log = cost_log if cost_log is not None else CostLog()
    locations = locations or {}
    result = PipelineResult(
        law_id=event.law_id,
        law_title=event.law_title,
        from_revision=event.from_revision,
        to_revision=event.to_revision,
        enforcement_date=event.enforcement_date,
    )

    def report(message: str) -> None:
        if progress:
            progress(message)

    report(f"Stage 0: {len(event.diffs)} 件の差分を変更単位に分解します")
    changes = stage0.decompose(
        chat,
        event.diffs,
        law_title=event.law_title,
        enforcement_date=event.enforcement_date,
        model=models.stage0,
        cost_log=cost_log,
        limit=max_changes,
    )

    for change in changes:
        report(f"  [{change.change_id}] {change.target_path}")
        result.results.append(
            _process_change(
                change,
                index,
                chat,
                models,
                event.law_title,
                embedder,
                linked_doc_ids,
                cache,
                cost_log,
                report,
            )
        )

    result.alerts = expand_alerts(result.results, index, locations)
    result.cost = {
        **cost_log.summary(),
        "cache": cache.stats if cache else {"hits": 0, "misses": 0},
    }
    if cache:
        cache.save()
    return result


def _process_change(
    change: Change,
    index: ChunkIndex,
    chat,
    models: ModelSet,
    law_title: str,
    embedder: Embedder | None,
    linked_doc_ids: set[str] | None,
    cache: JudgementCache | None,
    cost_log: CostLog,
    report,
) -> ChangeResult:
    funnel = FunnelStats(total_chunks=len(index))

    candidates = stage1.search(
        index, change, embedder=embedder, linked_doc_ids=linked_doc_ids
    )
    funnel.stage1_passed = len(candidates)
    report(f"    Stage 1: {funnel.total_chunks} → {funnel.stage1_passed} 件")

    passed, scores, notes = stage2.rerank(
        chat, change, candidates, index, model=models.stage2, cost_log=cost_log
    )
    funnel.stage2_passed = len(passed)
    report(f"    Stage 2: {funnel.stage1_passed} → {funnel.stage2_passed} 件")
    for note in notes:
        report(f"      注意: {note}")

    findings: list[Finding] = []
    doc_hashes = _document_hashes(index)
    for candidate in passed:
        chunk = index.get(candidate.chunk_id)
        key = cache_key(
            change.fingerprint,
            chunk.content_hash,
            stage3.PROMPT_VERSION,
            doc_hashes.get(chunk.doc_id, ""),
        )
        cached = cache.get(key) if cache else None
        if cached is not None:
            finding = Finding(**{**cached, "chunk_id": chunk.chunk_id, "doc_id": chunk.doc_id, "label": chunk.label})
        else:
            finding = stage3.judge_chunk(
                chat,
                change,
                chunk,
                index,
                law_title,
                model=models.stage3,
                escalation_model=models.escalation,
                cost_log=cost_log,
            )
            if cache:
                cache.set(key, finding.to_dict())
        findings.append(finding)

    funnel.stage3_judged = len(findings)
    funnel.affected = sum(1 for f in findings if f.impact == "affected")
    funnel.not_affected = funnel.stage3_judged - funnel.affected
    report(
        f"    Stage 3: {funnel.stage3_judged} 件を精査 → 要対応 {funnel.affected} 件 / "
        f"影響なし {funnel.not_affected} 件"
    )

    return ChangeResult(
        change=change, candidates=candidates, scores=scores, findings=findings, funnel=funnel
    )


def _document_hashes(index: ChunkIndex) -> dict[str, str]:
    """文書ごとの同一性ハッシュ（ファイル名ではなく中身から作る）。"""
    by_doc: dict[str, list[str]] = {}
    for chunk in index.chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk.content_hash)
    return {doc_id: document_hash(hashes) for doc_id, hashes in by_doc.items()}


def expand_alerts(
    results: list[ChangeResult], index: ChunkIndex, locations: dict[str, str]
) -> list[Alert]:
    """判定（チャンクハッシュ単位）を、起票（ファイルインスタンス単位）に展開する。

    同一内容のチャンクを含む**すべてのファイル**にアラートを出す。
    """
    by_hash: dict[str, list] = {}
    for chunk in index.chunks:
        by_hash.setdefault(chunk.content_hash, []).append(chunk)

    alerts: list[Alert] = []
    seen: set[tuple[str, str]] = set()  # (変更ID, チャンクID)

    for change_result in results:
        for finding in change_result.findings:
            if finding.impact != "affected":
                continue
            source = index.get(finding.chunk_id)
            for chunk in by_hash.get(source.content_hash, [source]):
                # 同一内容チャンクは複数ファイルで別々に判定されうる（判定はキャッシュで1回だが
                # 起票は展開される）。同じファイルの同じ箇所を二重に起票しない
                marker = (change_result.change.change_id, chunk.chunk_id)
                if marker in seen:
                    continue
                seen.add(marker)
                alerts.append(
                    Alert(
                        doc_id=chunk.doc_id,
                        location=locations.get(chunk.doc_id, chunk.doc_id),
                        chunk_id=chunk.chunk_id,
                        change_id=change_result.change.change_id,
                        finding=finding,
                    )
                )
    return alerts


def load_cache(path: Path | None) -> JudgementCache:
    return JudgementCache(path)
