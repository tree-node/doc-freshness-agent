"""画面が読むAPIのテスト。ネットワークに出ない。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

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


# --- 修正版ファイルのダウンロード ---------------------------------------------


def a_result_with_fix(doc_id="規程.md"):
    result = a_result()
    result["alerts"] = [
        {
            "doc_id": doc_id,
            "location": f"/watch/{doc_id}",
            "chunk_id": f"{doc_id}#1",
            "change_id": "chg-001",
            "finding": {
                "impact": "affected",
                "evidence_location": "第21条",
                "fix_proposal": {"before": "小学校就学の始期に達するまで", "after": "小学校第三学年修了前"},
            },
        }
    ]
    return result


@pytest.fixture
def watch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "watch"
    directory.mkdir()
    monkeypatch.setattr(api, "watch_root", lambda: directory)
    monkeypatch.setattr(api, "outputs_dir", lambda: tmp_path / "outputs")
    return directory


def test_downloads_a_revised_document(results_dir: Path, watch_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_fix())
    original = "第21条 小学校就学の始期に達するまでの子を養育する従業員は、看護休暇を取得できる。"
    (watch_dir / "規程.md").write_text(original, encoding="utf-8")

    res = client.get("/api/events/403AC0000000076/revised", params={"doc_id": "規程.md"})

    assert res.status_code == 200
    assert "小学校第三学年修了前" in res.text
    assert res.headers["X-Applied-Count"] == "1"
    # 元のファイルには触らない（設計原則2）
    assert (watch_dir / "規程.md").read_text(encoding="utf-8") == original


def test_download_tells_where_to_put_it_back(results_dir: Path, watch_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_fix())
    (watch_dir / "規程.md").write_text("第21条 小学校就学の始期に達するまでの子。", encoding="utf-8")
    res = client.get("/api/events/403AC0000000076/revised", params={"doc_id": "規程.md"})
    assert "規程.md" in unquote(res.headers["X-Replace-Target"])


def test_download_without_a_proposal_is_404(results_dir: Path, watch_dir: Path) -> None:
    write(results_dir, "a.json", a_result())  # alerts が空
    res = client.get("/api/events/403AC0000000076/revised", params={"doc_id": "規程.md"})
    assert res.status_code == 404


def test_download_reports_when_the_fix_does_not_match(results_dir: Path, watch_dir: Path) -> None:
    """当てられなかったときに、成功したふりをして元のままのファイルを返さない。"""
    write(results_dir, "a.json", a_result_with_fix())
    (watch_dir / "規程.md").write_text("まったく別の本文。", encoding="utf-8")
    res = client.get("/api/events/403AC0000000076/revised", params={"doc_id": "規程.md"})
    assert res.status_code == 422
    assert "見つかりません" in res.json()["detail"]


def test_download_of_a_missing_file_is_reported(results_dir: Path, watch_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_fix())
    res = client.get("/api/events/403AC0000000076/revised", params={"doc_id": "規程.md"})
    assert res.status_code == 422


# --- 判断の保存と監査ログ ------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """判断と監査ログのDBはテストごとに分ける（前のテストの記録が混ざらないように）。"""
    path = tmp_path / "app.sqlite"
    monkeypatch.setattr(api, "db_path", lambda: path)
    return path


def a_result_with_finding(doc_id="規程.md", chunk_id="規程.md#1"):
    result = a_result()
    result["changes"][0]["change"]["summary"] = "子の看護休暇の対象が拡大された"
    result["changes"][0]["findings"] = [
        {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "impact": "affected",
            "evidence_location": "第21条",
            "fix_proposal": {"before": "旧", "after": "新"},
        }
    ]
    return result


def test_status_starts_empty(results_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_finding())
    assert client.get("/api/events/403AC0000000076/statuses").json() == {"statuses": []}


def test_saves_a_decision(results_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_finding())
    res = client.put(
        "/api/events/403AC0000000076/statuses",
        json={
            "change_id": "chg-001",
            "chunk_id": "規程.md#1",
            "doc_id": "規程.md",
            "status": "approved",
            "actor": "佐藤",
        },
    )
    assert res.status_code == 200
    assert res.json()["status_label"] == "承認"

    saved = client.get("/api/events/403AC0000000076/statuses").json()["statuses"]
    assert len(saved) == 1
    assert saved[0]["status"] == "approved"


def test_a_rejection_lands_in_the_audit_log_with_its_basis(results_dir: Path) -> None:
    """「対応不要」も、何を根拠にそう決めたかとセットで残す。"""
    write(results_dir, "a.json", a_result_with_finding())
    client.put(
        "/api/events/403AC0000000076/statuses",
        json={
            "change_id": "chg-001",
            "chunk_id": "規程.md#1",
            "doc_id": "規程.md",
            "status": "rejected",
            "note": "適用外と判断",
            "actor": "佐藤",
        },
    )
    entry = client.get("/api/audit").json()["audit"][0]
    assert entry["to_status_label"] == "棄却"
    assert entry["actor"] == "佐藤"
    assert entry["note"] == "適用外と判断"
    assert entry["evidence_location"] == "第21条"
    assert "子の看護休暇" in entry["change_summary"]
    assert entry["law_title"] == "育児・介護休業法"


def test_changing_a_decision_keeps_both_in_the_audit_log(results_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_finding())
    body = {"change_id": "chg-001", "chunk_id": "規程.md#1", "doc_id": "規程.md"}
    client.put("/api/events/403AC0000000076/statuses", json={**body, "status": "pending"})
    client.put("/api/events/403AC0000000076/statuses", json={**body, "status": "approved"})

    audit = client.get("/api/audit").json()["audit"]
    assert [e["to_status"] for e in audit] == ["approved", "pending"]
    assert audit[0]["from_status"] == "pending"


def test_unknown_status_is_rejected(results_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_finding())
    res = client.put(
        "/api/events/403AC0000000076/statuses",
        json={"change_id": "chg-001", "chunk_id": "規程.md#1", "doc_id": "規程.md", "status": "適当"},
    )
    assert res.status_code == 422


def test_status_for_an_unknown_change_is_404(results_dir: Path) -> None:
    write(results_dir, "a.json", a_result_with_finding())
    res = client.put(
        "/api/events/403AC0000000076/statuses",
        json={"change_id": "ない", "chunk_id": "規程.md#1", "doc_id": "規程.md", "status": "approved"},
    )
    assert res.status_code == 404


def test_health_still_works() -> None:
    assert client.get("/api/health").json()["status"] == "ok"


# --- 正本の監視のオン/オフ -----------------------------------------------------


@pytest.fixture
def snapshots_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "snapshots"
    directory.mkdir()
    (directory / "403AC0000000076.json").write_text(
        json.dumps(
            {
                "law_id": "403AC0000000076",
                "law_title": "育児・介護休業法",
                "law_revision_id": "rev",
                "asof": "2025-03-01",
                "fetched_at": "2026-08-15T00:00:00+00:00",
                "provisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "snapshots_dir", lambda: directory)
    return directory


def test_rules_are_enabled_by_default(snapshots_dir: Path) -> None:
    assert client.get("/api/rules").json()["rules"][0]["enabled"] is True


def test_stopping_a_rule_hides_its_events_from_home(results_dir: Path, snapshots_dir: Path) -> None:
    """止めるとホームから消え、再開すると戻る（デモで見せる依存関係）。"""
    write(results_dir, "a.json", a_result())
    assert len(client.get("/api/events").json()["events"]) == 1

    client.put("/api/rules/403AC0000000076", json={"enabled": False})
    assert client.get("/api/events").json()["events"] == []
    assert client.get("/api/rules").json()["rules"][0]["enabled"] is False

    client.put("/api/rules/403AC0000000076", json={"enabled": True})
    assert len(client.get("/api/events").json()["events"]) == 1


def test_stopping_a_rule_does_not_delete_the_result(results_dir: Path, snapshots_dir: Path) -> None:
    """止めても検知結果そのものは残す（見るのをやめるだけ）。"""
    write(results_dir, "a.json", a_result())
    client.put("/api/rules/403AC0000000076", json={"enabled": False})
    assert client.get("/api/events/403AC0000000076").status_code == 200


def test_stopping_an_unregistered_rule_is_404(snapshots_dir: Path) -> None:
    assert client.put("/api/rules/存在しない", json={"enabled": False}).status_code == 404


# --- 正本の検索と登録 ---------------------------------------------------------


class FakeEGov:
    """e-Gov に通信しない差し替え。テストはネットワークに出ない。"""

    def __init__(self, laws=None, snapshot=None, error=None):
        self.laws = laws or []
        self.snapshot = snapshot
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def search_laws(self, law_title, limit=20):
        if self.error:
            raise self.error
        return self.laws

    def get_law_data(self, law_id, asof=None, elm=None):
        if self.error:
            raise self.error
        return self.snapshot


def a_law(law_id="322AC0000000049", title="労働基準法", law_type="Act"):
    return {
        "law_info": {"law_id": law_id, "law_num": "昭和二十二年法律第四十九号", "law_type": law_type},
        "revision_info": {"law_title": title},
    }


def a_law_data(law_id="322AC0000000049", title="労働基準法"):
    return {
        "revision_info": {
            "law_revision_id": f"{law_id}_20190401",
            "law_title": title,
            "amendment_enforcement_date": "2019-04-01",
        },
        "law_full_text": {
            "Law": {
                "LawBody": {
                    "MainProvision": {
                        "Chapter": [
                            {
                                "ChapterTitle": ["第四章　労働時間"],
                                "Article": [{"ArticleTitle": "第三十六条", "Paragraph": [{"Num": "1"}]}],
                            }
                        ]
                    }
                }
            }
        },
    }


def test_search_laws_returns_candidates(monkeypatch: pytest.MonkeyPatch, snapshots_dir: Path) -> None:
    monkeypatch.setattr(api, "egov_client", lambda: FakeEGov(laws=[a_law()]))
    body = client.get("/api/laws", params={"q": "労働基準法"}).json()
    assert body["laws"][0]["law_id"] == "322AC0000000049"
    assert body["laws"][0]["law_type"] == "Act"


def test_search_marks_already_registered_laws(monkeypatch: pytest.MonkeyPatch, snapshots_dir: Path) -> None:
    """登録済みのものが分かるようにする（同じ正本を二重に登録させない）。"""
    monkeypatch.setattr(
        api, "egov_client", lambda: FakeEGov(laws=[a_law(law_id="403AC0000000076", title="育児・介護休業法")])
    )
    assert client.get("/api/laws", params={"q": "育児"}).json()["laws"][0]["registered"] is True


def test_registers_a_law_and_saves_the_snapshot(
    monkeypatch: pytest.MonkeyPatch, snapshots_dir: Path
) -> None:
    monkeypatch.setattr(api, "egov_client", lambda: FakeEGov(snapshot=a_law_data()))
    res = client.post("/api/rules", json={"law_id": "322AC0000000049", "asof": "2019-03-01"})

    assert res.status_code == 200
    assert res.json()["law_title"] == "労働基準法"
    assert res.json()["provisions"] > 0
    assert (snapshots_dir / "322AC0000000049.json").exists()

    titles = [r["law_title"] for r in client.get("/api/rules").json()["rules"]]
    assert "労働基準法" in titles


def test_registering_the_same_law_twice_is_rejected(
    monkeypatch: pytest.MonkeyPatch, snapshots_dir: Path
) -> None:
    monkeypatch.setattr(api, "egov_client", lambda: FakeEGov(snapshot=a_law_data(law_id="403AC0000000076")))
    res = client.post("/api/rules", json={"law_id": "403AC0000000076"})
    assert res.status_code == 409


def test_an_unknown_law_id_is_reported(monkeypatch: pytest.MonkeyPatch, snapshots_dir: Path) -> None:
    from app.egov import EGovError

    monkeypatch.setattr(api, "egov_client", lambda: FakeEGov(error=EGovError("404 見つかりません")))
    res = client.post("/api/rules", json={"law_id": "存在しないID"})
    assert res.status_code == 422
    assert "取得できませんでした" in res.json()["detail"]
