#!/usr/bin/env python3
"""デモを動かせる状態を、自分の環境で作る。

`data/` 配下（スナップショット・索引・検知結果）は生成物なのでリポジトリに入っていない。
**他の人の環境でも同じ手順で作れることを確かめる**ためでもあるので、
配られたものを見るのではなく、ここから自分で作る。

    python scripts/setup_demo.py

やること:
  1. 正本2本のスナップショットを、改正前の時点で取得する（e-Gov。認証不要・数秒）
  2. 監視対象フォルダを取り込んで索引を作る（埋め込みAPIを使う。1〜2分）

検知（判定）まで走らせるのは別コマンド。時間と費用がかかるので、ここには含めない。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cli import main as cli  # noqa: E402
from app.config import settings  # noqa: E402

# デモで見張る正本と、どの時点を出発点にするか（PROGRESS.md 決定ログ参照）
SOURCES = [
    ("403AC0000000076", "2025-03-01", "育児・介護休業法"),
    ("322AC0000000049", "2019-03-01", "労働基準法"),
]

# セットアップ後に流すと指摘が出る変更（デモの本命）
DEMO_RUNS = [
    ("403AC0000000076", "第十六条の二", "子の看護休暇の対象拡大"),
    ("322AC0000000049", "第百三十八条", "割増賃金の猶予規定の削除"),
]


def step(number: int, text: str) -> None:
    print(f"\n[{number}] {text}")


def main() -> int:
    print("デモを動かせる状態を作ります")
    print(f"  監視対象フォルダ: {settings.watch_root}")

    if not settings.watch_root.exists():
        print(f"\nエラー: 監視対象フォルダがありません: {settings.watch_root}", file=sys.stderr)
        print("  .env の WATCH_ROOT を確認してください（既定: ./demo-data/監視対象）", file=sys.stderr)
        return 1

    step(1, "正本のスナップショットを取ります（e-Gov・認証不要）")
    for law_id, asof, name in SOURCES:
        print(f"  - {name}（{asof} 時点）")
        if cli(["snapshot", law_id, "--asof", asof]) != 0:
            print(f"\nエラー: {name} を取得できませんでした", file=sys.stderr)
            return 1

    step(2, "監視対象を取り込んで索引を作ります（1〜2分かかります）")
    if not settings.embeddings_model:
        print("  EMBEDDINGS_MODEL が未設定のため、キーワード検索だけで作ります")
        print("  （意味検索は使えませんが、デモは動きます）")
        code = cli(["ingest", "--no-embed"])
    else:
        code = cli(["ingest"])
    if code != 0:
        print("\nエラー: 取り込みに失敗しました", file=sys.stderr)
        print("  .env の ORCAROUTER_API_KEY と EMBEDDINGS_MODEL を確認してください", file=sys.stderr)
        return 1

    print("\n" + "=" * 66)
    print("ここまでで画面は動きます（検知結果はまだ空です）")
    print("=" * 66)
    print("\n  uvicorn app.main:app --port 8000")
    print("  cd frontend && npm run dev")
    print("\n指摘を出すには、変更を1つ選んで判定まで走らせてください")
    print("（1件あたり2〜3分・$0.05〜0.12 かかります）:\n")
    for law_id, change, name in DEMO_RUNS:
        print(f"  python -m app.cli run {law_id} --change-filter {change}")
        print(f"      → {name}")
    print("\n画面の「今すぐチェック」からも同じことができます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
