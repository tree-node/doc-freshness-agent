"""単価表とコスト実測のテスト。ネットワークに出ない。"""

from __future__ import annotations

from app.llm.client import CostLog, Usage
from app.llm.pricing import PriceTable

PAYLOAD = {
    "data": [
        {
            "id": "anthropic/claude-sonnet-5",
            "pricing": {"prompt_per_million": "2.000000", "completion_per_million": "10.000000"},
        },
        {
            "id": "google/gemini-3.5-flash-lite",
            "pricing": {"prompt_per_million": "0.100000", "completion_per_million": "0.400000"},
        },
        {"id": "壊れているモデル", "pricing": {}},
    ]
}


def test_price_table_skips_models_without_pricing() -> None:
    table = PriceTable.from_payload(PAYLOAD)
    assert len(table) == 2
    assert table.cost("壊れているモデル", 1000, 100) is None


def test_cost_is_computed_from_tokens() -> None:
    table = PriceTable.from_payload(PAYLOAD)
    cost = table.cost("anthropic/claude-sonnet-5", 1_000_000, 100_000)
    assert cost == 2.0 + 1.0


def test_cost_log_uses_the_requested_model_not_the_failover_name() -> None:
    """フェイルオーバーで応答のモデル名が変わっても単価を引けること。"""
    log = CostLog(prices=PriceTable.from_payload(PAYLOAD))
    log.add(
        Usage(
            model="jp.anthropic.claude-sonnet-5",  # ゲートウェイが返す名前
            requested_model="anthropic/claude-sonnet-5",  # こちらが指定した名前
            prompt_tokens=1_000_000,
            completion_tokens=0,
        )
    )
    summary = log.summary()
    assert summary["cost_usd"] == 2.0
    assert "anthropic/claude-sonnet-5" in summary["by_model"]


def test_cost_log_works_without_a_price_table() -> None:
    log = CostLog()
    log.add(Usage(model="m", prompt_tokens=100, completion_tokens=10))
    summary = log.summary()
    assert summary["calls"] == 1
    assert summary["total_tokens"] == 110
    assert summary["cost_usd"] is None  # 単価が無くても処理は続く


def test_price_table_returns_empty_when_unreachable(tmp_path, monkeypatch) -> None:
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    assert len(PriceTable.fetch(tmp_path / "pricing.json")) == 0
