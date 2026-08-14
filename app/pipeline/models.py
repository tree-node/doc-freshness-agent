"""パイプライン各段の入出力（DESIGN.md 候補絞り込みパイプライン）。

イベント（改正1件）─ 変更(change) × N の2階層。**各変更が独立に Stage 1〜3 を通る**。
UIの主語はイベントのまま（配下に変更・影響文書がぶら下がる）。
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ChangeType = Literal["amend", "add", "delete", "effective_date_only"]
Impact = Literal["affected", "none", "not_applicable"]
Applicability = Literal["applicable", "not_applicable", "unclear"]
DeadlineType = Literal["immediate", "on_renewal", "none"]


@dataclass
class Change:
    """Stage 0 の出力 = 変更単位。キャッシュキーの粒度でもある。"""

    change_id: str
    change_type: ChangeType
    target_path: str
    before_excerpt: str | None
    after_excerpt: str | None
    summary: str
    affected_domains: list[str]
    semantic_query: str  # ベクトル検索用（旧ルール準拠の文書に現れそうな表現）
    exact_terms: list[str]  # BM25用（条番号・固有語）。semantic_query と必ず分ける
    effective_date: str | None
    effective_date_note: str | None = None
    transitional: bool = False
    confidence: float = 0.0
    needs_human_review: bool = False
    note: str | None = None

    @property
    def fingerprint(self) -> str:
        """変更単位のハッシュ。判定キャッシュのキー材料（イベント単位ではない）。"""
        material = "|".join(
            [
                self.change_type,
                self.target_path,
                self.before_excerpt or "",
                self.after_excerpt or "",
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Candidate:
    """Stage 1 の通過候補。"""

    chunk_id: str
    doc_id: str
    label: str
    rrf_score: float
    reason: str  # なぜ通ったか（救済枠・紐付け等）を画面に出すために持つ
    # 紐付け済み文書か。**表示用の reason とは別に持つ**（見逃し担保①の判定を
    # 文字列一致に依存させない。検索上位にも入っていると reason が上書きされるため）
    linked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FunnelStats:
    """絞り込み過程の可視化（DESIGN.md 見逃し担保③・原則3「影響なしも見せる」）。"""

    total_chunks: int = 0
    stage1_passed: int = 0
    stage2_passed: int = 0
    stage3_judged: int = 0
    affected: int = 0
    not_affected: int = 0

    @property
    def stage1_excluded(self) -> int:
        return max(self.total_chunks - self.stage1_passed, 0)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage1_excluded"] = self.stage1_excluded
        return data


@dataclass
class Finding:
    """Stage 3 の判定結果（チャンク単位）。起票はこれを全ファイルインスタンスに展開する。"""

    chunk_id: str
    doc_id: str
    label: str
    document_nature: str
    law_applicability: Applicability
    applicability_reason: str
    impact: Impact
    deadline_type: DeadlineType
    evidence_quote: str
    evidence_location: str
    fix_proposal: dict[str, str] | None
    confidence: float
    needs_human_review: bool = False
    review_reason: str | None = None
    evidence_verified: bool = True  # 逐語引用がチャンク本文に実在したか
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeResult:
    """変更1件ぶんの結果。"""

    change: Change
    candidates: list[Candidate] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)  # Stage 2 のスコア
    findings: list[Finding] = field(default_factory=list)
    funnel: FunnelStats = field(default_factory=FunnelStats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change": self.change.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "stage2_scores": self.scores,
            "findings": [f.to_dict() for f in self.findings],
            "funnel": self.funnel.to_dict(),
        }


@dataclass
class Alert:
    """起票（ファイルインスタンス単位）。

    判定はチャンクハッシュ単位、起票は該当チャンクを含む**全ファイル**に展開する。
    """

    doc_id: str
    location: str
    chunk_id: str
    change_id: str
    finding: Finding

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "location": self.location,
            "chunk_id": self.chunk_id,
            "change_id": self.change_id,
            "finding": self.finding.to_dict(),
        }


@dataclass
class PipelineResult:
    """イベント1件ぶんの結果（CLIのJSON出力）。"""

    law_id: str
    law_title: str
    from_revision: str
    to_revision: str
    enforcement_date: str | None
    detected_at: str | None = None  # いつ検知したか。画面の「◯◯に検知」に使う
    results: list[ChangeResult] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "law_id": self.law_id,
            "law_title": self.law_title,
            "from_revision": self.from_revision,
            "to_revision": self.to_revision,
            "enforcement_date": self.enforcement_date,
            "detected_at": self.detected_at,
            "changes": [r.to_dict() for r in self.results],
            "alerts": [a.to_dict() for a in self.alerts],
            "cost": self.cost,
        }
