#!/usr/bin/env python3
"""e-Gov 法令API v2 の実機確認スクリプト。

**実データに対する回帰チェック**（pytest はネットワークに出ないので、こちらが本物の担保）。
パースは `app.egov` を使う（スクリプト側に第二の実装を持たない。持った結果、附則の条番号が
本則と衝突して条文が消えるバグを一度作っている）。

確認すること:
  1. 育児・介護休業法 / 同施行規則 の law_id が検索で引けること
  2. law_revisions で改正履歴（施行日付き）が取れること
  3. asof で「現行」と「2025年3月時点（2025-04-01改正の施行前）」の両方が取得でき、
     内容が実際に異なること
  4. 条・項が構造化データとして取れること（JSON / XML の両方）
  5. **取りこぼしがないこと**: 本則と附則で条番号が衝突しない、附則の Article を持たない項も拾う

実行: PYTHONPATH=. python scripts/verify_egov.py
"""

from __future__ import annotations

import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.egov import (  # noqa: E402
    LAW_ID_IKUKAI,
    LAW_ID_IKUKAI_RULE,
    EGovClient,
    LawSnapshot,
    diff_snapshots,
    parse_law_full_text,
)

# 2025-04-01 施行の改正前を指す時点。asof は施行日基準なので 3/31 以前ならよい
ASOF_BEFORE = "2025-03-01"

# 2025-04-01 改正で「子の看護休暇」→「子の看護等休暇」に変わった条
SAMPLE_ELM = "Article_16_2"  # 枝番はアンダースコア連結（Article_16の2 は 400）

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)
    return ok


def verify_law_ids(client: EGovClient) -> None:
    print("\n=== 1. 法令IDの特定 ===")
    title = "育児休業、介護休業等育児又は家族介護を行う労働者の福祉に関する法律"
    found = {
        law["law_info"]["law_id"]: (
            law["revision_info"]["law_title"],
            law["law_info"]["law_num"],
            law["law_info"]["law_type"],
        )
        for law in client.search_laws(title)
    }
    for law_id, (t, num, law_type) in found.items():
        print(f"    {law_id}  {law_type:20s} {num}  {t}")

    check("育児・介護休業法の law_id が一致", LAW_ID_IKUKAI in found)
    check("育児・介護休業法施行規則の law_id が一致", LAW_ID_IKUKAI_RULE in found)
    check(
        "同名の別法令（船員向け施行規則）が混在することを確認",
        "403M50000800036" in found,
        "law_title の部分一致だけでIDを確定させないこと",
    )


def verify_revisions(client: EGovClient) -> None:
    print("\n=== 2. 改正履歴（law_revisions） ===")
    revisions = client.get_revisions(LAW_ID_IKUKAI)
    print(f"    revision 件数: {len(revisions)}")
    for rev in revisions[:6]:
        mark = " ※未施行" if rev.is_unenforced else ""
        print(f"    {rev.law_revision_id}  施行 {rev.enforcement_date}  {rev.status}{mark}")

    check("改正履歴が取得できる", len(revisions) > 0, f"{len(revisions)} 件")
    dates = {r.enforcement_date for r in revisions}
    check("2025-04-01 施行のリビジョンが存在する", "2025-04-01" in dates, "時間巻き戻しの対象")
    check("施行日が全件で取れる（緊急度算出に使う）", all(r.enforcement_date for r in revisions))
    check(
        "未施行の改正も取得できる（施行前の先回り検知に使える）",
        any(r.is_unenforced for r in revisions),
    )


def verify_asof_before_after(client: EGovClient) -> None:
    print("\n=== 3. asof による改正前後の取得（最重要） ===")

    for law_id, name in ((LAW_ID_IKUKAI, "育介法"), (LAW_ID_IKUKAI_RULE, "育介法施行規則")):
        current = LawSnapshot.from_law_data(law_id, client.get_law_data(law_id))
        before = LawSnapshot.from_law_data(
            law_id, client.get_law_data(law_id, asof=ASOF_BEFORE), asof=ASOF_BEFORE
        )
        print(f"    {name} 現行          : {current.law_revision_id}")
        print(f"    {name} {ASOF_BEFORE}時点: {before.law_revision_id}")
        check(f"{name}: asof で異なるリビジョンが返る", current.law_revision_id != before.law_revision_id)

        print(f"    {name} ユニット数: 現行 {len(current.provisions)} / 改正前 {len(before.provisions)}")
        check(f"{name}: 現行の条文を取り出せる", len(current.provisions) > 0)
        check(f"{name}: 改正前の条文を取り出せる", len(before.provisions) > 0)

        diffs = diff_snapshots(before, current)
        counts = Counter(d.kind for d in diffs)
        print(
            f"    {name} 差分: 変更 {counts['changed']} / 追加 {counts['added']}"
            f" / 削除 {counts['removed']}"
        )
        for diff in diffs[:3]:
            print(f"      [{diff.kind}] {diff.label}")
        check(f"{name}: 改正前後で実際に差分がある", bool(diffs), "差分0なら時間巻き戻しが成立しない")
        check(
            f"{name}: 附則（経過措置）も差分の対象に入っている",
            any(d.key.startswith("附則") for d in diffs) or counts["added"] > 0,
            f"附則の差分 {sum(1 for d in diffs if d.key.startswith('附則'))} 件",
        )

    print(f"\n    --- 条単位の取得（elm={SAMPLE_ELM}）と内容差分 ---")
    cur = client.get_law_data(LAW_ID_IKUKAI, elm=SAMPLE_ELM)["law_full_text"]["Article"]
    old = client.get_law_data(LAW_ID_IKUKAI, asof=ASOF_BEFORE, elm=SAMPLE_ELM)["law_full_text"][
        "Article"
    ]
    print(f"      現行          : {cur['ArticleTitle']} {cur['ArticleCaption']}")
    print(f"      {ASOF_BEFORE}時点: {old['ArticleTitle']} {old['ArticleCaption']}")
    check("elm で条を名指し取得できる（枝番はアンダースコア連結）", cur.get("ArticleTitle") == "第十六条の二")
    check("同一条の見出しが改正前後で異なる", cur["ArticleCaption"] != old["ArticleCaption"])


def verify_structure(client: EGovClient) -> None:
    print("\n=== 4. 条・項の構造化データ取得 ===")
    art = client.get_law_data(LAW_ID_IKUKAI, elm=SAMPLE_ELM)["law_full_text"]["Article"]
    nums = [str(p.get("Num")) for p in art["Paragraph"]]
    print(f"    JSON: ArticleTitle={art['ArticleTitle']} 項番号={nums}")
    check("JSON: 条見出し・条番号が要素として取れる", bool(art.get("ArticleTitle")))
    check("JSON: 項が構造として取れる", nums == ["1", "2", "3", "4"], str(nums))

    # XML でも同じ構造が取れること（JSON形式は公式に「試行版」注記があるため退避先を確認）
    url = (
        f"https://laws.e-gov.go.jp/api/2/law_data/{LAW_ID_IKUKAI}"
        f"?response_format=xml&elm={SAMPLE_ELM}"
    )
    with urllib.request.urlopen(url, timeout=30) as res:
        root = ET.fromstring(res.read())
    article_el = next(root.iter("Article"), None)
    check("XML: Article 要素が取れる", article_el is not None)
    if article_el is not None:
        xml_nums = [p.get("Num") for p in article_el.findall("Paragraph")]
        print(f"    XML : Article@Num={article_el.get('Num')} 項番号={xml_nums}")
        check("XML: Paragraph 要素と Num 属性が取れる", xml_nums == ["1", "2", "3", "4"], str(xml_nums))


def verify_no_loss(client: EGovClient) -> None:
    """取りこぼし確認。ここが今回いちばん壊れやすかったところ。"""
    print("\n=== 5. 取りこぼしがないこと ===")
    data = client.get_law_data(LAW_ID_IKUKAI)
    provisions = parse_law_full_text(data["law_full_text"])

    keys = [p.key for p in provisions]
    check("キーが一意（本則と附則の条番号が衝突しない）", len(keys) == len(set(keys)), f"{len(keys)} 件")

    titles = [p.title for p in provisions if p.kind == "article"]
    dupes = [t for t, n in Counter(titles).items() if n > 1]
    print(f"    条見出しだけでキーにすると衝突する数: {len(dupes)}（例: {dupes[:3]}）")
    check(
        "条見出しだけをキーにしていたら失われていた条がある＝構造パスが必要",
        len(dupes) > 0,
        f"本則{sum(1 for p in provisions if p.key.startswith('本則') and p.kind == 'article')}条"
        f" / 附則{sum(1 for p in provisions if p.key.startswith('附則') and p.kind == 'article')}条",
    )

    suppl_text = [p for p in provisions if p.key.startswith("附則") and p.kind == "text"]
    check(
        "附則の Article を持たない項も拾えている",
        len(suppl_text) > 0,
        f"{len(suppl_text)} 件",
    )

    rule = parse_law_full_text(client.get_law_data(LAW_ID_IKUKAI_RULE)["law_full_text"])
    check(
        "施行規則の制定文（EnactStatement）も拾えている",
        any(p.title == "EnactStatement" for p in rule),
    )


def main() -> int:
    print("e-Gov 法令API v2 実機確認")
    print(f"  asof(改正前) = {ASOF_BEFORE}")
    with EGovClient() as client:
        verify_law_ids(client)
        verify_revisions(client)
        verify_asof_before_after(client)
        verify_structure(client)
        verify_no_loss(client)

    print("\n=== 結果 ===")
    if _failures:
        print(f"FAIL: {len(_failures)} 件")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("すべて PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
