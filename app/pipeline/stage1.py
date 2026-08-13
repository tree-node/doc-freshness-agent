"""Stage 1 — ハイブリッド検索（LLM不使用。3,000チャンク → 50件）。

DESIGN.md の決定:
  - ベクトル検索 + BM25 を併走し **RRF（k=60）** で統合。重み付き和は使わない（尺度が違う）
  - 通過条件は**順位カットのみ**: RRF上位50 ＋ **各検索の単独上位10は無条件で通す救済枠**
    （片方だけが強く反応した本命の取りこぼし防止）。閾値による判断は Stage 2 に集約する
  - `change_type: delete` は BM25 主軸（探すのは「削除された条を参照し続けている文書」）
  - 紐付け済み文書は検索スコアに関係なく通す（見逃し担保①）
"""

from __future__ import annotations

from app.index import ChunkIndex, Hit
from app.llm.client import Embedder
from app.pipeline.models import Candidate, Change

RRF_K = 60
TOP_K = 50
RESCUE_K = 10  # 各検索の単独上位。片方だけが強く反応した候補を救う

# delete型はBM25主軸。ベクトル側の寄与を弱める（除外はしない）
DELETE_VECTOR_WEIGHT = 0.3


def rrf_score(rank: int, weight: float = 1.0, k: int = RRF_K) -> float:
    return weight / (k + rank)


def _fuse(
    bm25_hits: list[Hit], vector_hits: list[Hit], vector_weight: float
) -> dict[str, tuple[float, list[str]]]:
    fused: dict[str, tuple[float, list[str]]] = {}
    for hits, source, weight in (
        (bm25_hits, "bm25", 1.0),
        (vector_hits, "vector", vector_weight),
    ):
        for hit in hits:
            score, sources = fused.get(hit.chunk_id, (0.0, []))
            fused[hit.chunk_id] = (score + rrf_score(hit.rank, weight), [*sources, source])
    return fused


def search(
    index: ChunkIndex,
    change: Change,
    embedder: Embedder | None = None,
    top_k: int = TOP_K,
    rescue_k: int = RESCUE_K,
    linked_doc_ids: set[str] | None = None,
) -> list[Candidate]:
    """変更1件に対する候補チャンクを返す。"""
    linked_doc_ids = linked_doc_ids or set()

    bm25_query = " ".join(change.exact_terms) or change.summary
    bm25_hits = index.search_bm25(bm25_query, top_k=max(top_k, rescue_k))

    vector_hits: list[Hit] = []
    if embedder is not None and index.has_vectors and change.semantic_query.strip():
        query_vector = embedder.embed([change.semantic_query])[0]
        vector_hits = index.search_vector(query_vector, top_k=max(top_k, rescue_k))

    vector_weight = DELETE_VECTOR_WEIGHT if change.change_type == "delete" else 1.0
    fused = _fuse(bm25_hits, vector_hits, vector_weight)

    ranked = sorted(fused.items(), key=lambda item: -item[1][0])
    selected: dict[str, str] = {}  # chunk_id -> 通過理由

    for chunk_id, _ in ranked[:top_k]:
        selected[chunk_id] = "検索上位"

    # 救済枠: 片方の検索だけで上位に来たものは無条件で通す
    for hits, source in ((bm25_hits, "キーワード検索"), (vector_hits, "意味検索")):
        for hit in hits[:rescue_k]:
            selected.setdefault(hit.chunk_id, f"{source}の上位（救済枠）")

    # 紐付け済み文書は検索結果に関係なく通す（見逃し担保①）
    if linked_doc_ids:
        for chunk in index.chunks:
            if chunk.doc_id in linked_doc_ids:
                selected.setdefault(chunk.chunk_id, "紐付け済み文書")

    candidates = [
        Candidate(
            chunk_id=chunk_id,
            doc_id=index.get(chunk_id).doc_id,
            label=index.get(chunk_id).label,
            rrf_score=round(fused.get(chunk_id, (0.0, []))[0], 6),
            reason=reason,
            linked=index.get(chunk_id).doc_id in linked_doc_ids,
        )
        for chunk_id, reason in selected.items()
    ]
    return sorted(candidates, key=lambda c: (-c.rrf_score, c.chunk_id))
