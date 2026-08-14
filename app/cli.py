"""パイプラインを貫通させるためのCLI（DESIGN.md 実装順序: CLI → 評価 → UI）。

    python -m app.cli revisions 403AC0000000076
    python -m app.cli snapshot  403AC0000000076 --asof 2025-03-01   # 時間巻き戻し初期化
    python -m app.cli check     403AC0000000076 [--json out.json]   # 巡回1回分
    python -m app.cli ingest    [--dir 監視対象] [--out インデックス]  # 取り込み→チャンク→索引
    python -m app.cli run       403AC0000000076 [--out result.json]  # Stage 0〜3 貫通
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from app.chunking import split_document
from app.config import settings
from app.egov import EGovClient, EGovError, check_law, fetch_snapshot, snapshot_path
from app.history import record_check
from app.index import ChunkIndex, build_index
from app.llm.client import CostLog, LLMError, OrcaRouterClient
from app.llm.pricing import PriceTable
from app.pipeline.run import ModelSet, load_cache, run_pipeline
from app.sources import LocalFolderSource

MAX_PREVIEW = 60


def _preview(text: str | None) -> str:
    if not text:
        return "（なし）"
    flat = " ".join(text.split())
    return flat[:MAX_PREVIEW] + ("…" if len(flat) > MAX_PREVIEW else "")


def cmd_revisions(args: argparse.Namespace) -> int:
    with EGovClient() as client:
        revisions = client.get_revisions(args.law_id)
    print(f"{args.law_id}: 改正履歴 {len(revisions)} 件（新しい順）")
    for rev in revisions[: args.limit]:
        mark = " ※未施行" if rev.is_unenforced else ""
        print(f"  施行 {rev.enforcement_date}  {rev.law_revision_id}  {rev.status}{mark}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    root = Path(args.dir) if args.dir else settings.snapshots_dir
    with EGovClient() as client:
        snapshot = fetch_snapshot(client, args.law_id, asof=args.asof)
    path = snapshot.save(snapshot_path(root, args.law_id))
    when = f"{args.asof} 時点" if args.asof else "現行"
    print(f"保存しました: {path}")
    print(f"  {snapshot.law_title}")
    print(f"  {when} / リビジョン {snapshot.law_revision_id} / 施行 {snapshot.enforcement_date}")
    print(f"  条文ユニット数: {len(snapshot.provisions)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.dir) if args.dir else settings.snapshots_dir
    with EGovClient() as client:
        event = check_law(client, args.law_id, root)

    if event is None:
        # 「変更なし」も結果として見せる（DESIGN.md 原則3・ホームのチェック履歴）
        print(f"{args.law_id}: 変更なし")
        return 0

    counts = {kind: sum(1 for d in event.diffs if d.kind == kind) for kind in ("changed", "added", "removed")}
    print(f"{event.law_title}")
    print(f"  {event.from_revision}")
    print(f"  → {event.to_revision}（施行 {event.enforcement_date}）")
    print(f"  差分: 変更 {counts['changed']} / 追加 {counts['added']} / 削除 {counts['removed']}")
    label = {"changed": "変更", "added": "追加", "removed": "削除"}
    for diff in event.diffs[: args.limit]:
        print(f"\n  [{label[diff.kind]}] {diff.label}")
        print(f"    before: {_preview(diff.before)}")
        print(f"    after : {_preview(diff.after)}")
    if len(event.diffs) > args.limit:
        print(f"\n  …ほか {len(event.diffs) - args.limit} 件（全件は --json で出力）")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(event.to_json() + "\n", encoding="utf-8")
        print(f"\nStage 0 の入力を書き出しました: {out}")
    return 0


class OrcaRouterEmbedder:
    """Embedder プロトコルの実装（埋め込みモデルは .env の EMBEDDINGS_MODEL）。"""

    def __init__(self, client: OrcaRouterClient, model: str) -> None:
        self._client = client
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed(texts, model=self._model)


def _index_dir(arg: str | None) -> Path:
    return Path(arg) if arg else settings.snapshots_dir.parent / "index"


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.dir) if args.dir else settings.watch_root
    source = LocalFolderSource(root)
    refs = source.list()
    print(f"取り込み: {root}")
    print(f"  対象ファイル {len(refs)} 件（md/txt/docx のみ）")

    chunks = []
    for ref in refs:
        document = source.read(ref)
        doc_chunks = split_document(ref.doc_id, document.text)
        chunks.extend(doc_chunks)
        print(f"    {ref.doc_id}: {len(doc_chunks)} チャンク")

    embedder = None
    if not args.no_embed:
        client = OrcaRouterClient()
        embedder = OrcaRouterEmbedder(client, settings.require("embeddings_model"))

    index = build_index(chunks, embedder=embedder)
    out = _index_dir(args.out)
    index.save(out)
    # 起票時に「置換先パス」を出すため、doc_id → 実際の位置 を残す
    (out / "locations.json").write_text(
        json.dumps({ref.doc_id: ref.location for ref in refs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  チャンク合計 {len(chunks)} 件 / 埋め込み {'あり' if index.has_vectors else 'なし'}")
    print(f"保存しました: {out}")
    return 0


def _snapshot_title(law_id: str) -> str:
    """変更が無かったときは法令名がイベントから取れないので、スナップショットから拾う。"""
    path = snapshot_path(settings.snapshots_dir, law_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("law_title", law_id)
    return law_id


def _resolve_models(args: argparse.Namespace) -> ModelSet:
    return ModelSet(
        stage0=args.model_stage0 or settings.require("model_stage0"),
        stage2=args.model_stage2 or settings.require("model_stage2"),
        stage3=args.model_stage3 or settings.require("model_stage3"),
        escalation=args.model_escalation or settings.model_escalation,
    )


def cmd_run(args: argparse.Namespace) -> int:
    index_dir = _index_dir(args.index)
    if not (index_dir / "chunks.json").exists():
        print(f"エラー: インデックスがありません: {index_dir}", file=sys.stderr)
        print("先に `python -m app.cli ingest` を実行してください", file=sys.stderr)
        return 1

    index = ChunkIndex.load(index_dir)
    locations_path = index_dir / "locations.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8")) if locations_path.exists() else {}

    models = _resolve_models(args)

    with EGovClient() as egov:
        event = check_law(egov, args.law_id, settings.snapshots_dir)

    # 変更が無かったことも記録する（ホームの「最近のチェック」に出すため）
    record_check(
        settings.history_path,
        law_id=args.law_id,
        law_title=event.law_title if event else _snapshot_title(args.law_id),
        detected=event is not None,
        revision=event.to_revision if event else None,
        enforcement_date=event.enforcement_date if event else None,
    )

    if event is None:
        print(f"{args.law_id}: 変更なし")
        return 0

    if args.change_filter:
        matched = [d for d in event.diffs if args.change_filter in d.label]
        if not matched:
            print(f"エラー: '{args.change_filter}' に一致する変更がありません", file=sys.stderr)
            return 1
        print(f"変更を絞り込みました: {len(event.diffs)} 件中 {len(matched)} 件")
        event = replace(event, diffs=matched)

    print(f"{event.law_title}")
    print(f"  差分 {len(event.diffs)} 件 / 監視対象チャンク {len(index)} 件")

    cost_log = CostLog(prices=PriceTable.fetch(settings.db_path.parent / "cache/pricing.json"))
    with OrcaRouterClient() as chat:
        embedder = (
            None if args.no_embed else OrcaRouterEmbedder(chat, settings.require("embeddings_model"))
        )
        result = run_pipeline(
            event,
            index,
            chat,
            models,
            embedder=embedder,
            locations=locations,
            linked_doc_ids=set(args.link or []),
            cache=load_cache(None if args.no_cache else settings.db_path.parent / "cache/judgements.json"),
            max_changes=args.max_changes,
            cost_log=cost_log,
            progress=print,
        )

    affected = sum(r.funnel.affected for r in result.results)
    judged = sum(r.funnel.stage3_judged for r in result.results)
    print(f"\n結果: 精査 {judged} 件中、要対応 {affected} 件 / 影響なし {judged - affected} 件")
    print(f"  起票（ファイル単位に展開）: {len(result.alerts)} 件")
    cost_usd = result.cost.get("cost_usd")
    if cost_usd:
        print(f"  コスト実測: ${cost_usd:.4f}（{result.cost['calls']}回・{result.cost['total_tokens']:,}トークン）")
    else:
        print(f"  コスト実測: {result.cost['calls']}回・{result.cost['total_tokens']:,}トークン（単価不明）")
    print(f"  判定キャッシュ: {result.cost['cache']}")

    # 既定の置き場に書けば、そのままAPI（画面）から見える
    out = Path(args.out) if args.out else settings.results_dir / f"{args.law_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"書き出しました: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="ドキュメント鮮度監視エージェント")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rev = sub.add_parser("revisions", help="改正履歴を表示する")
    p_rev.add_argument("law_id")
    p_rev.add_argument("--limit", type=int, default=10)
    p_rev.set_defaults(func=cmd_revisions)

    p_snap = sub.add_parser("snapshot", help="スナップショットを取得して保存する")
    p_snap.add_argument("law_id")
    p_snap.add_argument("--asof", help="YYYY-MM-DD（施行日基準）。改正前で初期化する場合に指定")
    p_snap.add_argument("--dir", help="保存先ディレクトリ（既定: SNAPSHOTS_DIR）")
    p_snap.set_defaults(func=cmd_snapshot)

    p_check = sub.add_parser("check", help="保存済みスナップショットと現行を比較する")
    p_check.add_argument("law_id")
    p_check.add_argument("--dir", help="スナップショットのディレクトリ")
    p_check.add_argument("--json", help="差分（Stage 0 の入力）の書き出し先")
    p_check.add_argument("--limit", type=int, default=10, help="画面に出す差分の件数")
    p_check.set_defaults(func=cmd_check)

    p_ingest = sub.add_parser("ingest", help="監視対象を取り込んでインデックスを作る")
    p_ingest.add_argument("--dir", help="監視対象フォルダ（既定: WATCH_ROOT）")
    p_ingest.add_argument("--out", help="インデックスの保存先")
    p_ingest.add_argument(
        "--no-embed", action="store_true", help="埋め込みを作らない（BM25のみ・オフライン可）"
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_run = sub.add_parser("run", help="Stage 0〜3 を貫通させる")
    p_run.add_argument("law_id")
    p_run.add_argument("--index", help="インデックスのディレクトリ")
    p_run.add_argument(
        "--out", help="結果JSONの書き出し先（既定: RESULTS_DIR/{law_id}.json。APIはここを読む）"
    )
    p_run.add_argument("--max-changes", type=int, help="処理する変更単位の上限（デモ・試走用）")
    p_run.add_argument(
        "--change-filter", help="変更箇所の表示名に含まれる語で絞る（例: 第十六条の二）"
    )
    p_run.add_argument(
        "--link", action="append", help="紐付け済み文書のdoc_id（無条件で精査に通す）。複数指定可"
    )
    p_run.add_argument("--no-embed", action="store_true", help="ベクトル検索を使わない")
    p_run.add_argument("--no-cache", action="store_true", help="判定キャッシュを使わない")
    for stage in ("stage0", "stage2", "stage3", "escalation"):
        p_run.add_argument(f"--model-{stage}", help=f"{stage} のモデル名（既定: .env）")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (EGovError, LLMError, FileNotFoundError, RuntimeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
