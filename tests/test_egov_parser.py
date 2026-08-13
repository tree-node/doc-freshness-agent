"""パーサーの単体テスト。

実データ（育介法・施行規則）で確認した「素朴に書くと落ちる形」をすべて含む縮小版を使う:
  - 附則の条番号が本則と衝突する（実データでは附則の「第一条」だけで37件）
  - 附則の一部は Article を持たず Paragraph が直下にある（実データで4件）
  - Chapter の下に Section がネストする
  - 施行規則には制定文（EnactStatement）がある
  - 章名は改正で変わる（第四章 子の看護休暇 → 子の看護等休暇）

ネットワークには出ない。実データに対する確認は scripts/verify_egov.py 側で行う。
"""

from __future__ import annotations

from app.egov.parser import parse_law_full_text

LAW = {
    "Law": {
        "LawNum": "平成三年法律第七十六号",
        "LawBody": {
            "LawTitle": "テスト法",
            "EnactStatement": ["テスト法を次のように定める。"],
            "MainProvision": {
                "Chapter": [
                    {
                        "ChapterTitle": ["第一章　総則"],
                        "Article": [
                            {
                                "ArticleCaption": "（目的）",
                                "ArticleTitle": "第一条",
                                "Paragraph": [
                                    {
                                        "Num": "1",
                                        "ParagraphSentence": {"Sentence": ["この法律は、…。"]},
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "ChapterTitle": ["第四章　子の看護休暇"],
                        "Section": [
                            {
                                "SectionTitle": ["第一節　申出"],
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
                                            },
                                            {
                                                "Num": "2",
                                                "ParagraphSentence": {"Sentence": ["前項の…。"]},
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ]
            },
            "SupplProvision": [
                {
                    "SupplProvisionLabel": "附　則",
                    "AmendLawNum": "平成一一年七月七日法律第八三号",
                    "Article": [
                        {
                            "ArticleTitle": "第一条",
                            "Paragraph": [
                                {"Num": "1", "ParagraphSentence": {"Sentence": ["施行期日…。"]}}
                            ],
                        }
                    ],
                },
                {
                    "SupplProvisionLabel": "附　則",
                    "AmendLawNum": "平成一八年六月二日法律第五〇号",
                    # Article を持たず Paragraph が直下（実データに存在する形）
                    "Paragraph": [
                        {
                            "Num": "1",
                            "ParagraphSentence": {
                                "Sentence": ["この法律は、一般社団・財団法人法の施行の日から施行する。"]
                            },
                        }
                    ],
                },
            ],
        },
    }
}


def keys(law: dict) -> set[str]:
    return {p.key for p in parse_law_full_text(law)}


def test_main_and_suppl_articles_do_not_collide() -> None:
    """本則の第一条と附則の第一条が同じキーに潰れない。"""
    provisions = parse_law_full_text(LAW)
    article_keys = [p.key for p in provisions if p.kind == "article"]
    assert len(article_keys) == len(set(article_keys))
    assert "本則/第一章/第一条" in article_keys
    assert "附則(平成一一年七月七日法律第八三号)/第一条" in article_keys


def test_bare_paragraph_under_suppl_is_kept() -> None:
    """Article を持たない附則の項を落とさない（見逃し側に倒す）。"""
    texts = [p.text for p in parse_law_full_text(LAW) if p.kind == "text"]
    assert any("一般社団・財団法人法" in t for t in texts)


def test_enact_statement_is_kept() -> None:
    assert any("テスト法を次のように定める。" in p.text for p in parse_law_full_text(LAW))


def test_nested_section_article_is_found() -> None:
    provisions = {p.key: p for p in parse_law_full_text(LAW)}
    art = provisions["本則/第四章/第一節/第十六条の二"]
    assert art.caption == "（子の看護休暇の申出）"
    assert [p.num for p in art.paragraphs] == ["1", "2"]
    assert art.label == "本則 > 第四章　子の看護休暇 > 第一節　申出 > 第十六条の二"


def test_article_key_is_stable_when_chapter_is_renamed() -> None:
    """章名の改正で条のキーが変わらない（変わると全条が削除＋追加に化ける）。"""
    import copy

    renamed = copy.deepcopy(LAW)
    chapter = renamed["Law"]["LawBody"]["MainProvision"]["Chapter"][1]
    chapter["ChapterTitle"] = ["第四章　子の看護等休暇"]

    before = {k for k in keys(LAW) if k.endswith("第十六条の二")}
    after = {k for k in keys(renamed) if k.endswith("第十六条の二")}
    assert before == after == {"本則/第四章/第一節/第十六条の二"}


def test_chapter_rename_is_still_detected_as_heading() -> None:
    """キーからは外すが、章名の変化自体は heading として検出できる。"""
    headings = {p.key: p.text for p in parse_law_full_text(LAW) if p.kind == "heading"}
    assert headings["本則/第四章/#heading"] == "第四章　子の看護休暇"


def test_duplicate_keys_are_disambiguated_not_dropped() -> None:
    """万一キーが衝突しても黙って消えない。"""
    law = {
        "Law": {
            "LawBody": {
                "MainProvision": {
                    "Chapter": [
                        {
                            "ChapterTitle": ["第一章　総則"],
                            "Article": [
                                {"ArticleTitle": "第一条", "Paragraph": [{"Num": "1"}]},
                                {"ArticleTitle": "第一条", "Paragraph": [{"Num": "1"}]},
                            ],
                        }
                    ]
                }
            }
        }
    }
    article_keys = [p.key for p in parse_law_full_text(law) if p.kind == "article"]
    assert article_keys == ["本則/第一章/第一条", "本則/第一章/第一条#2"]
