"""Stage 2 — 再ランク（安価モデル。50 → 10件）。

DESIGN.md の決定:
  - 「似ているか」ではなく「**影響しうるか**」で 0〜1 採点し直す。トリアージなので速度と安さ優先
  - **閾値はここに集約**: スコア 0.5 以上を通過、上限15件（正解セットで調整）
  - **1チャンク=1コール**（並列実行）。バッチ化しない（キャッシュ粒度が壊れる／位置バイアス）
  - 入力は変更の summary + affected_domains + チャンク本文 + 構造パスのみ（条文全文は渡さない）
  - 出力は `{"score": 0.x}` のみ（理由は書かせない＝出力トークン節約）
  - プロンプトで**迷いを通過側に倒す**

並列数は 10 に制限する。OrcaRouter 無料枠はレート上限が低く、50件一斉並列は429を踏む
（PROGRESS.md 決定ログ 2026-08-13）。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from app.chunking import Chunk
from app.index import ChunkIndex
from app.llm.client import INJECTION_GUARD, CostLog, LLMError, parse_json_object, wrap_untrusted
from app.pipeline.models import Candidate, Change

PROMPT_VERSION = "stage2-v1"

PASS_THRESHOLD = 0.5
MAX_PASS = 15
MAX_PARALLEL = 10

# 採点に失敗したチャンクは落とさず通す（見逃し側に倒す）
FAILURE_SCORE = PASS_THRESHOLD

_COST_LOCK = threading.Lock()

SYSTEM_PROMPT = f"""あなたは法令改正の影響調査のトリアージ担当です。

与えられた「法令の変更」と「社内文書の一部」を読み、その文書箇所が変更の影響を受ける**可能性があるか**を0〜1で採点してください。

{INJECTION_GUARD}

## 採点の基準

- 1.0 に近い: この箇所は明らかにその変更に関係する記述を含む
- 0.5 前後: 関係するかもしれない。判断がつかない
- 0.0 に近い: 明らかに無関係

**判断に迷う場合は必ず0.5以上を付けてください。** 0.5未満を付けてよいのは、無関係だと確信できる場合だけです。
ここは絞り込みの途中であり、あなたが落としたものは二度と検査されません。見落としの方が誤検出よりはるかに重大です。

## 出力

次のJSONだけを出力してください。理由や説明は書かないでください。

{{"score": 0.0〜1.0の数値}}
"""

USER_TEMPLATE = """## 法令の変更
{summary}

影響しうる領域: {domains}

## 社内文書の一部
文書内の位置: {label}

{chunk}
"""


def build_user_prompt(change: Change, chunk: Chunk) -> str:
    return USER_TEMPLATE.format(
        summary=change.summary,
        domains="、".join(change.affected_domains) or "（不明）",
        label=chunk.label,
        chunk=wrap_untrusted(chunk.text),
    )


def score_chunk(
    chat, change: Change, chunk: Chunk, model: str, cost_log: CostLog | None = None
) -> tuple[float, str | None]:
    """1チャンクを採点する。失敗しても落とさず通過側の点を返す。"""
    try:
        result = chat.chat(
            model=model,
            system=SYSTEM_PROMPT,
            user=build_user_prompt(change, chunk),
            max_tokens=32,
        )
    except LLMError as exc:
        return FAILURE_SCORE, f"採点に失敗したため通過させました: {exc}"

    if cost_log is not None:
        # Stage 2 は件数が多く、コスト実測の主役。並列実行から呼ばれるのでロックを取る
        with _COST_LOCK:
            cost_log.add(result.usage)

    try:
        payload = parse_json_object(result.text)
        score = float(payload["score"])
    except Exception:
        return FAILURE_SCORE, f"採点結果を解釈できませんでした: {result.text[:80]}"

    return max(0.0, min(1.0, score)), None


def rerank(
    chat,
    change: Change,
    candidates: list[Candidate],
    index: ChunkIndex,
    model: str,
    cost_log: CostLog | None = None,
    threshold: float = PASS_THRESHOLD,
    max_pass: int = MAX_PASS,
    max_parallel: int = MAX_PARALLEL,
) -> tuple[list[Candidate], dict[str, float], list[str]]:
    """候補を採点し、通過分・全スコア・注意メッセージを返す。"""
    if not candidates:
        return [], {}, []

    def run(candidate: Candidate) -> tuple[Candidate, float, str | None]:
        chunk = index.get(candidate.chunk_id)
        score, note = score_chunk(chat, change, chunk, model, cost_log)
        return candidate, score, note

    notes: list[str] = []
    scored: list[tuple[Candidate, float]] = []

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        for candidate, score, note in pool.map(run, candidates):
            scored.append((candidate, score))
            if note:
                notes.append(f"{candidate.label}: {note}")

    scores = {candidate.chunk_id: round(score, 3) for candidate, score in scored}

    passed = [c for c, score in sorted(scored, key=lambda x: -x[1]) if score >= threshold]

    # 紐付け済み文書は無条件で Stage 3 に通す（見逃し担保①。スコアに関係なく）
    linked = [c for c, _ in scored if c.reason == "紐付け済み文書" and c not in passed]

    if len(passed) > max_pass:
        notes.append(
            f"閾値{threshold}以上が{len(passed)}件あり、上位{max_pass}件に絞りました"
            f"（{len(passed) - max_pass}件は精査していません）"
        )
        passed = passed[:max_pass]

    return [*passed, *linked], scores, notes
