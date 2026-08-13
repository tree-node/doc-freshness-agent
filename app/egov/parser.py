"""e-Gov 法令API の本文（json_format=light）を条・項の構造として読む。

**このモジュールは意図的に隔離されている**: e-Gov のJSON形式は公式に「試行版・仕様変更の
可能性あり」と注記されているため、壊れたらここだけをXMLパースに差し替えられるようにする
（PROGRESS.md 決定ログ 2026-08-13）。呼び出し側は Provision だけを知っていればよい。

取りこぼさないための設計（原則4「見逃し側に倒す」）:
  - 条（Article）だけを拾うと落ちるものがある。実データで確認済み:
      * 附則の一部は Article を持たず Paragraph が直下にある（育介法で4件）
      * 施行規則には制定文（EnactStatement）がある
      * Chapter の下に Section がネストする
    これらもすべて Provision として拾う。
  - **識別キーに章名などの可変な見出し語を含めない**。2025年改正で「第四章 子の看護休暇」が
    「第四章 子の看護等休暇」に変わったように、章名は改正で変わる。名前をキーに含めると
    その章の全条が「削除＋追加」に化けて差分が壊れる。キーには章番号だけを使い、
    見出し語の変化は heading の Provision として別途検出する。
  - **本則と附則で条番号が衝突する**（育介法では附則の「第一条」だけで37件）。キーは
    本則／附則（改正法令番号）を含めた構造パスで作る。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

# 見出しを持つ入れ子要素（要素名 → 見出しの要素名）
CONTAINERS = {
    "Part": "PartTitle",
    "Chapter": "ChapterTitle",
    "Section": "SectionTitle",
    "Subsection": "SubsectionTitle",
    "Division": "DivisionTitle",
}

# 条に属さない本文テキスト（前文・制定文）。捨てずに Provision にする
STANDALONE_TEXT = ("Preamble", "EnactStatement")

ProvisionKind = Literal["article", "heading", "text"]


@dataclass(frozen=True)
class Paragraph:
    num: str
    text: str


@dataclass(frozen=True)
class Provision:
    """差分とチャンク分割の最小単位。

    key   : 改正をまたいで安定する識別子（差分の突き合わせに使う）
    path  : 表示用の構造パス（DESIGN.md のチャンクメタデータ「構造パス」）
    """

    key: str
    path: tuple[str, ...]
    kind: ProvisionKind
    title: str | None
    caption: str | None
    text: str
    paragraphs: tuple[Paragraph, ...] = field(default=())

    @property
    def label(self) -> str:
        parts = [*self.path]
        if self.title:
            parts.append(self.title)
        return " > ".join(parts)


def _as_text(value: Any) -> str:
    """light 形式は文字列を裸でも配列でも返すため吸収する。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return "".join(_as_text(v) for v in value.values())
    return str(value)


def _collect_text(node: Any) -> str:
    """ノード配下の文字列をすべて連結する（号・細分まで取りこぼさない）。"""
    return _as_text(node)


def _chapter_number(title: str) -> str:
    """「第四章　子の看護等休暇」→「第四章」。章名は改正で変わるためキーに使わない。"""
    return title.split("　")[0].strip() or title.strip()


def _listed(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _paragraphs_of(node: dict) -> tuple[Paragraph, ...]:
    result = []
    for para in _listed(node.get("Paragraph")):
        if not isinstance(para, dict):
            continue
        num = str(para.get("Num") or len(result) + 1)
        result.append(Paragraph(num=num, text=_collect_text(para)))
    return tuple(result)


def _walk(node: Any, key_path: tuple[str, ...], display_path: tuple[str, ...]) -> Iterator[Provision]:
    if not isinstance(node, dict):
        return

    for name, title_key in CONTAINERS.items():
        for index, child in enumerate(_listed(node.get(name)), start=1):
            if not isinstance(child, dict):
                continue
            title = _as_text(child.get(title_key))
            # 章番号は安定、章名は改正で変わる → キーには番号、表示にはフルタイトル
            stable = _chapter_number(title) or f"{name}[{index}]"
            child_key = (*key_path, stable)
            child_display = (*display_path, title or stable)
            yield Provision(
                key="/".join((*child_key, "#heading")),
                path=child_display,
                kind="heading",
                title=None,
                caption=None,
                text=title,
            )
            yield from _walk(child, child_key, child_display)

    for index, article in enumerate(_listed(node.get("Article")), start=1):
        if not isinstance(article, dict):
            continue
        title = _as_text(article.get("ArticleTitle")) or f"Article[{index}]"
        caption = _as_text(article.get("ArticleCaption")) or None
        yield Provision(
            key="/".join((*key_path, title)),
            path=display_path,
            kind="article",
            title=title,
            caption=caption,
            text=_collect_text(article),
            paragraphs=_paragraphs_of(article),
        )

    # 条に属さず直下に置かれた項（附則に実在する）
    if "Article" not in node:
        for para in _paragraphs_of(node):
            yield Provision(
                key="/".join((*key_path, f"項{para.num}")),
                path=display_path,
                kind="text",
                title=f"第{para.num}項",
                caption=None,
                text=para.text,
                paragraphs=(para,),
            )

    for name in STANDALONE_TEXT:
        if name in node:
            text = _collect_text(node[name])
            if text:
                yield Provision(
                    key="/".join((*key_path, name)),
                    path=display_path,
                    kind="text",
                    title=name,
                    caption=None,
                    text=text,
                )


def parse_law_full_text(law_full_text: dict) -> list[Provision]:
    """`law_data` の `law_full_text`（json_format=light）を Provision の列にする。"""
    law = law_full_text.get("Law", law_full_text)
    body = law.get("LawBody", law)

    provisions: list[Provision] = []

    for name in STANDALONE_TEXT:
        if name in body:
            text = _collect_text(body[name])
            if text:
                provisions.append(
                    Provision(key=name, path=(), kind="text", title=name, caption=None, text=text)
                )

    main = body.get("MainProvision")
    if main is not None:
        provisions.extend(_walk(main, ("本則",), ("本則",)))

    for index, suppl in enumerate(_listed(body.get("SupplProvision")), start=1):
        if not isinstance(suppl, dict):
            continue
        label = _as_text(suppl.get("SupplProvisionLabel")) or "附則"
        # 改正法令番号は改正をまたいで安定した識別子。無い場合（制定時の附則）だけ位置で代用
        amend = _as_text(suppl.get("AmendLawNum"))
        stable = f"附則({amend})" if amend else f"附則[{index}]"
        display = f"{label}（{amend}）" if amend else label
        provisions.extend(_walk(suppl, (stable,), (display,)))

    return _disambiguate(provisions)


def _disambiguate(provisions: list[Provision]) -> list[Provision]:
    """万一キーが衝突しても後勝ちで消えないよう連番を振る（黙って落とさない）。"""
    seen: dict[str, int] = {}
    result = []
    for prov in provisions:
        count = seen.get(prov.key, 0) + 1
        seen[prov.key] = count
        if count > 1:
            prov = Provision(
                key=f"{prov.key}#{count}",
                path=prov.path,
                kind=prov.kind,
                title=prov.title,
                caption=prov.caption,
                text=prov.text,
                paragraphs=prov.paragraphs,
            )
        result.append(prov)
    return result
