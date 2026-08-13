"""パイプラインを貫通させるためのCLI（DESIGN.md 実装順序: CLI → 評価 → UI）。

    python -m app.cli revisions 403AC0000000076
    python -m app.cli snapshot  403AC0000000076 --asof 2025-03-01   # 時間巻き戻し初期化
    python -m app.cli check     403AC0000000076 [--json out.json]   # 巡回1回分
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import settings
from app.egov import EGovClient, EGovError, check_law, fetch_snapshot, snapshot_path

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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (EGovError, FileNotFoundError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
