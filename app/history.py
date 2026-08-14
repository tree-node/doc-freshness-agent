"""チェック履歴の記録。

ホームの「最近のチェック」には**変更が無かったチェックも出す**（DESIGN.md 原則3）。
そのためには「いつ・どの正本を見て・変更が有ったか無かったか」を残しておく必要がある。
結果JSONは変更を検知したときしか作られないので、別に1行ずつ追記していく。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CheckRecord:
    law_id: str
    law_title: str
    checked_at: str
    detected: bool
    revision: str | None = None  # 検知したときの新しいリビジョン
    enforcement_date: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def record_check(
    path: Path,
    law_id: str,
    law_title: str,
    detected: bool,
    revision: str | None = None,
    enforcement_date: str | None = None,
) -> CheckRecord:
    record = CheckRecord(
        law_id=law_id,
        law_title=law_title,
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
        detected=detected,
        revision=revision,
        enforcement_date=enforcement_date,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return record


def load_checks(path: Path, limit: int | None = None) -> list[CheckRecord]:
    """新しい順に返す。壊れた行があっても履歴全体を落とさない。

    時刻は秒までしか持たないので、同じ秒に複数回チェックすると時刻だけでは並べられない。
    追記順（後の行ほど新しい）をタイブレークに使う。
    """
    if not path.exists():
        return []
    records: list[tuple[int, CheckRecord]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append((index, CheckRecord(**json.loads(line))))
        except (json.JSONDecodeError, TypeError):
            continue
    records.sort(key=lambda item: (item[1].checked_at, item[0]), reverse=True)
    ordered = [record for _, record in records]
    return ordered[:limit] if limit else ordered
