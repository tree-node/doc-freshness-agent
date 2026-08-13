"""評価スクリプトのテスト。ネットワークに出ない。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from evaluate import Expected, Finding, evaluate, matches  # noqa: E402


def expected(doc_id="規程.docx", location="第21条第2項", impact="affected", deadline="immediate", law="労働基準法"):
    return Expected(
        doc_id=doc_id, location=location, impact=impact, deadline_type=deadline,
        law=law, change="第36条", note="",
    )


def finding(doc_id="規程.docx", label="(時間外労働) > 第21条", impact="affected", deadline="immediate", conf=0.9):
    return Finding(
        doc_id=doc_id, label=label, location="第21条第2項", impact=impact,
        deadline_type=deadline, confidence=conf, needs_review=False,
        change_id="chg-001", source="r.json",
    )


def test_matches_on_article_number_not_on_exact_string() -> None:
    assert matches(expected(), finding())


def test_does_not_match_a_different_article() -> None:
    assert not matches(expected(location="第40条"), finding())


def test_does_not_match_a_different_document() -> None:
    assert not matches(expected(), finding(doc_id="別の規程.docx"))


def test_whole_document_expectation_matches_any_finding_in_it() -> None:
    """該当箇所が「—」の行は、その文書のどの指摘とも突き合わせる。"""
    assert matches(expected(location="—", impact="none"), finding())


def test_detection_is_counted() -> None:
    report = evaluate([expected()], [finding()])
    assert len(report.detected) == 1
    assert not report.missed
    assert not report.over


def test_missing_detection_is_a_false_negative() -> None:
    report = evaluate([expected()], [])
    assert len(report.missed) == 1
    assert not report.detected


def test_flagging_a_compliant_document_is_a_false_positive() -> None:
    clean = expected(doc_id="対応済み.docx", location="—", impact="none", deadline="none")
    report = evaluate([clean], [finding(doc_id="対応済み.docx")])
    assert len(report.over) == 1
    assert not report.correctly_excluded


def test_not_flagging_a_compliant_document_is_a_true_negative() -> None:
    clean = expected(doc_id="対応済み.docx", location="—", impact="none", deadline="none")
    report = evaluate([clean], [])
    assert len(report.correctly_excluded) == 1
    assert not report.over


def test_rows_without_a_matching_amendment_are_excluded_from_the_count() -> None:
    """改正イベントが無い行は見逃しに数えない（数えると数字が嘘になる）。"""
    row = expected(location="第40条第2項", law="（対応する改正なし）")
    report = evaluate([row], [])
    assert not report.missed
    assert len(report.out_of_scope) == 1


def test_wrong_deadline_type_is_reported_separately() -> None:
    """検出はできているが期限の種別を取り違えた場合は、見逃しでも過検出でもない。"""
    row = expected(doc_id="ひな形.md", location="第4条", deadline="immediate")
    got = finding(doc_id="ひな形.md", label="ひな形 > 第4条", deadline="on_renewal")
    report = evaluate([row], [got])
    assert len(report.detected) == 1
    assert len(report.wrong_deadline) == 1
    assert not report.over


def test_a_finding_matching_no_expectation_is_over_detection() -> None:
    report = evaluate([], [finding(doc_id="無関係.md")])
    assert len(report.over) == 1


def test_non_affected_findings_are_ignored() -> None:
    """「影響なし」「適用外」の判定は指摘ではないので過検出に数えない。"""
    report = evaluate([], [finding(impact="none"), finding(impact="not_applicable")])
    assert not report.over
