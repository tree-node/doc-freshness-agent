#!/usr/bin/env python3
"""正解セットとの突き合わせ（DESIGN.md「正解セットと精度報告」）。

  - **見逃し（偽陰性）と過検出（偽陽性）を分けて出す**。率だけを出さない
  - 「影響あり10件中10件検出、影響なし15件中14件を正しく除外（1件過検出）」の形で報告する
  - 正解表で「対応する改正なし」となっている行は**集計から外す**。改正イベントが存在せず、
    このプロダクトの検知対象ではないため（見逃しとして数えると数字が嘘になる）

実行:
    PYTHONPATH=. python scripts/evaluate.py data/results/*.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "demo-data" / "答え合わせ" / "正解表.tsv"

ARTICLE_RE = re.compile(r"第[0-9０-９一二三四五六七八九十百千]+条(?:の[0-9０-９一二三四五六七八九十百]+)?")
OUT_OF_SCOPE = "（対応する改正なし）"


@dataclass
class Expected:
    doc_id: str
    location: str
    impact: str
    deadline_type: str
    law: str
    change: str
    note: str

    @property
    def articles(self) -> list[str]:
        return ARTICLE_RE.findall(self.location)

    @property
    def in_scope(self) -> bool:
        """改正イベントに紐づくか。紐づかないものは検知対象ではない。"""
        return self.law not in (OUT_OF_SCOPE, "—", "")

    @property
    def should_be_flagged(self) -> bool:
        return self.impact == "affected"


@dataclass
class Finding:
    doc_id: str
    label: str
    location: str
    impact: str
    deadline_type: str
    confidence: float
    needs_review: bool
    change_id: str
    source: str

    @property
    def articles(self) -> list[str]:
        return ARTICLE_RE.findall(f"{self.label} {self.location}")


@dataclass
class Report:
    detected: list[tuple[Expected, Finding]] = field(default_factory=list)
    missed: list[Expected] = field(default_factory=list)
    over: list[Finding] = field(default_factory=list)
    correctly_excluded: list[Expected] = field(default_factory=list)
    wrong_deadline: list[tuple[Expected, Finding]] = field(default_factory=list)
    out_of_scope: list[Expected] = field(default_factory=list)
    cost_usd: float = 0.0
    stage3_judged: int = 0


def load_truth(path: Path) -> list[Expected]:
    with path.open(encoding="utf-8") as handle:
        return [
            Expected(
                doc_id=row["doc_id"],
                location=row["該当箇所"],
                impact=row["期待判定"],
                deadline_type=row["deadline_type"],
                law=row["根拠の正本"],
                change=row["根拠の変更"],
                note=row["備考"],
            )
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def load_findings(paths: list[Path]) -> tuple[list[Finding], float, int]:
    findings: list[Finding] = []
    cost = 0.0
    judged = 0
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cost += payload.get("cost", {}).get("cost_usd") or 0.0
        for change in payload.get("changes", []):
            judged += change["funnel"]["stage3_judged"]
            for row in change["findings"]:
                findings.append(
                    Finding(
                        doc_id=row["doc_id"],
                        label=row["label"],
                        location=row["evidence_location"],
                        impact=row["impact"],
                        deadline_type=row["deadline_type"],
                        confidence=row["confidence"],
                        needs_review=row["needs_human_review"],
                        change_id=change["change"]["change_id"],
                        source=path.name,
                    )
                )
    return findings, cost, judged


def matches(expected: Expected, finding: Finding) -> bool:
    if expected.doc_id != finding.doc_id:
        return False
    if not expected.articles:
        return True  # 文書全体に対する期待（「影響なし」など）
    return bool(set(expected.articles) & set(finding.articles))


def evaluate(truth: list[Expected], findings: list[Finding]) -> Report:
    report = Report()
    flagged = [f for f in findings if f.impact == "affected"]
    claimed: set[int] = set()

    for expected in truth:
        if not expected.in_scope and expected.should_be_flagged:
            report.out_of_scope.append(expected)
            continue

        hits = [
            (i, f) for i, f in enumerate(flagged) if matches(expected, f)
        ]
        if expected.should_be_flagged:
            if hits:
                index, finding = hits[0]
                claimed.update(i for i, _ in hits)
                report.detected.append((expected, finding))
                if expected.deadline_type != finding.deadline_type:
                    report.wrong_deadline.append((expected, finding))
            else:
                report.missed.append(expected)
        else:
            if hits:
                claimed.update(i for i, _ in hits)
                report.over.extend(f for _, f in hits)
            else:
                report.correctly_excluded.append(expected)

    # どの期待にも当たらなかった「影響あり」も過検出
    for index, finding in enumerate(flagged):
        if index not in claimed:
            report.over.append(finding)

    return report


def print_report(report: Report) -> None:
    detected, missed = len(report.detected), len(report.missed)
    target = detected + missed
    excluded, over = len(report.correctly_excluded), len(report.over)

    print("=" * 72)
    print("精度")
    print("=" * 72)
    print(f"  影響あり {target} 件中 {detected} 件を検出（見逃し {missed} 件）")
    print(f"  影響なし {excluded + over} 件中 {excluded} 件を正しく除外（過検出 {over} 件）")
    if report.out_of_scope:
        print(f"  ※ 集計対象外 {len(report.out_of_scope)} 件（改正イベントに紐づかないため検知対象ではない）")

    if report.missed:
        print("\n--- 見逃し（致命的。ここをゼロにする） ---")
        for e in report.missed:
            print(f"  ✗ {e.doc_id} / {e.location}")
            print(f"      根拠: {e.law} {e.change}")

    if report.over:
        print("\n--- 過検出（棄却フローで吸収できる） ---")
        for f in sorted(report.over, key=lambda x: -x.confidence):
            mark = "要確認" if f.needs_review else "　　　"
            print(f"  △ [{mark}] conf={f.confidence:<5} {f.doc_id} / {f.label[-24:]}")

    if report.wrong_deadline:
        print("\n--- 期限の種別が違う（検出はできている） ---")
        for e, f in report.wrong_deadline:
            print(f"  ! {e.doc_id} / {e.location}: 正解 {e.deadline_type} → 判定 {f.deadline_type}")

    if report.detected:
        print("\n--- 検出できたもの ---")
        for e, f in report.detected:
            print(f"  ✓ conf={f.confidence:<5} {e.doc_id} / {e.location}")

    if report.out_of_scope:
        print("\n--- 集計対象外（改正イベントが無い） ---")
        for e in report.out_of_scope:
            print(f"  - {e.doc_id} / {e.location}: {e.note[:60]}")

    print("\n" + "=" * 72)
    print(f"  精査 {report.stage3_judged} 件 / コスト実測 ${report.cost_usd:.4f}")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="正解セットとの突き合わせ")
    parser.add_argument("results", nargs="+", help="run コマンドが出した結果JSON")
    parser.add_argument("--truth", default=str(TRUTH), help="正解表のTSV")
    parser.add_argument("--json", help="集計結果の書き出し先")
    args = parser.parse_args(argv)

    truth = load_truth(Path(args.truth))
    findings, cost, judged = load_findings([Path(p) for p in args.results])
    report = evaluate(truth, findings)
    report.cost_usd = cost
    report.stage3_judged = judged
    print_report(report)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "detected": len(report.detected),
                    "missed": len(report.missed),
                    "correctly_excluded": len(report.correctly_excluded),
                    "over_detected": len(report.over),
                    "wrong_deadline": len(report.wrong_deadline),
                    "out_of_scope": len(report.out_of_scope),
                    "cost_usd": report.cost_usd,
                    "stage3_judged": report.stage3_judged,
                    "missed_detail": [f"{e.doc_id} / {e.location}" for e in report.missed],
                    "over_detail": [
                        {"doc_id": f.doc_id, "label": f.label, "confidence": f.confidence,
                         "needs_review": f.needs_review}
                        for f in report.over
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return 1 if report.missed else 0


if __name__ == "__main__":
    sys.exit(main())
