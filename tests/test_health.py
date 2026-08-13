from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["db"]["writable"] is True


def test_health_does_not_leak_secrets() -> None:
    """APIキーは「設定済みかどうか」だけを返し、値そのものは返さない。"""
    body = client.get("/api/health").json()
    assert isinstance(body["configured"]["orcarouter_api_key"], bool)
    assert "sk-" not in json.dumps(body, ensure_ascii=False)


def test_health_includes_egov_attribution() -> None:
    """e-Gov 出典明示（政府標準利用規約）はフッター表示のためAPIから配る。"""
    body = client.get("/api/health").json()
    assert "e-Gov" in body["attribution"]
