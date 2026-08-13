"""スナップショットの保存・読み込みと差分検知の単体テスト（ネットワークに出ない）。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.egov.snapshot import LawSnapshot, check_law, diff_snapshots, snapshot_path

LAW_DATA = {
    "revision_info": {
        "law_revision_id": "403AC0000000076_20240531_506AC0000000042",
        "law_title": "テスト法",
        "amendment_enforcement_date": "2024-05-31",
    },
    "law_full_text": {
        "Law": {
            "LawBody": {
                "MainProvision": {
                    "Chapter": [
                        {
                            "ChapterTitle": ["第四章　子の看護休暇"],
                            "Article": [
                                {
                                    "ArticleCaption": "（子の看護休暇の申出）",
                                    "ArticleTitle": "第十六条の二",
                                    "Paragraph": [
                                        {
                                            "Num": "1",
                                            "ParagraphSentence": {
                                                "Sentence": ["小学校就学の始期に達するまでの子…。"]
                                            },
                                        }
                                    ],
                                },
                                {
                                    "ArticleTitle": "第十六条の三",
                                    "Paragraph": [
                                        {"Num": "1", "ParagraphSentence": {"Sentence": ["準用…。"]}}
                                    ],
                                },
                            ],
                        }
                    ]
                }
            }
        }
    },
}


def amended_law_data() -> dict:
    """2025-04-01 改正相当: 章名と条文が変わり、条が1つ増え、1つ削除される。"""
    data = copy.deepcopy(LAW_DATA)
    data["revision_info"] = {
        "law_revision_id": "403AC0000000076_20250401_506AC0000000042",
        "law_title": "テスト法",
        "amendment_enforcement_date": "2025-04-01",
    }
    chapter = data["law_full_text"]["Law"]["LawBody"]["MainProvision"]["Chapter"][0]
    chapter["ChapterTitle"] = ["第四章　子の看護等休暇"]
    art = chapter["Article"][0]
    art["ArticleCaption"] = "（子の看護等休暇の申出）"
    art["Paragraph"][0]["ParagraphSentence"]["Sentence"] = [
        "九歳に達する日以後の最初の三月三十一日までの間にある子…。"
    ]
    chapter["Article"][1] = {
        "ArticleTitle": "第十六条の四",
        "Paragraph": [{"Num": "1", "ParagraphSentence": {"Sentence": ["新設…。"]}}],
    }
    return data


@pytest.fixture
def old_snapshot() -> LawSnapshot:
    return LawSnapshot.from_law_data("403AC0000000076", LAW_DATA, asof="2025-03-01")


@pytest.fixture
def new_snapshot() -> LawSnapshot:
    return LawSnapshot.from_law_data("403AC0000000076", amended_law_data())


def test_snapshot_records_revision_and_asof(old_snapshot: LawSnapshot) -> None:
    assert old_snapshot.law_revision_id.endswith("_20240531_506AC0000000042")
    assert old_snapshot.asof == "2025-03-01"
    assert old_snapshot.enforcement_date == "2024-05-31"
    assert "本則/第四章/第十六条の二" in old_snapshot.provisions


def test_snapshot_roundtrip(tmp_path: Path, old_snapshot: LawSnapshot) -> None:
    path = old_snapshot.save(snapshot_path(tmp_path, old_snapshot.law_id))
    assert LawSnapshot.load(path) == old_snapshot


def test_diff_detects_changed_added_removed(
    old_snapshot: LawSnapshot, new_snapshot: LawSnapshot
) -> None:
    diffs = {d.key: d for d in diff_snapshots(old_snapshot, new_snapshot)}

    changed = diffs["本則/第四章/第十六条の二"]
    assert changed.kind == "changed"
    assert "小学校就学の始期" in changed.before
    assert "九歳に達する日" in changed.after

    assert diffs["本則/第四章/第十六条の四"].kind == "added"

    removed = diffs["本則/第四章/第十六条の三"]
    assert removed.kind == "removed"
    assert removed.after is None  # 削除は後段で「旧条番号を参照し続ける文書」を探すため落とさない

    assert diffs["本則/第四章/#heading"].kind == "changed"  # 章名の改正も検出する


def test_diff_is_empty_for_identical_snapshots(old_snapshot: LawSnapshot) -> None:
    assert diff_snapshots(old_snapshot, old_snapshot) == []


def test_diff_order_is_changed_added_removed(
    old_snapshot: LawSnapshot, new_snapshot: LawSnapshot
) -> None:
    kinds = [d.kind for d in diff_snapshots(old_snapshot, new_snapshot)]
    assert kinds == sorted(kinds, key=lambda k: {"changed": 0, "added": 1, "removed": 2}[k])


class FakeClient:
    """e-Gov に出ずに check_law を検証するための差し替え。"""

    def __init__(self, data: dict) -> None:
        self.data = data

    def get_law_data(self, law_id: str, asof: str | None = None, elm: str | None = None) -> dict:
        return self.data


def test_check_law_reports_event_when_revision_changed(
    tmp_path: Path, old_snapshot: LawSnapshot
) -> None:
    old_snapshot.save(snapshot_path(tmp_path, old_snapshot.law_id))
    event = check_law(FakeClient(amended_law_data()), old_snapshot.law_id, tmp_path)

    assert event is not None
    assert event.from_revision == old_snapshot.law_revision_id
    assert event.to_revision.endswith("_20250401_506AC0000000042")
    assert event.enforcement_date == "2025-04-01"
    assert len(event.diffs) == 4
    assert "第十六条の二" in event.to_json()


def test_check_law_returns_none_when_revision_unchanged(
    tmp_path: Path, old_snapshot: LawSnapshot
) -> None:
    old_snapshot.save(snapshot_path(tmp_path, old_snapshot.law_id))
    assert check_law(FakeClient(LAW_DATA), old_snapshot.law_id, tmp_path) is None


def test_check_law_without_snapshot_tells_how_to_initialize(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="app.cli snapshot"):
        check_law(FakeClient(LAW_DATA), "403AC0000000076", tmp_path)
