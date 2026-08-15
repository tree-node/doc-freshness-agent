"""判断の保存と監査ログのテスト。ネットワークに出ない。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.store import (
    FindingKey,
    UnknownStatusError,
    get_status,
    init_db,
    list_audit,
    list_statuses,
    set_status,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "app.sqlite"
    init_db(path)
    return path


def a_key(chunk="就業規則.docx#3", doc="株式会社サクラベース/就業規則.docx") -> FindingKey:
    return FindingKey(law_id="322AC0000000049", change_id="chg-001", chunk_id=chunk, doc_id=doc)


# --- ステータス ---------------------------------------------------------------


def test_no_status_before_anyone_decides(db: Path) -> None:
    assert get_status(a_key(), db_path=db) is None


def test_saves_and_reads_back(db: Path) -> None:
    set_status(a_key(), "approved", actor="佐藤", db_path=db)
    record = get_status(a_key(), db_path=db)
    assert record.status == "approved"
    assert record.updated_by == "佐藤"
    assert record.to_dict()["status_label"] == "承認"


def test_changing_the_decision_overwrites_it(db: Path) -> None:
    set_status(a_key(), "pending", db_path=db)
    set_status(a_key(), "rejected", db_path=db)
    assert get_status(a_key(), db_path=db).status == "rejected"
    assert len(list_statuses("322AC0000000049", db_path=db)) == 1


def test_unknown_status_is_rejected(db: Path) -> None:
    with pytest.raises(UnknownStatusError, match="不明なステータス"):
        set_status(a_key(), "なんとなく", db_path=db)


def test_statuses_are_per_document(db: Path) -> None:
    """同じ内容のチャンクが複数ファイルにあっても、判断はファイルごとに持つ。"""
    set_status(a_key(doc="株式会社サクラベース/就業規則.docx"), "approved", db_path=db)
    set_status(a_key(doc="共有フォルダ（未整理）/就業規則.docx"), "rejected", db_path=db)
    statuses = {s.doc_id: s.status for s in list_statuses("322AC0000000049", db_path=db)}
    assert statuses == {
        "株式会社サクラベース/就業規則.docx": "approved",
        "共有フォルダ（未整理）/就業規則.docx": "rejected",
    }


# --- 監査ログ -----------------------------------------------------------------


def test_every_decision_is_recorded(db: Path) -> None:
    set_status(a_key(), "approved", actor="佐藤", db_path=db)
    entries = list_audit(db_path=db)
    assert len(entries) == 1
    assert entries[0].actor == "佐藤"
    assert entries[0].to_status == "approved"
    assert entries[0].from_status is None


def test_rejection_is_recorded_too(db: Path) -> None:
    """「対応不要」の判断こそ記録が要る（何を見送ったか分からないと監査にならない）。"""
    set_status(a_key(), "rejected", note="業務委託のため適用外と判断", db_path=db)
    entry = list_audit(db_path=db)[0]
    assert entry.to_status == "rejected"
    assert entry.note == "業務委託のため適用外と判断"


def test_audit_keeps_the_previous_decision(db: Path) -> None:
    """判断を変えても過去の判断は消さない（追記のみ）。"""
    set_status(a_key(), "pending", db_path=db)
    set_status(a_key(), "approved", db_path=db)
    entries = list_audit(db_path=db)
    assert len(entries) == 2
    assert entries[0].to_status == "approved"
    assert entries[0].from_status == "pending"
    assert entries[1].to_status == "pending"


def test_audit_holds_the_legal_basis(db: Path) -> None:
    """どの改正を根拠に判断したかをセットで持つ（DESIGN.md 監査ログ）。"""
    set_status(
        a_key(),
        "approved",
        law_title="労働基準法",
        evidence_law="労働基準法 附則第百三十八条",
        evidence_location="第40条(割増賃金)",
        change_summary="中小事業主への割増賃金率の適用猶予が廃止された",
        db_path=db,
    )
    entry = list_audit(db_path=db)[0]
    assert entry.law_title == "労働基準法"
    assert entry.evidence_law == "労働基準法 附則第百三十八条"
    assert entry.evidence_location == "第40条(割増賃金)"
    assert "適用猶予" in entry.change_summary


def test_audit_is_newest_first(db: Path) -> None:
    set_status(a_key(chunk="a"), "approved", db_path=db)
    set_status(a_key(chunk="b"), "rejected", db_path=db)
    entries = list_audit(db_path=db)
    assert [e.chunk_id for e in entries] == ["b", "a"]


def test_audit_can_be_filtered_by_law(db: Path) -> None:
    set_status(a_key(), "approved", db_path=db)
    other = FindingKey(law_id="403AC0000000076", change_id="c", chunk_id="x", doc_id="d")
    set_status(other, "rejected", db_path=db)
    entries = list_audit(law_id="403AC0000000076", db_path=db)
    assert len(entries) == 1
    assert entries[0].law_id == "403AC0000000076"


def test_schema_is_created_on_demand(tmp_path: Path) -> None:
    """init_db を呼び忘れていても落ちない（デモ中に初期化漏れで死なないように）。"""
    path = tmp_path / "fresh.sqlite"
    set_status(a_key(), "approved", db_path=path)
    assert get_status(a_key(), db_path=path).status == "approved"


# --- 正本の監視のオン/オフ -----------------------------------------------------


def test_rules_are_watched_by_default(db: Path) -> None:
    """登録されていれば監視中。設定した覚えが無いのに止まっている、を作らない。"""
    from app.store import is_rule_enabled

    assert is_rule_enabled("322AC0000000049", db_path=db) is True


def test_can_stop_and_resume_watching(db: Path) -> None:
    from app.store import disabled_law_ids, is_rule_enabled, set_rule_enabled

    set_rule_enabled("322AC0000000049", False, db_path=db)
    assert is_rule_enabled("322AC0000000049", db_path=db) is False
    assert disabled_law_ids(db_path=db) == {"322AC0000000049"}

    set_rule_enabled("322AC0000000049", True, db_path=db)
    assert is_rule_enabled("322AC0000000049", db_path=db) is True
    assert disabled_law_ids(db_path=db) == set()


def test_stopping_one_rule_leaves_the_others_alone(db: Path) -> None:
    from app.store import disabled_law_ids, set_rule_enabled

    set_rule_enabled("322AC0000000049", False, db_path=db)
    assert disabled_law_ids(db_path=db) == {"322AC0000000049"}


def test_stopping_a_rule_keeps_the_decisions(db: Path) -> None:
    """監視を止めても、その正本に対して下した判断は消さない（再開すれば戻る）。"""
    from app.store import set_rule_enabled

    set_status(a_key(), "approved", db_path=db)
    set_rule_enabled("322AC0000000049", False, db_path=db)
    assert get_status(a_key(), db_path=db).status == "approved"
    assert len(list_audit(db_path=db)) == 1
