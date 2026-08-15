"""「今すぐチェック」の実体。

CLIの `run` と同じことを、進捗を返しながら実行する。
処理そのものは `app.pipeline.run` に任せ、ここは組み立てと文言だけを持つ。

進捗の文言は画面にそのまま出るので**日常語で書く**（DESIGN.md 画面構成）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.egov import EGovClient, check_law
from app.history import record_check
from app.index import ChunkIndex
from app.llm.client import CostLog, OrcaRouterClient
from app.llm.pricing import PriceTable
from app.pipeline.run import ModelSet, load_cache, run_pipeline


class NotReadyError(RuntimeError):
    """チェックを始められる状態にない（インデックスが無い等）。"""


# 前回の条件が分からないときに、一度に処理する変更の上限。
# ボタン一つで数十件の変更が流れると、数十分かかり費用もかさむ。
# 切り捨てたことは進捗に必ず出す（黙って落とさない）。
MAX_CHANGES_WITHOUT_FILTER = 1


def resolve_models() -> ModelSet:
    return ModelSet(
        stage0=settings.require("model_stage0"),
        stage2=settings.require("model_stage2"),
        stage3=settings.require("model_stage3"),
        escalation=settings.model_escalation,
    )


def previous_filter(law_id: str) -> str | None:
    """前回どの条件で流したかを、保存済みの結果から拾う。

    ボタンを押したときに前回と同じものを見に行けるようにする
    （改正1件だけを見せているのに、押した途端に全件流れて何十分もかかる、を避ける）。

    `change_filter` が入っていない古い結果でも、変更が1件だけならその条から復元する。
    """
    path = settings.results_dir / f"{law_id}.json"
    if not path.exists():
        return None
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    saved = result.get("change_filter")
    if saved:
        return saved

    changes = result.get("changes") or []
    if len(changes) != 1:
        return None
    # 「本則 > 第四章　子の看護等休暇 > 第十六条の二」→「第十六条の二」
    target = changes[0].get("change", {}).get("target_path", "")
    tail = target.split(">")[-1].strip()
    return tail or None


def run_check(
    law_id: str,
    report: Callable[[str], None],
    change_filter: str | None = None,
    max_changes: int | None = None,
    index_dir: Path | None = None,
    all_changes: bool = False,
) -> dict[str, Any]:
    """1つの正本をチェックする。変更があれば判定まで走らせて結果を保存する。

    `all_changes=True` で見つかった変更をすべて見る。時間と費用がかかるので、
    呼び出し側が明示したときだけ。既定は歯止めが働く。
    """
    index_dir = index_dir or settings.snapshots_dir.parent / "index"
    if not (index_dir / "chunks.json").exists():
        raise NotReadyError(
            "監視対象がまだ取り込まれていません。"
            "ターミナルで `python -m app.cli ingest` を実行してください"
            "（demo-data/監視対象 を読み込みます）"
        )

    index = ChunkIndex.load(index_dir)
    locations_path = index_dir / "locations.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8")) if locations_path.exists() else {}
    models = resolve_models()

    report("法令の最新の条文を確認しています…")
    with EGovClient() as egov:
        event = check_law(egov, law_id, settings.snapshots_dir)

    law_title = event.law_title if event else _snapshot_title(law_id)
    record_check(
        settings.history_path,
        law_id=law_id,
        law_title=law_title,
        detected=event is not None,
        revision=event.to_revision if event else None,
        enforcement_date=event.enforcement_date if event else None,
    )

    if event is None:
        report("変更はありませんでした")
        return {"law_id": law_id, "law_title": law_title, "detected": False}

    total = len(event.diffs)
    if change_filter:
        matched = [d for d in event.diffs if change_filter in d.label]
        if matched:
            event = replace(event, diffs=matched)
            report(f"{total}件の変更のうち、前回と同じ{len(matched)}件を確認します")
        else:
            report(f"前回見た変更が見つからなかったため、{total}件すべてを対象にします")

    if all_changes:
        # 2026-08-15 の全件実測から。労基法41件＋育介法27件＝68変更を 2時間39分・$5.31 で完走し、
        # 1変更あたり 140秒・$0.078 だった。以前は 80秒・$0.05 と見積もっていたが、
        # 実測の1.75倍楽観的で「1時間で終わると言われて3時間待つ」ことになるため実測値に置き換えた。
        # 少なく言うほうが事故なので、丸めるときは切り上げる。
        report(
            f"{total}件の変更すべてを確認します。"
            f"目安は {round(total * 140 / 60)} 分ほど、費用は ${total * 0.078:.1f} 前後です"
        )
    # 条件が分からないときは全件流さない。時間と費用の歯止め
    elif not change_filter and len(event.diffs) > MAX_CHANGES_WITHOUT_FILTER:
        max_changes = MAX_CHANGES_WITHOUT_FILTER
        picked = "、".join(d.label.split(">")[-1].strip() for d in event.diffs[:max_changes])
        # **どれを見ているかを必ず言う**。41件を1件に絞ったのに、その1件が何かを
        # 伝えないと「動かなかった」と「関係ない条を見ていた」の区別が付かない。
        # 並び順で選んでいるだけで、関係のありそうな変更を選んでいるわけではない
        report(
            f"{total}件の変更が見つかりました。全部を見ると1〜2時間かかるため、"
            f"今回は先頭の{max_changes}件（{picked}）だけ確認します"
        )
        report(
            "見たい変更が決まっている場合は、コマンドで指定してください: "
            f"python -m app.cli run {law_id} --change-filter 第◯◯条"
        )

    report(f"{len(event.diffs)}件の変更について、影響のある文書を探します…")

    cost_log = CostLog(prices=PriceTable.fetch(settings.db_path.parent / "cache/pricing.json"))
    with OrcaRouterClient() as chat:
        embedder = _embedder(chat)
        result = run_pipeline(
            event,
            index,
            chat,
            models,
            embedder=embedder,
            locations=locations,
            cache=load_cache(settings.db_path.parent / "cache/judgements.json"),
            max_changes=max_changes,
            cost_log=cost_log,
            progress=_friendly(report),
            change_filter=change_filter,
            changes_found=total,
        )

    out = settings.results_dir / f"{law_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    affected = sum(r.funnel.affected for r in result.results)
    judged = sum(r.funnel.stage3_judged for r in result.results)
    report(f"確認おわり: {judged}件を確認して、{affected}件が要対応でした")
    return {
        "law_id": law_id,
        "law_title": result.law_title,
        "detected": True,
        "judged": judged,
        "affected": affected,
        "cost_usd": result.cost.get("cost_usd"),
    }


def _friendly(report: Callable[[str], None]) -> Callable[[str], None]:
    """パイプラインが出す開発者向けの進捗を、画面に出せる日常語に置き換える。"""

    def translate(message: str) -> None:
        text = message.strip()
        if text.startswith("Stage 0"):
            report("変更の内容を読み取っています…")
        elif text.startswith("Stage 1"):
            report("関係のありそうな箇所を絞り込んでいます…")
        elif text.startswith("Stage 2"):
            report("影響しそうな箇所を選んでいます…")
        elif text.startswith("Stage 3"):
            report("一つずつ中身を確認しています…")
        elif text.startswith("注意:"):
            report(text)
        # 変更IDなどの内部情報は画面に出さない

    return translate


def _embedder(chat: OrcaRouterClient):
    model = settings.embeddings_model
    if not model:
        return None

    class _Embedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return chat.embed(texts, model=model)

    return _Embedder()


def _snapshot_title(law_id: str) -> str:
    path = settings.snapshots_dir / f"{law_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("law_title", law_id)
    return law_id
