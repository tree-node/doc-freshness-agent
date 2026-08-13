#!/usr/bin/env python3
"""e-Gov 法令API v2 の実機確認スクリプト（PROGRESS.md「次にやる」#4）。

確認すること:
  1. 育児・介護休業法 / 同施行規則 の law_id が検索で引けること
  2. law_revisions で改正履歴（施行日付き）が取れること
  3. asof（時点指定）で「現行」と「2025年3月時点（2025-04-01改正の施行前）」の
     両方の条文が取得でき、内容が実際に異なること
  4. 条・項が構造化データとして取れること（正規表現でパースしない）
     — JSON (json_format=light) と XML の両方で確認

依存なし（標準ライブラリのみ）。ネットワークに出るため CI では実行しない想定。
出典: e-Gov 法令検索（デジタル庁）法令API v2 https://laws.e-gov.go.jp/
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_BASE = "https://laws.e-gov.go.jp/api/2"

# 調査で特定した法令ID（PROGRESS.md 決定ログ参照）
LAW_ID_IKUKAI = "403AC0000000076"  # 育児・介護休業法（平成三年法律第七十六号）
LAW_ID_IKUKAI_RULE = "403M50002000025"  # 同施行規則（平成三年労働省令第二十五号）

# 2025-04-01 施行の改正前を指す時点。asof は施行日基準なので 3/31 以前ならよい
ASOF_BEFORE = "2025-03-01"

# 2025-04-01 改正で「子の看護休暇」→「子の看護等休暇」に変わった条
SAMPLE_ELM = "Article_16_2"  # 枝番はアンダースコア連結（Article_16の2 は 400 になる）

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)
    return ok


def get(path: str, **params: str) -> bytes:
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "doc-freshness-agent/verify"})
    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read()
    print(f"    GET {url}  -> {len(body):,} bytes")
    time.sleep(0.3)  # 公開APIへの連投を避ける
    return body


def get_json(path: str, **params: str) -> dict:
    return json.loads(get(path, **params))


# --- 構造化データの取り出し（正規表現を使わない） -------------------------------


def iter_articles(node: object):
    """法令本文JSON(light)を再帰的に歩いて Article ノードを列挙する。

    章・節・款のネストが法令ごとに違うため、構造を決め打ちせず Article キーを探す。
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Article":
                for art in value if isinstance(value, list) else [value]:
                    yield art
            else:
                yield from iter_articles(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_articles(item)


def collect_text(node: object, out: list[str]) -> None:
    """Article 配下の文字列をすべて拾う（項・号・細分を問わず本文比較に使う）。"""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            collect_text(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_text(item, out)


def article_map(law_full_text: dict) -> dict[str, str]:
    """{条見出し番号: 本文（連結）} を返す。"""
    result: dict[str, str] = {}
    for art in iter_articles(law_full_text):
        title = art.get("ArticleTitle")
        if not title:
            continue
        parts: list[str] = []
        collect_text(art, parts)
        result[title] = "".join(parts)
    return result


def paragraph_nums(article: dict) -> list[str]:
    """条の直下の項番号を構造から取り出す。"""
    paras = article.get("Paragraph")
    if paras is None:
        return []
    if isinstance(paras, dict):
        paras = [paras]
    return [str(p.get("Num")) for p in paras]


# --- 各確認項目 ---------------------------------------------------------------


def verify_law_ids() -> None:
    print("\n=== 1. 法令IDの特定 ===")
    title = "育児休業、介護休業等育児又は家族介護を行う労働者の福祉に関する法律"
    data = get_json("laws", law_title=title, limit="20")

    found = {}
    for law in data.get("laws", []):
        info = law["law_info"]
        rev = law["revision_info"]
        found[info["law_id"]] = (rev["law_title"], info["law_num"], info["law_type"])
    for law_id, (t, num, law_type) in found.items():
        print(f"    {law_id}  {law_type:20s} {num}  {t}")

    check(
        "育児・介護休業法の law_id が一致",
        LAW_ID_IKUKAI in found,
        f"{LAW_ID_IKUKAI} = {found.get(LAW_ID_IKUKAI, ('見つからない',))[0]}",
    )
    check(
        "育児・介護休業法施行規則の law_id が一致",
        LAW_ID_IKUKAI_RULE in found,
        f"{LAW_ID_IKUKAI_RULE} = {found.get(LAW_ID_IKUKAI_RULE, ('見つからない',))[0]}",
    )
    # 「船員に関する〜施行規則」が同名で混ざるため、law_title 部分一致だけで確定させない
    check(
        "同名の別法令（船員向け施行規則）が検索結果に混在することを確認",
        "403M50000800036" in found,
        "law_title の部分一致だけでIDを確定させないこと",
    )


def verify_revisions() -> None:
    print("\n=== 2. 改正履歴（law_revisions） ===")
    data = get_json(f"law_revisions/{LAW_ID_IKUKAI}")
    revisions = data.get("revisions", [])
    print(f"    revision 件数: {len(revisions)}")
    for rev in revisions[:6]:
        print(
            f"    {rev['law_revision_id']}  施行 {rev['amendment_enforcement_date']}"
            f"  {rev['current_revision_status']}"
        )
    check("改正履歴が取得できる", len(revisions) > 0, f"{len(revisions)} 件")
    enforcement_dates = {r["amendment_enforcement_date"] for r in revisions}
    check(
        "2025-04-01 施行のリビジョンが存在する",
        "2025-04-01" in enforcement_dates,
        "デモの「時間巻き戻し」対象",
    )
    check(
        "施行日が構造化フィールドで取れる（緊急度算出に使える）",
        all(r.get("amendment_enforcement_date") for r in revisions),
    )


def fetch_law(law_id: str, asof: str | None = None, elm: str | None = None) -> dict:
    params = {
        "response_format": "json",
        "law_full_text_format": "json",
        "json_format": "light",
    }
    if asof:
        params["asof"] = asof
    if elm:
        params["elm"] = elm
    return get_json(f"law_data/{law_id}", **params)


def verify_asof_before_after() -> None:
    print("\n=== 3. asof による改正前後の取得（最重要） ===")

    for law_id, name in ((LAW_ID_IKUKAI, "育介法"), (LAW_ID_IKUKAI_RULE, "育介法施行規則")):
        current = fetch_law(law_id)
        before = fetch_law(law_id, asof=ASOF_BEFORE)
        rev_current = current["revision_info"]["law_revision_id"]
        rev_before = before["revision_info"]["law_revision_id"]
        print(f"    {name} 現行          : {rev_current}")
        print(f"    {name} {ASOF_BEFORE}時点: {rev_before}")
        check(
            f"{name}: asof で異なるリビジョンが返る",
            rev_current != rev_before,
        )

        arts_current = article_map(current["law_full_text"])
        arts_before = article_map(before["law_full_text"])
        print(f"    {name} 条数: 現行 {len(arts_current)} / {ASOF_BEFORE}時点 {len(arts_before)}")
        check(f"{name}: 現行の条文を条単位で取り出せる", len(arts_current) > 0)
        check(f"{name}: 改正前の条文を条単位で取り出せる", len(arts_before) > 0)

        added = [t for t in arts_current if t not in arts_before]
        removed = [t for t in arts_before if t not in arts_current]
        changed = [
            t for t in arts_current if t in arts_before and arts_current[t] != arts_before[t]
        ]
        print(
            f"    {name} 差分: 追加 {len(added)} / 削除 {len(removed)} / 本文変更 {len(changed)}"
        )
        if added:
            print(f"      追加: {'、'.join(added[:5])}")
        if removed:
            print(f"      削除: {'、'.join(removed[:5])}")
        if changed:
            print(f"      変更: {'、'.join(changed[:5])}")
        check(
            f"{name}: 改正前後で実際に本文差分がある",
            bool(added or removed or changed),
            "差分が0なら時間巻き戻しデモが成立しない",
        )

    # 条単位の取得（elm）と、内容差分の具体例
    print(f"\n    --- 条単位の取得（elm={SAMPLE_ELM}）と内容差分 ---")
    cur = fetch_law(LAW_ID_IKUKAI, elm=SAMPLE_ELM)["law_full_text"]["Article"]
    old = fetch_law(LAW_ID_IKUKAI, asof=ASOF_BEFORE, elm=SAMPLE_ELM)["law_full_text"]["Article"]
    print(f"      現行          : {cur['ArticleTitle']} {cur['ArticleCaption']}")
    print(f"      {ASOF_BEFORE}時点: {old['ArticleTitle']} {old['ArticleCaption']}")
    check(
        "elm で条を名指し取得できる（枝番はアンダースコア連結）",
        cur.get("ArticleTitle") == "第十六条の二",
        cur.get("ArticleTitle", ""),
    )
    check(
        "同一条の見出しが改正前後で異なる（子の看護休暇 → 子の看護等休暇）",
        cur["ArticleCaption"] != old["ArticleCaption"],
    )


def verify_structure() -> None:
    print("\n=== 4. 条・項の構造化データ取得 ===")

    art = fetch_law(LAW_ID_IKUKAI, elm=SAMPLE_ELM)["law_full_text"]["Article"]
    nums = paragraph_nums(art)
    print(f"    JSON: ArticleTitle={art['ArticleTitle']} 項番号={nums}")
    check("JSON: 条見出し・条番号が要素として取れる", bool(art.get("ArticleTitle")))
    check("JSON: 項が構造として取れる（項番号あり）", nums == ["1", "2", "3", "4"], str(nums))
    first = art["Paragraph"][0]["ParagraphSentence"]["Sentence"]
    check("JSON: 項の本文が取れる", bool(first) and isinstance(first, list))
    print(f"    JSON: 第1項冒頭 = {''.join(first)[:60]}…")

    # XML でも同じ構造が取れること（DESIGN.md の「条構造付きXML」の裏取り）
    raw = get(
        f"law_data/{LAW_ID_IKUKAI}",
        response_format="xml",
        elm=SAMPLE_ELM,
    )
    root = ET.fromstring(raw)
    articles = root.iter("Article")
    article_el = next(articles, None)
    check("XML: Article 要素が取れる", article_el is not None)
    if article_el is not None:
        paras = article_el.findall("Paragraph")
        xml_nums = [p.get("Num") for p in paras]
        title_el = article_el.find("ArticleTitle")
        print(
            f"    XML : ArticleTitle={title_el.text if title_el is not None else None}"
            f" 項番号={xml_nums} Article@Num={article_el.get('Num')}"
        )
        check("XML: Paragraph 要素と Num 属性が取れる", xml_nums == ["1", "2", "3", "4"], str(xml_nums))


def main() -> int:
    print("e-Gov 法令API v2 実機確認")
    print(f"  API_BASE = {API_BASE}")
    print(f"  asof(改正前) = {ASOF_BEFORE}")

    verify_law_ids()
    verify_revisions()
    verify_asof_before_after()
    verify_structure()

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
