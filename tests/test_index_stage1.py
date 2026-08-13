"""インデックスと Stage 1（ハイブリッド検索）のテスト。ネットワークに出ない。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.chunking import split_document
from app.index import ChunkIndex, build_index, normalize_rows, tokenize
from app.pipeline.models import Change
from app.pipeline.stage1 import RRF_K, rrf_score, search

DOCS = {
    "就業規則.md": (
        "# 就業規則\n"
        "## 第3章 休暇\n"
        "第16条（子の看護休暇）\n"
        "小学校就学の始期に達するまでの子を養育する従業員は、看護休暇を取得できる。\n"
        "第17条（介護休暇）\n"
        "要介護状態にある家族を介護する従業員は、介護休暇を取得できる。\n"
    ),
    "業務委託契約書.md": (
        "# 業務委託契約書\n"
        "第5条（報酬）\n"
        "委託者は受託者に対し、月額金額を支払う。\n"
        "第6条（再委託）\n"
        "受託者は、委託者の承諾なく再委託してはならない。\n"
    ),
    "旧・時間外労働メモ.txt": "第138条 中小事業主については、当分の間、適用しない。\n",
}


def make_chunks():
    chunks = []
    for doc_id, text in DOCS.items():
        chunks.extend(split_document(doc_id, text))
    return chunks


class FakeEmbedder:
    """語の有無だけを見る決定的な埋め込み。ネットワークに出ずにベクトル経路を通す。"""

    VOCAB = ("看護", "介護", "報酬", "再委託", "中小事業主", "休暇")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(word in text) for word in self.VOCAB] for text in texts]


def a_change(**overrides) -> Change:
    base = {
        "change_id": "c1",
        "change_type": "amend",
        "target_path": "第16条の2",
        "before_excerpt": "小学校就学の始期に達するまで",
        "after_excerpt": "九歳に達する日以後の最初の三月三十一日まで",
        "summary": "子の看護休暇の対象となる子の範囲が拡大された",
        "affected_domains": ["育児"],
        "semantic_query": "小学校就学の始期に達するまでの子を養育する従業員の看護休暇",
        "exact_terms": ["子の看護休暇", "第16条"],
        "effective_date": "2025-04-01",
    }
    return Change(**{**base, **overrides})


# --- インデックス ---------------------------------------------------------------


def test_tokenizer_uses_character_bigrams_for_japanese() -> None:
    assert tokenize("看護休暇") == ["看護", "護休", "休暇"]


def test_tokenizer_keeps_ascii_words_whole() -> None:
    assert tokenize("Article 16") == ["article", "16"]


def test_bm25_finds_the_document_by_keyword() -> None:
    index = build_index(make_chunks())
    hits = index.search_bm25("子の看護休暇", top_k=5)
    assert hits
    assert index.get(hits[0].chunk_id).doc_id == "就業規則.md"


def test_bm25_ranks_are_one_based_and_ordered() -> None:
    index = build_index(make_chunks())
    hits = index.search_bm25("看護休暇", top_k=5)
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert hits == sorted(hits, key=lambda h: -h.score)


def test_bm25_keeps_matches_whose_terms_are_common_in_the_corpus() -> None:
    """頻出語で一致した本命を落とさない。

    BM25のIDFは、その語がコーパスの半数超の文書に現れると負になる。スコアで足切りすると、
    就業規則ばかりのフォルダで「看護」「労働者」のような語が負になり、
    本命の一致が丸ごと消える（実際にこれで検索結果が空になった）。
    """
    chunks = []
    for i in range(3):
        chunks.extend(split_document(f"就業規則{i}.md", f"# 就業規則{i}\n第16条（子の看護休暇）\n看護休暇を取得できる。\n"))
    chunks.extend(split_document("無関係.md", "# 議事録\n第1条 会議の記録。\n"))
    index = build_index(chunks)

    scores = index._bm25.get_scores(tokenize("子の看護休暇"))
    assert min(scores) >= 0, "一致しないチャンクが負にならないこと（順位反転の防止）"

    hits = index.search_bm25("子の看護休暇", top_k=10)
    assert {index.get(h.chunk_id).doc_id for h in hits} == {
        "就業規則0.md",
        "就業規則1.md",
        "就業規則2.md",
    }, "一致した3件が返り、一致しない議事録は返らない"


def test_vector_search_requires_embeddings() -> None:
    index = build_index(make_chunks())  # embedder なし
    assert not index.has_vectors
    assert index.search_vector([1.0, 0, 0, 0, 0, 0], top_k=5) == []


def test_vector_search_returns_similar_chunks() -> None:
    embedder = FakeEmbedder()
    index = build_index(make_chunks(), embedder=embedder)
    query = embedder.embed(["看護休暇について"])[0]
    hits = index.search_vector(query, top_k=3)
    assert index.get(hits[0].chunk_id).doc_id == "就業規則.md"


def test_index_roundtrip_preserves_chunks_and_vectors(tmp_path: Path) -> None:
    index = build_index(make_chunks(), embedder=FakeEmbedder())
    index.save(tmp_path / "idx")
    loaded = ChunkIndex.load(tmp_path / "idx")

    assert [c.chunk_id for c in loaded.chunks] == [c.chunk_id for c in index.chunks]
    assert loaded.chunks[0].structure_path == index.chunks[0].structure_path
    assert np.allclose(loaded.embeddings, index.embeddings)


def test_embeddings_are_normalized() -> None:
    matrix = normalize_rows(np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32))
    assert np.isclose(np.linalg.norm(matrix[0]), 1.0)
    assert np.allclose(matrix[1], 0.0)  # ゼロ行で落ちない


# --- Stage 1 --------------------------------------------------------------------


def test_rrf_score_decreases_with_rank() -> None:
    assert rrf_score(1) > rrf_score(2)
    assert rrf_score(1) == 1 / (RRF_K + 1)


def test_search_returns_candidates_sorted_by_rrf() -> None:
    index = build_index(make_chunks(), embedder=FakeEmbedder())
    candidates = search(index, a_change(), embedder=FakeEmbedder())
    assert candidates
    assert candidates == sorted(candidates, key=lambda c: (-c.rrf_score, c.chunk_id))
    assert any("看護休暇" in index.get(c.chunk_id).text for c in candidates[:3])


def test_rescue_slot_passes_single_engine_hits() -> None:
    """片方の検索だけが強く反応した候補も通す（取りこぼし防止）。"""
    index = build_index(make_chunks(), embedder=FakeEmbedder())
    candidates = search(index, a_change(), embedder=FakeEmbedder(), top_k=1, rescue_k=3)
    reasons = {c.reason for c in candidates}
    assert len(candidates) > 1
    assert any("救済枠" in reason for reason in reasons)


def test_linked_documents_pass_regardless_of_score() -> None:
    """紐付け済み文書は検索スコアに関係なく通す（見逃し担保①）。"""
    index = build_index(make_chunks())
    change = a_change(semantic_query="", exact_terms=["まったく無関係な語"])
    candidates = search(index, change, top_k=0, rescue_k=0, linked_doc_ids={"業務委託契約書.md"})
    linked = [c for c in candidates if c.doc_id == "業務委託契約書.md"]
    assert linked
    assert all(c.reason == "紐付け済み文書" for c in linked)
    assert all(c.linked for c in linked)


def test_linked_flag_survives_when_the_document_is_also_a_search_hit() -> None:
    """紐付け済み文書が検索上位にも入ると、表示用の理由は「検索上位」になる。

    それでも紐付けフラグは立てておかないと、Stage 2 の無条件通過が効かず、
    見逃し担保①が破れる（スコアが閾値未満で落ちる）。
    """
    index = build_index(make_chunks())
    candidates = search(index, a_change(), linked_doc_ids={"就業規則.md"})
    hits = [c for c in candidates if c.doc_id == "就業規則.md"]
    assert any(c.reason == "検索上位" for c in hits)
    assert all(c.linked for c in hits)


def test_delete_type_leans_on_bm25() -> None:
    """delete型は「削除された条を参照し続けている文書」を旧条番号で探す。"""
    index = build_index(make_chunks(), embedder=FakeEmbedder())
    change = a_change(
        change_type="delete",
        target_path="第138条",
        after_excerpt=None,
        summary="第138条が削除された",
        exact_terms=["第138条", "中小事業主"],
        semantic_query="中小事業主の時間外労働の割増賃金の適用猶予",
    )
    candidates = search(index, change, embedder=FakeEmbedder())
    assert candidates[0].doc_id == "旧・時間外労働メモ.txt"


def test_search_works_without_embedder() -> None:
    """埋め込みが用意できなくてもBM25だけで動く（デモ当日の保険）。"""
    index = build_index(make_chunks())
    assert search(index, a_change())
