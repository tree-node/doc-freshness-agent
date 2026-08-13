"""チャンク分割のテスト（DESIGN.md 分割ルール）。ネットワークに出ない。"""

from __future__ import annotations

from app.chunking import MAX_CHARS, Chunk, content_hash, split_document

REGULATION = """この規程は、株式会社架空商事の育児・介護休業について定める。

# 育児・介護休業規程

## 第3章 子の看護休暇

第16条（子の看護休暇）
1 小学校就学の始期に達するまでの子を養育する従業員は、看護休暇を取得できる。
2 前項の休暇は、1年度において5日を限度とする。

区分 | 日数
子1人 | 5日
子2人以上 | 10日

第17条（介護休暇）
要介護状態にある家族を介護する従業員は、介護休暇を取得できる。
"""


def chunks_of(text: str = REGULATION, doc_id: str = "規程.md") -> list[Chunk]:
    return split_document(doc_id, text)


def find(chunks: list[Chunk], needle: str) -> Chunk:
    return next(c for c in chunks if needle in c.text)


def test_preamble_before_first_heading_is_kept() -> None:
    """見出しに掛からない残りテキストも捨てない（見逃し側に倒す）。"""
    chunk = find(chunks_of(), "株式会社架空商事")
    assert chunk.structure_path == ()


def test_article_becomes_its_own_chunk_with_structure_path() -> None:
    chunk = find(chunks_of(), "看護休暇を取得できる")
    assert chunk.kind == "article"
    assert chunk.structure_path == (
        "育児・介護休業規程",
        "第3章 子の看護休暇",
        "第16条（子の看護休暇）",
    )
    assert chunk.label == "育児・介護休業規程 > 第3章 子の看護休暇 > 第16条（子の看護休暇）"


def test_table_is_a_separate_chunk_under_the_preceding_heading() -> None:
    chunk = find(chunks_of(), "子2人以上")
    assert chunk.kind == "table"
    # 直前の見出し（条）に属する
    assert chunk.structure_path[-1].startswith("第16条")


def test_offsets_point_at_the_original_text() -> None:
    text = REGULATION
    for chunk in chunks_of(text):
        assert chunk.text in text[chunk.start : chunk.end]


def test_embedding_text_prefixes_structure_path() -> None:
    chunk = find(chunks_of(), "看護休暇を取得できる")
    assert chunk.embedding_text.startswith("育児・介護休業規程 > 第3章")
    assert chunk.text not in ("",)
    assert not chunk.text.startswith("育児・介護休業規程 >")  # 表示用本文は分ける


def test_same_text_in_different_documents_shares_the_hash() -> None:
    """同一内容チャンクは同一キー = 重複配置ファイルの片方だけ指摘する事故を構造的に防ぐ。"""
    a = find(chunks_of(doc_id="A/規程.md"), "看護休暇を取得できる")
    b = find(chunks_of(doc_id="B/コピー.md"), "看護休暇を取得できる")
    assert a.doc_id != b.doc_id
    assert a.content_hash == b.content_hash
    assert a.chunk_id != b.chunk_id


def test_hash_ignores_indentation_only_differences() -> None:
    assert content_hash("第1条 本文") == content_hash("  第1条 本文  \n")


def test_short_articles_are_not_merged() -> None:
    text = "第1条 短い。\n第2条 これも短い。\n"
    chunks = split_document("d.md", text)
    assert len(chunks) == 2


def test_long_article_is_split_at_paragraph_markers() -> None:
    body = "あ" * (MAX_CHARS // 2)
    text = f"第1条（長い条）\n1 {body}\n2 {body}\n3 {body}\n"
    chunks = split_document("d.md", text)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS * 1.5 for c in chunks)
    # 分割後も構造パスは保たれる
    assert all(c.structure_path[-1].startswith("第1条") for c in chunks)


def test_article_with_branch_number_is_detected() -> None:
    chunks = split_document("d.md", "第16条の2（子の看護等休暇）\n本文。\n")
    assert chunks[0].structure_path == ("第16条の2（子の看護等休暇）",)


def test_headings_nest_by_level() -> None:
    text = "# A\n## B\n本文1\n## C\n本文2\n# D\n本文3\n"
    paths = [c.structure_path for c in split_document("d.md", text)]
    assert ("A", "B") in paths
    assert ("A", "C") in paths
    assert ("D",) in paths
