"""Stage 0 — 差分の分解とクエリ化（中位モデル × 1回/変更）。

DESIGN.md の決定:
  - 差分を意味のある変更単位に分解し、各単位をクエリ化する
  - `before_excerpt` / `after_excerpt` は**検証用の錨**。実際のdiffに含まれるか機械照合し、
    含まれなければリトライする（ハルシネーション検出）
  - `semantic_query` は「**改正前のルールに準拠して書かれた文書に現れそうな表現**」を書かせる
    （探す相手は旧ルール準拠の文書）。`exact_terms`（BM25用）とは必ず分ける
  - `change_type: delete` は探すべきものが違う（旧条番号を参照し続けている文書）
  - JSONのみ強制 → スキーマ検証 → 失敗時1回リトライ → **なお失敗しても黙って落とさず**、
    要人間確認フラグ付きの変更単位として通す
"""

from __future__ import annotations

import json
from typing import Any

from app.egov.snapshot import ProvisionDiff
from app.llm.client import INJECTION_GUARD, ChatResult, CostLog, LLMError, parse_json_object, wrap_untrusted
from app.pipeline.models import Change

# プロンプトを変えたら必ず上げる（判定キャッシュのキーに含まれる）
PROMPT_VERSION = "stage0-v1"

MAX_EXCERPT_CHARS = 1200

SYSTEM_PROMPT = f"""あなたは日本の法令改正を読み解き、企業の社内文書への影響を調べるための検索クエリを作る専門家です。

与えられた1件の条文の変更について、後段の検索で使う情報をJSONで出力してください。

{INJECTION_GUARD}

## 出力するJSON（このキーのみ。説明文やコードフェンスを付けない）

{{
  "change_type": "amend | add | delete | effective_date_only",
  "summary": "この変更を1〜2文で。何がどう変わったか",
  "affected_domains": ["影響が及びそうな業務領域。例: 育児休業, 労働時間"],
  "semantic_query": "改正前のルールに準拠して書かれた社内文書に現れそうな表現。文章で書く",
  "exact_terms": ["キーワード検索用の語。条番号・制度名・固有の用語。文章にしない"],
  "before_excerpt": "変更前の条文からの逐語引用（変更の核心部分。変更前が無い場合はnull）",
  "after_excerpt": "変更後の条文からの逐語引用（変更後が無い場合はnull）",
  "effective_date": "YYYY-MM-DD。与えられた施行日をそのまま使う。不明ならnull",
  "transitional": true/false,
  "confidence": 0.0〜1.0
}}

## 重要な注意

- **semantic_query は「探す相手」の言葉で書く**。探しているのは改正後の条文ではなく、
  改正前のルールのまま書かれている社内規定・契約書です。改正前の表現を使ってください。
- **exact_terms と semantic_query を混ぜない**。exact_terms は語の列、semantic_query は文章です。
- **before_excerpt / after_excerpt は必ず与えられた条文からの逐語引用**にしてください。
  要約したり言い換えたりしてはいけません。存在しない文を書いてはいけません。
- change_type が delete の場合、探すべきものは「削除された条番号を参照し続けている文書」です。
  exact_terms に旧条番号を必ず含めてください。
"""

USER_TEMPLATE = """## 法令
{law_title}

## 変更箇所
{label}

## 施行日
{enforcement_date}

## 変更前の条文
{before}

## 変更後の条文
{after}
"""

REQUIRED_KEYS = ("change_type", "summary", "semantic_query", "exact_terms")
VALID_TYPES = ("amend", "add", "delete", "effective_date_only")


class Stage0Error(LLMError):
    pass


def _truncate(text: str | None) -> str:
    if not text:
        return "（なし）"
    if len(text) <= MAX_EXCERPT_CHARS:
        return text
    return text[:MAX_EXCERPT_CHARS] + "…（以下略）"


def _default_change_type(diff: ProvisionDiff) -> str:
    return {"added": "add", "removed": "delete", "changed": "amend"}[diff.kind]


def build_user_prompt(diff: ProvisionDiff, law_title: str, enforcement_date: str | None) -> str:
    return USER_TEMPLATE.format(
        law_title=law_title,
        label=diff.label,
        enforcement_date=enforcement_date or "不明",
        before=wrap_untrusted(_truncate(diff.before)),
        after=wrap_untrusted(_truncate(diff.after)),
    )


def _validate(payload: dict[str, Any], diff: ProvisionDiff) -> list[str]:
    """スキーマと**逐語引用の実在**を検証する。返り値は問題点のリスト。"""
    problems: list[str] = []

    for key in REQUIRED_KEYS:
        if not payload.get(key):
            problems.append(f"{key} がありません")

    if payload.get("change_type") not in VALID_TYPES:
        problems.append(f"change_type が不正です: {payload.get('change_type')}")

    if not isinstance(payload.get("exact_terms"), list):
        problems.append("exact_terms が配列ではありません")

    # 錨の機械照合（ハルシネーション検出）
    for field, source in (("before_excerpt", diff.before), ("after_excerpt", diff.after)):
        excerpt = payload.get(field)
        if not excerpt:
            continue
        if not source or _normalize(excerpt) not in _normalize(source):
            problems.append(f"{field} が実際の条文に存在しません")

    return problems


def _normalize(text: str) -> str:
    return "".join(text.split())


def _fallback_change(diff: ProvisionDiff, change_id: str, enforcement_date: str | None, note: str) -> Change:
    """LLMが失敗しても黙って落とさない。検索できる形で通し、要人間確認を立てる。"""
    text = diff.after or diff.before or ""
    kind_label = {"added": "追加", "removed": "削除", "changed": "変更"}[diff.kind]
    return Change(
        change_id=change_id,
        change_type=_default_change_type(diff),  # type: ignore[arg-type]
        target_path=diff.label,
        before_excerpt=(diff.before or None),
        after_excerpt=(diff.after or None),
        summary=f"{diff.label} が{kind_label}されました（自動要約に失敗）",
        affected_domains=[],
        semantic_query=text[:200],
        exact_terms=[t for t in (diff.title, *diff.label.split(" > ")) if t],
        effective_date=enforcement_date,
        confidence=0.0,
        needs_human_review=True,
        note=note,
    )


def decompose_diff(
    chat,  # ChatModel
    diff: ProvisionDiff,
    change_id: str,
    law_title: str,
    enforcement_date: str | None,
    model: str,
    cost_log: CostLog | None = None,
) -> Change:
    """差分1件を変更単位1件に変換する。"""
    user = build_user_prompt(diff, law_title, enforcement_date)
    problems: list[str] = []
    payload: dict[str, Any] = {}

    for attempt in range(2):  # 失敗時1回リトライ
        prompt = user
        if problems:
            prompt = (
                f"{user}\n\n## 前回の出力の問題点（必ず直してください）\n"
                + "\n".join(f"- {p}" for p in problems)
            )
        try:
            result: ChatResult = chat.chat(model=model, system=SYSTEM_PROMPT, user=prompt)
        except LLMError as exc:
            return _fallback_change(diff, change_id, enforcement_date, f"LLM呼び出し失敗: {exc}")

        if cost_log is not None:
            cost_log.add(result.usage)

        try:
            payload = parse_json_object(result.text)
        except (LLMError, json.JSONDecodeError):
            problems = ["JSONとして解釈できませんでした。JSONのみを出力してください"]
            continue

        problems = _validate(payload, diff)
        if not problems:
            break

    if problems:
        return _fallback_change(
            diff, change_id, enforcement_date, "スキーマ検証に失敗: " + " / ".join(problems)
        )

    return Change(
        change_id=change_id,
        change_type=payload["change_type"],
        target_path=diff.label,
        before_excerpt=payload.get("before_excerpt"),
        after_excerpt=payload.get("after_excerpt"),
        summary=payload["summary"],
        affected_domains=list(payload.get("affected_domains") or []),
        semantic_query=payload["semantic_query"],
        exact_terms=[str(t) for t in payload["exact_terms"]],
        effective_date=payload.get("effective_date") or enforcement_date,
        effective_date_note=payload.get("effective_date_note"),
        transitional=bool(payload.get("transitional")),
        confidence=float(payload.get("confidence") or 0.0),
    )


def decompose(
    chat,
    diffs: list[ProvisionDiff],
    law_title: str,
    enforcement_date: str | None,
    model: str,
    cost_log: CostLog | None = None,
    limit: int | None = None,
) -> list[Change]:
    """イベントの差分を変更単位の列に分解する（差分1件＝変更単位1件）。"""
    targets = diffs[:limit] if limit else diffs
    return [
        decompose_diff(
            chat,
            diff,
            change_id=f"chg-{i:03d}",
            law_title=law_title,
            enforcement_date=enforcement_date,
            model=model,
            cost_log=cost_log,
        )
        for i, diff in enumerate(targets, start=1)
    ]
