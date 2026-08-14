"""画面が読むAPI。

**返すのはパイプラインの出力（PipelineResult）そのまま**。整形はフロント側に寄せてある。
サーバー側で画面用に加工し始めると、CLIの出力と画面の表示が二重管理になるため。

主語はイベント（DESIGN.md 設計原則1）なので、URLも `/api/events/{law_id}` が起点。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.history import load_checks

router = APIRouter(prefix="/api")


# 置き場は関数経由で読む。Settings は frozen dataclass で差し替えられないため、
# テストからはこの3つを差し替える。
def results_dir() -> Path:
    return settings.results_dir


def snapshots_dir() -> Path:
    return settings.snapshots_dir


def history_path() -> Path:
    return settings.history_path


def _load_results(directory: Path | None = None) -> list[dict[str, Any]]:
    """検知結果を新しい順に読む。壊れたファイルがあっても全体を落とさない。"""
    directory = directory or results_dir()
    if not directory.exists():
        return []

    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("law_id"):
            results.append(payload)

    results.sort(key=lambda r: (r.get("detected_at") or ""), reverse=True)
    return results


def _load_snapshots(directory: Path | None = None) -> list[dict[str, Any]]:
    directory = directory or snapshots_dir()
    if not directory.exists():
        return []
    snapshots = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("law_id"):
            snapshots.append(payload)
    return snapshots


@router.get("/events")
def list_events() -> dict[str, Any]:
    """検知した変更イベントの一覧。ホームが読む。"""
    return {"events": _load_results()}


@router.get("/events/{law_id}")
def get_event(law_id: str) -> dict[str, Any]:
    """変更イベント1件。変更の詳細・指摘詳細が読む。"""
    for result in _load_results():
        if result["law_id"] == law_id:
            return result
    raise HTTPException(status_code=404, detail=f"イベントが見つかりません: {law_id}")


@router.get("/rules")
def list_rules() -> dict[str, Any]:
    """見守り中のルール（登録済みの正本）。スナップショットの有無が登録の実体。"""
    rules = [
        {
            "law_id": snapshot["law_id"],
            "law_title": snapshot["law_title"],
            "source": "e-Gov",
            "watching_since": snapshot.get("asof"),
            "last_fetched_at": snapshot.get("fetched_at"),
            "revision": snapshot.get("law_revision_id"),
        }
        for snapshot in _load_snapshots()
    ]
    return {"rules": rules}


@router.get("/history")
def list_history(limit: int = 20) -> dict[str, Any]:
    """最近のチェック。**変更が無かったチェックも含める**（DESIGN.md 原則3）。"""
    checks = load_checks(history_path(), limit=limit)
    results = {r["law_id"]: r for r in _load_results()}

    entries = []
    for check in checks:
        entry: dict[str, Any] = {
            "law_id": check.law_id,
            "law_title": check.law_title,
            "checked_at": check.checked_at,
            "detected": check.detected,
        }
        if check.detected:
            result = results.get(check.law_id)
            if result:
                judged = sum(c["funnel"]["stage3_judged"] for c in result["changes"])
                affected = sum(c["funnel"]["affected"] for c in result["changes"])
                entry["summary"] = {
                    "judged": judged,
                    "affected": affected,
                    "not_affected": judged - affected,
                }
        entries.append(entry)
    return {"history": entries}
