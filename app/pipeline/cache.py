"""判定キャッシュ。

    cache_key = hash(変更単位) × hash(対象チャンク) × prompt_version

  - キー粒度は**イベントではなく変更単位**（イベント全体でハッシュを取ると、次回改正で
    1条追加されただけで全変更のキャッシュが無効化される）
  - prompt_version を含めないと、プロンプト改善後に古い判定が残る。**プロンプトを変えたら上げる**
  - 同一内容チャンクは同一キー → 同一判定が構造的に保証される
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cache_key(change_fingerprint: str, chunk_hash: str, prompt_version: str) -> str:
    return f"{change_fingerprint}:{chunk_hash}:{prompt_version}"


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
