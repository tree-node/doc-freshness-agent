"""チャンクの検索インデックス（Stage 1 の土台）。

DESIGN.md の決定に従う:
  - **ベクトルDBは使わない**。3,000チャンク規模は numpy 総当たりで足りる。
    メタデータはJSON、埋め込みは .npy に保存する
  - BM25 の日本語トークン化は**文字バイグラム**（形態素解析の環境依存を持たない）。
    **トークナイザは1関数に隔離**し、取りこぼしが出たら Janome に差し替えられるようにする。
    MeCab系は使わない
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from app.chunking import Chunk
from app.llm.client import Embedder


def tokenize(text: str) -> list[str]:
    """日本語の文字バイグラム＋英数字語。**ここだけ差し替えれば分かち書きを変えられる**。"""
    normalized = "".join(ch if ch.isalnum() else " " for ch in text)
    tokens: list[str] = []
    for word in normalized.split():
        if word.isascii():
            tokens.append(word.lower())
        else:
            tokens.extend(word[i : i + 2] for i in range(max(len(word) - 1, 1)))
    return tokens


def _apply_positive_idf(bm25: BM25Okapi, tokenized: list[list[str]]) -> None:
    """IDFを必ず正になる式に差し替える（Lucene と同じ形）。

    `rank_bm25` の既定のIDFは、**その語がコーパスの半数超の文書に現れると負になる**。
    就業規則ばかりを集めたフォルダでは「看護」「労働者」のような語がまさにそれで、
    一致したチャンクのスコアが負、一致しないチャンクが0となり、**順位が反転する**
    （一致しない文書が上位に来る）。ライブラリのepsilon補正は平均IDF自体が負だと効かない。

        idf(w) = ln(1 + (N - n + 0.5) / (n + 0.5))     ← n がいくつでも正
    """
    n_docs = len(tokenized)
    df: Counter[str] = Counter()
    for doc in tokenized:
        df.update(set(doc))
    bm25.idf = {
        word: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5)) for word, freq in df.items()
    }
    bm25.average_idf = (sum(bm25.idf.values()) / len(bm25.idf)) if bm25.idf else 0.0


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    score: float
    rank: int  # 1始まり


@dataclass
class ChunkIndex:
    """チャンク本体・BM25・埋め込みをまとめて持つ。"""

    chunks: list[Chunk]
    embeddings: np.ndarray | None = None

    def __post_init__(self) -> None:
        self._by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        self._bm25 = None
        if self.chunks:
            tokenized = [tokenize(c.embedding_text) for c in self.chunks]
            self._bm25 = BM25Okapi(tokenized)
            _apply_positive_idf(self._bm25, tokenized)
        if self.embeddings is not None and len(self.embeddings) != len(self.chunks):
            raise ValueError("埋め込みの件数がチャンク数と一致しません")

    def __len__(self) -> int:
        return len(self.chunks)

    def get(self, chunk_id: str) -> Chunk:
        return self._by_id[chunk_id]

    @property
    def has_vectors(self) -> bool:
        return self.embeddings is not None and len(self.embeddings) > 0

    # --- 検索 ---------------------------------------------------------------

    def search_bm25(self, query: str, top_k: int) -> list[Hit]:
        """BM25で上位を返す。

        落とすのは**クエリ語が1つも出てこないチャンクだけ**（スコア0）。IDFを正に揃えて
        あるので、語が1つでも一致すれば必ず0より大きくなる。
        スコアの大小による足切りはしない——閾値の判断は Stage 2 に集約する（DESIGN.md Stage 1）。
        """
        if not self._bm25 or not query.strip():
            return []
        scores = np.asarray(self._bm25.get_scores(tokenize(query)))
        return [hit for hit in self._rank(scores, top_k) if hit.score > 0]

    def search_vector(self, query_vector: list[float], top_k: int) -> list[Hit]:
        if not self.has_vectors:
            return []
        query = np.asarray(query_vector, dtype=np.float32)
        norm = np.linalg.norm(query)
        if norm == 0:
            return []
        scores = self.embeddings @ (query / norm)  # 保存時に正規化済み
        return self._rank(scores, top_k)

    def _rank(self, scores: np.ndarray, top_k: int) -> list[Hit]:
        order = np.argsort(-scores)[: max(top_k, 0)]
        return [
            Hit(chunk_id=self.chunks[idx].chunk_id, score=float(scores[idx]), rank=rank)
            for rank, idx in enumerate(order, start=1)
        ]

    # --- 保存・読み込み -------------------------------------------------------

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "chunks.json").write_text(
            json.dumps([asdict(c) for c in self.chunks], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if self.embeddings is not None:
            np.save(directory / "embeddings.npy", self.embeddings)
        return directory

    @classmethod
    def load(cls, directory: Path) -> "ChunkIndex":
        raw = json.loads((directory / "chunks.json").read_text(encoding="utf-8"))
        chunks = [
            Chunk(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                structure_path=tuple(row["structure_path"]),
                kind=row["kind"],
                text=row["text"],
                start=row["start"],
                end=row["end"],
                content_hash=row["content_hash"],
            )
            for row in raw
        ]
        vectors_path = directory / "embeddings.npy"
        embeddings = np.load(vectors_path) if vectors_path.exists() else None
        return cls(chunks=chunks, embeddings=embeddings)


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def build_index(
    chunks: list[Chunk], embedder: Embedder | None = None, batch_size: int = 64
) -> ChunkIndex:
    """チャンクからインデックスを作る。embedder が無ければBM25のみ（オフラインでも動く）。"""
    embeddings = None
    if embedder is not None and chunks:
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors.extend(embedder.embed([c.embedding_text for c in batch]))
        embeddings = normalize_rows(np.asarray(vectors, dtype=np.float32))
    return ChunkIndex(chunks=chunks, embeddings=embeddings)
