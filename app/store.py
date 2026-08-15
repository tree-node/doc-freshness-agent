"""判断（ステータス）と監査ログの保存。

DESIGN.md の要件:
  - ステータス管理: 未対応 / 承認 / **棄却** / 検討中
  - 監査ログ: 誰が・いつ・どの改正を根拠に・どう判断したか。
    **「対応不要」の判断も記録する**。根拠法令をセットで持つ

判断は上書きされるが、**監査ログは追記のみ**。あとから「なぜそう決めたか」を辿れることが
このプロダクトの主張の一部なので、履歴を消せる作りにしない。
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db import connection

STATUSES = ("open", "approved", "rejected", "pending")
STATUS_LABELS = {
    "open": "未対応",
    "approved": "承認",
    "rejected": "棄却",
    "pending": "検討中",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS finding_status (
    law_id      TEXT NOT NULL,
    change_id   TEXT NOT NULL,
    chunk_id    TEXT NOT NULL,
    doc_id      TEXT NOT NULL,
    status      TEXT NOT NULL,
    note        TEXT,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL,
    PRIMARY KEY (law_id, change_id, chunk_id, doc_id)
);

-- 監査ログは追記のみ。判断を変えても過去の判断は消さない
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    actor         TEXT NOT NULL,
    law_id        TEXT NOT NULL,
    law_title     TEXT,
    change_id     TEXT NOT NULL,
    chunk_id      TEXT NOT NULL,
    doc_id        TEXT NOT NULL,
    from_status   TEXT,
    to_status     TEXT NOT NULL,
    note          TEXT,
    -- 根拠法令をセットで持つ（あとから「何を根拠に決めたか」を辿れるように）
    evidence_law      TEXT,
    evidence_location TEXT,
    change_summary    TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log (at DESC);
"""


class UnknownStatusError(ValueError):
    pass


@dataclass(frozen=True)
class FindingKey:
    law_id: str
    change_id: str
    chunk_id: str
    doc_id: str


@dataclass(frozen=True)
class StatusRecord:
    law_id: str
    change_id: str
    chunk_id: str
    doc_id: str
    status: str
    note: str | None
    updated_at: str
    updated_by: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status_label"] = STATUS_LABELS.get(self.status, self.status)
        return data


@dataclass(frozen=True)
class AuditEntry:
    at: str
    actor: str
    law_id: str
    law_title: str | None
    change_id: str
    chunk_id: str
    doc_id: str
    from_status: str | None
    to_status: str
    note: str | None
    evidence_law: str | None
    evidence_location: str | None
    change_summary: str | None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["to_status_label"] = STATUS_LABELS.get(self.to_status, self.to_status)
        data["from_status_label"] = STATUS_LABELS.get(self.from_status or "", self.from_status)
        return data


def init_db(db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.executescript(SCHEMA)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def get_status(key: FindingKey, db_path: Path | None = None) -> StatusRecord | None:
    with connection(db_path) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """SELECT * FROM finding_status
               WHERE law_id = ? AND change_id = ? AND chunk_id = ? AND doc_id = ?""",
            (key.law_id, key.change_id, key.chunk_id, key.doc_id),
        ).fetchone()
    return StatusRecord(**dict(row)) if row else None


def list_statuses(law_id: str, db_path: Path | None = None) -> list[StatusRecord]:
    with connection(db_path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT * FROM finding_status WHERE law_id = ? ORDER BY updated_at DESC", (law_id,)
        ).fetchall()
    return [StatusRecord(**dict(row)) for row in rows]


def set_status(
    key: FindingKey,
    status: str,
    actor: str = "担当者",
    note: str | None = None,
    law_title: str | None = None,
    evidence_law: str | None = None,
    evidence_location: str | None = None,
    change_summary: str | None = None,
    db_path: Path | None = None,
) -> StatusRecord:
    """判断を保存し、同時に監査ログへ1行残す。

    **「棄却（対応不要）」も必ず記録する**。何を見送ったかが後から分からないと、
    監査ログの意味がない（DESIGN.md）。
    """
    if status not in STATUSES:
        raise UnknownStatusError(f"不明なステータスです: {status}（{', '.join(STATUSES)} のいずれか）")

    now = datetime.now(UTC).isoformat(timespec="seconds")
    with connection(db_path) as conn:
        _ensure_schema(conn)
        previous = conn.execute(
            """SELECT status FROM finding_status
               WHERE law_id = ? AND change_id = ? AND chunk_id = ? AND doc_id = ?""",
            (key.law_id, key.change_id, key.chunk_id, key.doc_id),
        ).fetchone()

        conn.execute(
            """INSERT INTO finding_status
                   (law_id, change_id, chunk_id, doc_id, status, note, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (law_id, change_id, chunk_id, doc_id) DO UPDATE SET
                   status = excluded.status,
                   note = excluded.note,
                   updated_at = excluded.updated_at,
                   updated_by = excluded.updated_by""",
            (key.law_id, key.change_id, key.chunk_id, key.doc_id, status, note, now, actor),
        )
        conn.execute(
            """INSERT INTO audit_log
                   (at, actor, law_id, law_title, change_id, chunk_id, doc_id,
                    from_status, to_status, note, evidence_law, evidence_location, change_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                actor,
                key.law_id,
                law_title,
                key.change_id,
                key.chunk_id,
                key.doc_id,
                previous["status"] if previous else None,
                status,
                note,
                evidence_law,
                evidence_location,
                change_summary,
            ),
        )

    return StatusRecord(
        law_id=key.law_id,
        change_id=key.change_id,
        chunk_id=key.chunk_id,
        doc_id=key.doc_id,
        status=status,
        note=note,
        updated_at=now,
        updated_by=actor,
    )


def list_audit(limit: int = 100, law_id: str | None = None, db_path: Path | None = None) -> list[AuditEntry]:
    """監査ログを新しい順に返す。"""
    query = "SELECT * FROM audit_log"
    params: tuple = ()
    if law_id:
        query += " WHERE law_id = ?"
        params = (law_id,)
    query += " ORDER BY at DESC, id DESC LIMIT ?"
    params = (*params, limit)

    with connection(db_path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(query, params).fetchall()
    return [AuditEntry(**{k: v for k, v in dict(row).items() if k != "id"}) for row in rows]
