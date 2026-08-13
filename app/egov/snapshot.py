"""正本（法令）のスナップショット保持と差分検知。

DESIGN.md「デモ中の『改正』の起こし方（時間巻き戻し方式）」の実体:
スナップショットを改正前（asof指定）で初期化し、本物の e-Gov との差分として実在の改正を検知する。

ここまでが Stage 0（差分の分解とクエリ化）の**入力**。差分をどう変更単位に分けるかは Stage 0 の仕事。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.egov.client import EGovClient
from app.egov.parser import Provision, parse_law_full_text

DiffKind = Literal["added", "removed", "changed"]


@dataclass(frozen=True)
class LawSnapshot:
    law_id: str
    law_revision_id: str
    law_title: str
    enforcement_date: str | None
    asof: str | None
    fetched_at: str
    provisions: dict[str, dict]  # key -> {path, kind, title, caption, text}

    @classmethod
    def from_law_data(cls, law_id: str, data: dict, asof: str | None = None) -> "LawSnapshot":
        info = data.get("revision_info", {})
        provisions = {
            prov.key: {
                "path": list(prov.path),
                "kind": prov.kind,
                "title": prov.title,
                "caption": prov.caption,
                "text": prov.text,
            }
            for prov in parse_law_full_text(data["law_full_text"])
        }
        return cls(
            law_id=law_id,
            law_revision_id=info.get("law_revision_id", ""),
            law_title=info.get("law_title", ""),
            enforcement_date=info.get("amendment_enforcement_date"),
            asof=asof,
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            provisions=provisions,
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "LawSnapshot":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class ProvisionDiff:
    key: str
    kind: DiffKind
    label: str  # 表示用（例: 本則 > 第四章 子の看護等休暇 > 第十六条の二）
    title: str | None
    before: str | None
    after: str | None


def diff_snapshots(old: LawSnapshot, new: LawSnapshot) -> list[ProvisionDiff]:
    """条文の差分を取る。順序は 変更 → 追加 → 削除。

    削除（change_type: delete）は「削除された条を参照し続けている文書」を探すため
    後段で特別扱いする（DESIGN.md Stage 0/1）ので、ここで落とさない。
    """
    diffs: list[ProvisionDiff] = []

    for key, new_prov in new.provisions.items():
        old_prov = old.provisions.get(key)
        if old_prov is None:
            diffs.append(_diff(key, "added", new_prov, before=None, after=new_prov["text"]))
        elif old_prov["text"] != new_prov["text"]:
            diffs.append(
                _diff(key, "changed", new_prov, before=old_prov["text"], after=new_prov["text"])
            )

    for key, old_prov in old.provisions.items():
        if key not in new.provisions:
            diffs.append(_diff(key, "removed", old_prov, before=old_prov["text"], after=None))

    order = {"changed": 0, "added": 1, "removed": 2}
    return sorted(diffs, key=lambda d: (order[d.kind], d.key))


def _diff(key: str, kind: DiffKind, prov: dict, before: str | None, after: str | None) -> ProvisionDiff:
    label_parts = [*prov.get("path", [])]
    if prov.get("title"):
        label_parts.append(prov["title"])
    return ProvisionDiff(
        key=key,
        kind=kind,
        label=" > ".join(label_parts) or key,
        title=prov.get("title"),
        before=before,
        after=after,
    )


@dataclass(frozen=True)
class ChangeEvent:
    """正本の変更イベント（UI・データモデルの主語。DESIGN.md 設計原則1）。"""

    law_id: str
    law_title: str
    from_revision: str
    to_revision: str
    enforcement_date: str | None
    detected_at: str
    diffs: list[ProvisionDiff]

    def to_json(self) -> str:
        payload = asdict(self)
        return json.dumps(payload, ensure_ascii=False, indent=2)


def snapshot_path(root: Path, law_id: str) -> Path:
    return root / f"{law_id}.json"


def fetch_snapshot(client: EGovClient, law_id: str, asof: str | None = None) -> LawSnapshot:
    return LawSnapshot.from_law_data(law_id, client.get_law_data(law_id, asof=asof), asof=asof)


def check_law(client: EGovClient, law_id: str, root: Path) -> ChangeEvent | None:
    """保存済みスナップショットと現行を比較する（＝巡回1回分）。

    差分がなければ None（「変更なし」もUIに出すため、呼び出し側で握りつぶさない）。
    """
    path = snapshot_path(root, law_id)
    if not path.exists():
        raise FileNotFoundError(
            f"スナップショットがありません: {path}\n"
            f"先に `python -m app.cli snapshot {law_id} --asof YYYY-MM-DD` で初期化してください。"
        )
    stored = LawSnapshot.load(path)
    current = fetch_snapshot(client, law_id)

    if stored.law_revision_id == current.law_revision_id:
        return None

    diffs = diff_snapshots(stored, current)
    return ChangeEvent(
        law_id=law_id,
        law_title=current.law_title,
        from_revision=stored.law_revision_id,
        to_revision=current.law_revision_id,
        enforcement_date=current.enforcement_date,
        detected_at=datetime.now(UTC).isoformat(timespec="seconds"),
        diffs=diffs,
    )
