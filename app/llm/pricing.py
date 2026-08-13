"""モデルの単価表（コスト実測表示に使う）。

OrcaRouter の `/v1/models` は `pricing.prompt_per_million` / `completion_per_million` を返すので、
usage のトークン数と掛け合わせて1リクエストのコストを出す。

注意: 応答に入ってくるモデル名はフェイルオーバーで `jp.anthropic.claude-sonnet-5` のように
変化する。**単価の引き当てには、こちらが指定したモデル名（requested_model）を使う**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

MODELS_URL = "https://api.orcarouter.ai/v1/models"


@dataclass(frozen=True)
class Price:
    prompt_per_million: float
    completion_per_million: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.prompt_per_million + completion_tokens * self.completion_per_million
        ) / 1_000_000


class PriceTable:
    def __init__(self, prices: dict[str, Price]) -> None:
        self._prices = prices

    def __len__(self) -> int:
        return len(self._prices)

    def cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        price = self._prices.get(model)
        if price is None:
            return None
        return price.cost(prompt_tokens, completion_tokens)

    @classmethod
    def from_payload(cls, payload: dict) -> "PriceTable":
        prices: dict[str, Price] = {}
        for model in payload.get("data", []):
            pricing = model.get("pricing") or {}
            try:
                prices[model["id"]] = Price(
                    prompt_per_million=float(pricing["prompt_per_million"]),
                    completion_per_million=float(pricing["completion_per_million"]),
                )
            except (KeyError, TypeError, ValueError):
                continue  # 価格が取れないモデルは黙って飛ばす（コスト表示が欠けるだけ）
        return cls(prices)

    @classmethod
    def fetch(cls, cache_path: Path | None = None, timeout: float = 15.0) -> "PriceTable":
        """単価表を取得する。取得できなければ空の表を返す（コスト表示が出ないだけで処理は続く）。"""
        try:
            payload = httpx.get(MODELS_URL, timeout=timeout).json()
        except Exception:
            if cache_path and cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            else:
                return cls({})
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return cls.from_payload(payload)
