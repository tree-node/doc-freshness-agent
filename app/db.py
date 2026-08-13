"""SQLite 接続。

スキーマ（イベント・変更・チャンク・判定キャッシュ・監査ログ）はパイプライン実装と
同時に入れる。ここでは接続とファイル生成のみを持つ。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping(db_path: Path | None = None) -> bool:
    """DBファイルを作成・読み書きできるか確認する（ヘルスチェック用）。"""
    with connection(db_path) as conn:
        return conn.execute("SELECT 1").fetchone()[0] == 1
