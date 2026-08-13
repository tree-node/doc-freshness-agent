"""判定キャッシュ。

    cache_key = hash(変更単位) × hash(対象チャンク) × prompt_version

  - キー粒度は**イベントではなく変更単位**（イベント全体でハッシュを取ると、次回改正で
    1条追加されただけで全変更のキャッシュが無効化される）
  - prompt_version を含めないと、プロンプト改善後に古い判定が残る。**プロンプトを変えたら上げる**
  - 同一内容チャンクは同一キー → 同一判定が構造的に保証される
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(
    change_fingerprint: str, chunk_hash: str, prompt_version: str, document_hash: str = ""
) -> str:
    """判定1件のキー。

    `document_hash` は**文書の中身から作る**（ファイル名ではない）ので:
      - 同一内容のファイルが複数置かれていても → 同じキー = 判定は1回、起票は全ファイルに展開
      - 条文が1文字も違わなくても文書全体が違えば → 別のキー = 別々に判定される

    後者が要る理由: 「雇用契約書のひな形」と「締結済みの雇用契約書」は休暇条項が同一でも、
    期限の種別が immediate と on_renewal で分かれる。チャンクだけをキーにすると
    先に判定した方の結果が使い回され、必ずどちらかを取り違える。
    """
    return f"{change_fingerprint}:{chunk_hash}:{document_hash}:{prompt_version}"


def document_hash(chunk_hashes: list[str]) -> str:
    """文書の同一性。チャンクの本文ハッシュを順に連ねたもの。"""
    return hashlib.sha256("|".join(chunk_hashes).encode("utf-8")).hexdigest()[:16]


class JudgementCache:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0
        if path and path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str) -> dict | None:
        value = self._data.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def set(self, key: str, value: dict) -> None:
        self._data[key] = value

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
