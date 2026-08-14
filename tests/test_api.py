"""画面が読むAPIのテスト。ネットワークに出ない。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.history import load_checks, record_check
from app.main import app

client = TestClient(app)


def a_result(law_id="403AC0000000076", detected_at="2026-08-14T00:00:00+00:00", affected=2, judged=5):
    return {
        "law_id": law_id,
        "law_title": "育児・介護休業法",
        "from_revision": "rev-old",
        "to_revision": "rev-new",
        "enforcement_date": "2025-04-01",
        "detected_at": detected_at,
        "changes": [
            {
                "change": {"change_id": "chg-001", "target_path": "第十六条の二", "change_type": "amend"},
                "candidates": [],
                "stage2_scores": {},
                "findings": [],
                "funnel": {"total_chunks": 171, "stage3_judged": judged, "affected": affected},
            }
        ],
        "alerts": [],
        "cost": {"calls": 60, "cost_usd": 0.1},
    }


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "results"
    directory.mkdir()
    monkeypatch.setattr(api, "results_dir", lambda: directory)
    return directory


@pytest.fixture
def history_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(api, "history_path", lambda: path)
    return path


def write(directory: Path, name: str, payload: dict) -> None:
    (directory / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --- イベント ---------------------------------------------------------------


def test_events_are_empty_before_any_check(results_dir: Path) -> None:
    res = client.get("/api/events")
    assert res.status_code == 200
    assert res.json() == {"events": []}


def test_events_returns_the_pipeline_output_as_is(results_dir: Path) -> None:
    """画面用に加工しない。CLIの出力と画面の表示を二重管理にしないため。"""
    write(results_dir, "a.json", a_result())
    body = client.get("/api/events").json()
    assert len(body["events"]) == 1
    assert body["events"][0]["law_id"] == "403AC0000000076"
    assert body["events"][0]["changes"][0]["funnel"]["stage3_judged"] == 5


def test_events_are_sorted_newest_first(results_dir: Path) -> None:
    write(results_dir, "old.json", a_result(law_id="A", detected_at="2026-08-10T00:00:00+00:00"))
    write(results_dir, "new.json", a_result(law_id="B", detected_at="2026-08-14T00:00:00+00:00"))
    ids = [e["law_id"] for e in client.get("/api/events").json()["events"]]
    assert ids == ["B", "A"]


def test_a_broken_file_does_not_take_down_the_list(results_dir: Path) -> None:
    write(results_dir, "ok.json", a_result())
    (results_dir / "broken.json").write_text("{ これはJSONではない", encoding="utf-8")
    assert len(client.get("/api/events").json()["events"]) == 1


def test_get_event_by_law_id(results_dir: Path) -> None:
    write(results_dir, "a.json", a_result())
    res = client.get("/api/events/403AC0000000076")
    assert res.status_code == 200
    assert res.json()["law_title"] == "育児・介護休業法"


def test_unknown_event_is_404(results_dir: Path) -> None:
    assert client.get("/api/events/存在しない").status_code == 404


# --- 見守り中のルール --------------------------------------------------------


def test_rules_come_from_registered_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "322AC0000000049.json").write_text(
        json.dumps(
            {
                "law_id": "322AC0000000049",
                "law_title": "労働基準法",
                "law_revision_id": "rev",
                "asof": "2019-03-01",
                "fetched_at": "2026-08-14T00:00:00+00:00",
                "provisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "snapshots_dir", lambda: snapshots)

    rules = client.get("/api/rules").json()["rules"]
    assert len(rules) == 1
    assert rules[0]["law_title"] == "労働基準法"
    assert rules[0]["watching_since"] == "2019-03-01"


# --- チェック履歴 ------------------------------------------------------------


def test_history_includes_checks_with_no_change(results_dir: Path, history_path: Path) -> None:
    """変更が無かったチェックも履歴に出す（DESIGN.md 原則3）。"""
    record_check(history_path, law_id="322AC0000000049", law_title="労働基準法", detected=False)
    entries = client.get("/api/history").json()["history"]
    assert len(entries) == 1
    assert entries[0]["detected"] is False
    assert "summary" not in entries[0]


def test_history_attaches_the_breakdown_when_something_was_detected(
    results_dir: Path, history_path: Path
) -> None:
    write(results_dir, "a.json", a_result(affected=2, judged=5))
    record_check(
        history_path, law_id="403AC0000000076", law_title="育児・介護休業法", detected=True, revision="rev-new"
    )
    entry = client.get("/api/history").json()["history"][0]
    assert entry["detected"] is True
    assert entry["summary"] == {"judged": 5, "affected": 2, "not_affected": 3}


def test_history_is_newest_first(history_path: Path, results_dir: Path) -> None:
    record_check(history_path, law_id="A", law_title="法A", detected=False)
    record_check(history_path, law_id="B", law_title="法B", detected=False)
    entries = client.get("/api/history").json()["history"]
    assert [e["law_id"] for e in entries] == ["B", "A"]


def test_history_survives_a_broken_line(history_path: Path) -> None:
    record_check(history_path, law_id="A", law_title="法A", detected=False)
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write("これはJSONではない\n")
    assert len(load_checks(history_path)) == 1


def test_health_still_works() -> None:
    assert client.get("/api/health").json()["status"] == "ok"
