"""Stage 3 — 精査（高性能モデル。10 → 影響あり3件）。

DESIGN.md の決定:
  - **入力の並び順を固定**する（キャッシュ効率）。共通プレフィックス（システムプロンプト＋
    変更情報）は候補10件で同一なので、2件目以降はプロンプトキャッシュに乗る。
    可変部（文書メタデータ・チャンク本文）は必ず後ろに置く。**この順序を変えないこと**
  - 出力は**フィールド順で思考順を強制**する（impact より先に law_applicability を生成させる）
  - `law_applicability: unclear` は適用ありとして続行（見逃し側に倒す）＋要確認フラグ
  - `evidence_quote` は逐語引用させ、**チャンク本文の部分文字列として実在するか機械照合**。
    不在なら1回リトライ。マーキング表示のオフセット特定はこの照合に全面依存する
  - `fix_proposal` は該当文の before/after のみ（全文書き換えさせない）
  - few-shot は1例のみ（業務委託契約書に労働時間の記載があるが適用外＝最高難度）
  - confidence < 0.6 は強いモデルで再精査1回 → 高い方を採用。なお低ければ要人間確認
"""

from __future__ import annotations

from app.chunking import Chunk
from app.index import ChunkIndex
from app.llm.client import INJECTION_GUARD, CostLog, LLMError, parse_json_object, wrap_untrusted
from app.pipeline.models import Candidate, Change, Finding

PROMPT_VERSION = "stage3-v2"  # プロンプトを変えたら必ず上げる（判定キャッシュのキー）

ESCALATION_THRESHOLD = 0.6
CONTEXT_CHARS = 300  # 前後文脈の長さ

SYSTEM_PROMPT = f"""あなたは日本の労働法・企業法務に詳しい専門家です。
法令が改正されたとき、企業の社内文書のどの記述が影響を受けるかを判定します。

{INJECTION_GUARD}

## 手順

1. まず、その文書が**どういう性質の文書か**を判断する（就業規則か、締結済みの契約書か、ひな形か等）
2. 次に、**その文書にその法令が適用されるか**を判断する（例: 業務委託契約の受託者は労働者ではないため労働基準法は適用されない）
3. 適用される場合に限り、**改正によって記述が古くなった／違反状態になったか**を判断する

順番を守ってください。適用可能性を確かめる前に影響を判断してはいけません。

## 出力するJSON（このキーと順序で。説明文やコードフェンスを付けない）

{{
  "document_nature": "文書の性質",
  "law_applicability": "applicable | not_applicable | unclear",
  "applicability_reason": "そう判断した理由",
  "impact": "affected | none | not_applicable",
  "deadline_type": "immediate | on_renewal | none",
  "evidence_quote": "文書本文からの逐語引用（影響を受ける箇所そのもの）",
  "evidence_location": "文書内の位置（第◯条など）",
  "fix_proposal": {{"before": "直すべき一文", "after": "改正後の内容に合わせた一文"}},
  "confidence": 0.0〜1.0
}}

## 判断の基準

- **deadline_type**:
  - `immediate`（即時対応）: 就業規則・社内規定（法令違反の規則は効力がなく、届出義務もある）と、
    今後の締結に使うひな形・テンプレート
  - `on_renewal`（更新時対応）: **すでに締結済みの個別の契約書**。強行法規の直律的効力により
    法定基準が自動で適用されるため、書き換えないと違反、という状態にはならない。次の更新時に直せばよい
  - `none`: 影響がない場合
- 判断がつかない場合は `law_applicability` に `unclear` を入れてください。無理に断定しないでください。
- **evidence_quote は文書本文からの逐語引用**にしてください。1文字も変えてはいけません。
  要約・言い換え・存在しない文の記載は誤りです。影響がない場合は空文字にしてください。
- **fix_proposal は影響を受ける一文だけ**を直してください。文書全体を書き換えてはいけません。
  影響がない場合は null にしてください。

## 例（最も判断が難しいケース）

文書: 業務委託契約書。「受託者の作業時間は1日8時間を超えないものとする」という記述がある。
法令の変更: 労働時間の上限規制に関する改正。

正しい判定:
{{
  "document_nature": "業務委託契約書",
  "law_applicability": "not_applicable",
  "applicability_reason": "受託者は労働者ではなく、労働基準法の労働時間規制は適用されない。作業時間の記述は当事者間の合意であり法定労働時間の定めではない",
  "impact": "not_applicable",
  "deadline_type": "none",
  "evidence_quote": "",
  "evidence_location": "",
  "fix_proposal": null,
  "confidence": 0.9
}}

労働時間という語が出てくるだけでは影響ありとは限りません。文書の性質を先に見てください。
"""

# --- 共通プレフィックス（候補ごとに変えない） ---
CHANGE_TEMPLATE = """## 法令の変更

法令: {law_title}
変更箇所: {target_path}
施行日: {effective_date}

変更の要点: {summary}

### 変更前の条文
{before}

### 変更後の条文
{after}
"""

# --- 可変サフィックス（候補ごとに変わる。必ず後ろに置く） ---
# **ファイル名は渡さない**（ファイル名・フォルダ構造は判定に使わない＝中身で判定する）。
# 代わりに文書の冒頭を渡す。ひな形なのか締結済みの契約なのかは、そこを読めば分かる。
CHUNK_TEMPLATE = """## 判定対象の社内文書

### 文書の冒頭（どういう文書かの判断に使う）
{opening}

文書内の位置: {label}

### 該当箇所
{chunk}

### 前後の文脈（参考。判定対象はあくまで上の該当箇所）
{context}
"""

OPENING_CHARS = 400

REQUIRED_KEYS = ("law_applicability", "impact", "confidence")
VALID_APPLICABILITY = ("applicable", "not_applicable", "unclear")
VALID_IMPACT = ("affected", "none", "not_applicable")
VALID_DEADLINE = ("immediate", "on_renewal", "none")


def build_change_prefix(change: Change, law_title: str) -> str:
    return CHANGE_TEMPLATE.format(
        law_title=law_title,
        target_path=change.target_path,
        effective_date=change.effective_date or "不明",
        summary=change.summary,
        before=wrap_untrusted(change.before_excerpt or "（なし）"),
        after=wrap_untrusted(change.after_excerpt or "（なし）"),
    )


def neighbor_context(index: ChunkIndex, chunk: Chunk) -> str:
    """同一文書内の前後チャンクを短く付ける。"""
    same_doc = [c for c in index.chunks if c.doc_id == chunk.doc_id]
    position = next((i for i, c in enumerate(same_doc) if c.chunk_id == chunk.chunk_id), None)
    if position is None:
        return "（なし）"
    parts = []
    if position > 0:
        parts.append("【前】" + same_doc[position - 1].text[-CONTEXT_CHARS:])
    if position + 1 < len(same_doc):
        parts.append("【後】" + same_doc[position + 1].text[:CONTEXT_CHARS])
    return wrap_untrusted("\n".join(parts)) if parts else "（なし）"


def document_opening(index: ChunkIndex, doc_id: str) -> str:
    """文書の冒頭。表題や「締結日」「ひな形」といった手がかりがここに出る。"""
    for chunk in index.chunks:
        if chunk.doc_id == doc_id:
            return chunk.text[:OPENING_CHARS]
    return "（不明）"


def build_user_prompt(change: Change, chunk: Chunk, index: ChunkIndex, law_title: str) -> str:
    # 並び順は固定: 共通プレフィックス → 可変サフィックス
    return build_change_prefix(change, law_title) + "\n" + CHUNK_TEMPLATE.format(
        opening=wrap_untrusted(document_opening(index, chunk.doc_id)),
        label=chunk.label,
        chunk=wrap_untrusted(chunk.text),
        context=neighbor_context(index, chunk),
    )


def _normalize(text: str) -> str:
    return "".join(text.split())


def _validate(payload: dict) -> list[str]:
    problems = []
    for key in REQUIRED_KEYS:
        if payload.get(key) is None:
            problems.append(f"{key} がありません")
    if payload.get("law_applicability") not in VALID_APPLICABILITY:
        problems.append(f"law_applicability が不正です: {payload.get('law_applicability')}")
    if payload.get("impact") not in VALID_IMPACT:
        problems.append(f"impact が不正です: {payload.get('impact')}")
    if payload.get("deadline_type") and payload["deadline_type"] not in VALID_DEADLINE:
        problems.append(f"deadline_type が不正です: {payload.get('deadline_type')}")
    return problems


def _to_finding(payload: dict, chunk: Chunk, model: str, evidence_verified: bool) -> Finding:
    applicability = payload["law_applicability"]
    impact = payload["impact"]
    confidence = float(payload.get("confidence") or 0.0)

    needs_review = False
    reasons = []

    # unclear は適用ありとして影響判定を続行し、結果に関わらず要確認（見逃し側に倒す）
    if applicability == "unclear":
        needs_review = True
        reasons.append("法令の適用可否が判断できていません")
    if not evidence_verified and impact == "affected":
        needs_review = True
        reasons.append("引用が本文と一致せず、該当箇所を特定できていません")

    return Finding(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        label=chunk.label,
        document_nature=payload.get("document_nature") or "不明",
        law_applicability=applicability,
        applicability_reason=payload.get("applicability_reason") or "",
        impact=impact,
        deadline_type=payload.get("deadline_type") or "none",
        evidence_quote=payload.get("evidence_quote") or "",
        evidence_location=payload.get("evidence_location") or "",
        fix_proposal=payload.get("fix_proposal") if isinstance(payload.get("fix_proposal"), dict) else None,
        confidence=confidence,
        needs_human_review=needs_review,
        review_reason=" / ".join(reasons) or None,
        evidence_verified=evidence_verified,
        model=model,
    )


def _failed_finding(chunk: Chunk, reason: str, model: str) -> Finding:
    """判定に失敗しても黙って落とさず、要人間確認として起票する。"""
    return Finding(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        label=chunk.label,
        document_nature="不明",
        law_applicability="unclear",
        applicability_reason=reason,
        impact="affected",  # 判定できないものを「影響なし」にしない
        deadline_type="none",
        evidence_quote="",
        evidence_location="",
        fix_proposal=None,
        confidence=0.0,
        needs_human_review=True,
        review_reason=reason,
        evidence_verified=False,
        model=model,
    )


def judge_chunk(
    chat,
    change: Change,
    chunk: Chunk,
    index: ChunkIndex,
    law_title: str,
    model: str,
    escalation_model: str | None = None,
    cost_log: CostLog | None = None,
) -> Finding:
    user = build_user_prompt(change, chunk, index, law_title)
    problems: list[str] = []
    finding: Finding | None = None

    for _ in range(2):  # スキーマ違反・引用不一致は1回リトライ
        prompt = user
        if problems:
            prompt = user + "\n\n## 前回の出力の問題点（必ず直してください）\n" + "\n".join(
                f"- {p}" for p in problems
            )
        try:
            result = chat.chat(model=model, system=SYSTEM_PROMPT, user=prompt, max_tokens=1500)
        except LLMError as exc:
            return _failed_finding(chunk, f"精査の呼び出しに失敗しました: {exc}", model)

        if cost_log is not None:
            cost_log.add(result.usage)

        try:
            payload = parse_json_object(result.text)
        except Exception:
            problems = ["JSONとして解釈できませんでした。JSONのみを出力してください"]
            continue

        problems = _validate(payload)
        if problems:
            continue

        quote = payload.get("evidence_quote") or ""
        verified = not quote or _normalize(quote) in _normalize(chunk.text)
        if not verified and not problems:
            # 引用が本文に無い → 1回だけ直させる
            problems = ["evidence_quote が文書本文に存在しません。本文からそのまま引用してください"]
            finding = _to_finding(payload, chunk, result.usage.model, evidence_verified=False)
            continue

        finding = _to_finding(payload, chunk, result.usage.model, evidence_verified=verified)
        problems = []
        break

    if finding is None:
        return _failed_finding(chunk, "スキーマ検証に失敗: " + " / ".join(problems), model)

    # confidence < 0.6 は強いモデルで再精査1回 → 高い方を採用
    if finding.confidence < ESCALATION_THRESHOLD and escalation_model:
        try:
            escalated = judge_chunk(
                chat, change, chunk, index, law_title, escalation_model, None, cost_log
            )
            if escalated.confidence > finding.confidence:
                finding = escalated
        except LLMError:
            pass

    if finding.confidence < ESCALATION_THRESHOLD:
        finding.needs_human_review = True
        finding.review_reason = " / ".join(
            filter(None, [finding.review_reason, f"確信度が低い（{finding.confidence}）"])
        )
    return finding


def examine(
    chat,
    change: Change,
    candidates: list[Candidate],
    index: ChunkIndex,
    law_title: str,
    model: str,
    escalation_model: str | None = None,
    cost_log: CostLog | None = None,
) -> list[Finding]:
    return [
        judge_chunk(
            chat,
            change,
            index.get(candidate.chunk_id),
            index,
            law_title,
            model,
            escalation_model,
            cost_log,
        )
        for candidate in candidates
    ]
