"""文書のチャンク分割（DESIGN.md「取り込みとチャンク分割」）。

分割ルール:
  - 構造単位で分割: 規定 → 条・項単位 / md → 見出し単位 / docx → 見出しスタイル単位
    （docx は取り込み時に見出しを md 記法へ変換済みなので、md と同じ経路で処理する）
  - サイズ目安 200〜800トークン。長い条は項で再分割、**短い条は結合しない**
  - 表は直前の見出しに属する1チャンクとして明示的に拾う
  - 見出しに掛からない残りテキスト（前文など）も捨てずにチャンク化する

チャンクメタデータ:
  - 文書ID + 構造パス / 文字オフセット（修正案の置換位置に使う）/ 本文ハッシュ（キャッシュキー材料）
  - 埋め込み用テキストは構造パスを先頭に付けた別フィールド（表示用本文と分離）
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

# トークン数の近似。日本語は 1トークン ≈ 1.2文字 程度として扱う。
# 正確なトークナイザは段階ごとにモデルが違って一意に決まらないため、目安として1箇所に閉じる。
CHARS_PER_TOKEN = 1.2
TARGET_MIN_TOKENS = 200
TARGET_MAX_TOKENS = 800

MAX_CHARS = int(TARGET_MAX_TOKENS * CHARS_PER_TOKEN)

# 見出し（md記法。docx も取り込み時にこの形へ変換される）
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# 条（社内規定・契約書。法令側は e-Gov APIの構造を使うのでここは通らない）
KANJI_NUM = r"[〇一二三四五六七八九十百千0-9０-９]"
ARTICLE_RE = re.compile(rf"^(第{KANJI_NUM}+条(?:の{KANJI_NUM}+)?)\s*(?:[（(](.+?)[）)])?\s*(.*)$")

# 項（条の中の 2 / ２　/ （2）で始まる行）
PARAGRAPH_RE = re.compile(r"^(?:[（(]?([0-9０-９]{1,2})[）)]?)[　 ]")

# 表（md記法の行、または docx の表をセル区切りで連結した行）
TABLE_LINE_RE = re.compile(r".+\|.+")

ChunkKind = Literal["text", "article", "table"]

# 条は見出し階層の最下層として扱う（章・節の下にぶら下げる）
ARTICLE_LEVEL = 7


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    structure_path: tuple[str, ...]
    kind: ChunkKind
    text: str
    start: int  # 文書テキスト上の開始オフセット
    end: int  # 同・終了オフセット（end は含まない）
    content_hash: str

    @property
    def label(self) -> str:
        return " > ".join(self.structure_path) if self.structure_path else self.doc_id

    @property
    def embedding_text(self) -> str:
        """埋め込み用。構造パスを先頭に付ける（表示用本文とは分ける）。"""
        return f"{self.label}\n{self.text}" if self.structure_path else self.text


def content_hash(text: str) -> str:
    """判定キャッシュのキー材料。

    **doc_id を混ぜない**。同一内容のチャンクが同一キーになることで、
    重複配置されたファイルの片方だけ指摘する事故を設計で防ぐ（DESIGN.md キャッシュと起票）。
    """
    normalized = "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def approx_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


@dataclass
class _Block:
    kind: ChunkKind
    path: tuple[str, ...]
    lines: list[tuple[str, int, int]]  # (行テキスト, start, end)

    @property
    def start(self) -> int:
        return self.lines[0][1]

    @property
    def end(self) -> int:
        return self.lines[-1][2]

    def text(self) -> str:
        return "\n".join(line for line, _, _ in self.lines).strip()


def _iter_lines(text: str):
    offset = 0
    for line in text.split("\n"):
        yield line, offset, offset + len(line)
        offset += len(line) + 1


def _heading(line: str) -> tuple[int, str] | None:
    match = HEADING_RE.match(line)
    if match:
        return len(match.group(1)), match.group(2)
    article = ARTICLE_RE.match(line)
    if article:
        caption = article.group(2)
        title = f"{article.group(1)}（{caption}）" if caption else article.group(1)
        return ARTICLE_LEVEL, title
    return None


def _split_long(block: _Block) -> list[_Block]:
    """長すぎるチャンクを項の切れ目で分ける。項が無ければ行単位で詰める。

    短いチャンクは結合しない（DESIGN.md の分割ルール）。
    """
    if len(block.text()) <= MAX_CHARS:
        return [block]

    groups: list[list[tuple[str, int, int]]] = [[]]
    for entry in block.lines:
        line = entry[0]
        starts_paragraph = bool(PARAGRAPH_RE.match(line))
        current_len = sum(len(l) + 1 for l, _, _ in groups[-1])
        if groups[-1] and (starts_paragraph or current_len >= MAX_CHARS):
            groups.append([])
        groups[-1].append(entry)

    return [_Block(kind=block.kind, path=block.path, lines=lines) for lines in groups if lines]


def split_document(doc_id: str, text: str) -> list[Chunk]:
    """文書テキストをチャンクに分割する。"""
    blocks: list[_Block] = []
    path_stack: list[tuple[int, str]] = []
    current: _Block | None = None

    def flush() -> None:
        nonlocal current
        if current is not None and current.text():
            blocks.append(current)
        current = None

    def current_path() -> tuple[str, ...]:
        return tuple(title for _, title in path_stack)

    for line, start, end in _iter_lines(text):
        heading = _heading(line)
        if heading:
            level, title = heading
            flush()
            while path_stack and path_stack[-1][0] >= level:
                path_stack.pop()
            path_stack.append((level, title))
            kind: ChunkKind = "article" if level == ARTICLE_LEVEL else "text"
            current = _Block(kind=kind, path=current_path(), lines=[(line, start, end)])
            continue

        is_table_line = bool(TABLE_LINE_RE.match(line.strip()))
        if current is None:
            # 見出しの前にある本文（前文など）も捨てない
            current = _Block(kind="table" if is_table_line else "text", path=current_path(), lines=[])
        elif is_table_line and current.kind != "table" and current.text():
            # 表は直前の見出しに属する独立チャンクとして拾う
            flush()
            current = _Block(kind="table", path=current_path(), lines=[])
        elif not is_table_line and current.kind == "table" and line.strip():
            flush()
            current = _Block(kind="text", path=current_path(), lines=[])

        current.lines.append((line, start, end))

    flush()

    chunks: list[Chunk] = []
    for block in blocks:
        for piece in _split_long(block):
            body = piece.text()
            if not body:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#{len(chunks)}",
                    doc_id=doc_id,
                    structure_path=piece.path,
                    kind=piece.kind,
                    text=body,
                    start=piece.start,
                    end=piece.end,
                    content_hash=content_hash(body),
                )
            )
    return chunks
