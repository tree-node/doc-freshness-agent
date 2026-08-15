"""画面が読むAPI。

**返すのはパイプラインの出力（PipelineResult）そのまま**。整形はフロント側に寄せてある。
サーバー側で画面用に加工し始めると、CLIの出力と画面の表示が二重管理になるため。

主語はイベント（DESIGN.md 設計原則1）なので、URLも `/api/events/{law_id}` が起点。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.egov import EGovClient, EGovError, fetch_snapshot, snapshot_path
from app.checks import NotReadyError, previous_filter, run_check
from app.history import load_checks
from app.jobs import runner
from app.proposal import edits_from_result, generate_revised_document
from app.sources.local import UnsupportedFormatError
from app.store import (
    FindingKey,
    UnknownStatusError,
    disabled_law_ids,
    is_rule_enabled,
    list_audit,
    list_statuses,
    set_rule_enabled,
    set_status,
)

router = APIRouter(prefix="/api")


# 置き場は関数経由で読む。Settings は frozen dataclass で差し替えられないため、
# テストからはこの3つを差し替える。
def results_dir() -> Path:
    return settings.results_dir


def snapshots_dir() -> Path:
    return settings.snapshots_dir


def history_path() -> Path:
    return settings.history_path


def watch_root() -> Path:
    return settings.watch_root


def outputs_dir() -> Path:
    return settings.outputs_dir


def db_path() -> Path:
    return settings.db_path


def egov_client() -> EGovClient:
    """e-Gov クライアント。テストからはここを差し替える（テストは通信しない）。"""
    return EGovClient()


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
    """検知した変更イベントの一覧。ホームが読む。

    **監視を止めている正本のイベントは出さない**。止めた瞬間にホームから指摘が消え、
    再開すると戻る——正本と社内文書の依存関係が目に見える。
    検知結果そのものは消していないので、再開すればそのまま復活する。
    """
    disabled = disabled_law_ids(db_path=db_path())
    return {"events": [r for r in _load_results() if r["law_id"] not in disabled]}


@router.get("/events/{law_id}")
def get_event(law_id: str) -> dict[str, Any]:
    """変更イベント1件。変更の詳細・指摘詳細が読む。"""
    for result in _load_results():
        if result["law_id"] == law_id:
            return result
    raise HTTPException(status_code=404, detail=f"イベントが見つかりません: {law_id}")


@router.get("/events/{law_id}/revised")
def download_revised_document(law_id: str, doc_id: str) -> FileResponse:
    """修正版ファイルを作って返す。

    **元のファイルには触らない**（DESIGN.md 設計原則2）。置換先のパスはヘッダーで伝え、
    実際に置き換えるかどうかは受け取った人間が決める。
    """
    result = get_event(law_id)
    edits = edits_from_result(result, doc_id)
    if not edits:
        raise HTTPException(status_code=404, detail=f"この文書に対する修正案がありません: {doc_id}")

    source = watch_root() / doc_id
    try:
        generated = generate_revised_document(source, doc_id, edits, outputs_dir() / law_id)
    except (FileNotFoundError, UnsupportedFormatError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not generated.applied:
        reasons = "／".join(reason for _, reason in generated.skipped) or "理由不明"
        raise HTTPException(status_code=422, detail=f"修正を当てられませんでした: {reasons}")

    return FileResponse(
        generated.output_path,
        filename=Path(doc_id).name,
        headers={
            # 置換先と、当てられなかった箇所の数を一緒に返す（黙って落とさない）
            "X-Replace-Target": quote(generated.replace_target),
            "X-Applied-Count": str(len(generated.applied)),
            "X-Skipped-Count": str(len(generated.skipped)),
        },
    )


class StatusUpdate(BaseModel):
    """判断の登録。誰がどう決めたかを残すため、根拠も一緒に受け取る。"""

    change_id: str
    chunk_id: str
    doc_id: str
    status: str
    note: str | None = None
    actor: str = "担当者"


@router.get("/events/{law_id}/statuses")
def list_event_statuses(law_id: str) -> dict[str, Any]:
    """このイベントに対して人が下した判断の一覧。画面が状態を復元するのに使う。"""
    return {"statuses": [record.to_dict() for record in list_statuses(law_id, db_path=db_path())]}


@router.put("/events/{law_id}/statuses")
def update_status(law_id: str, update: StatusUpdate) -> dict[str, Any]:
    """判断を保存する。棄却（対応不要）も含めて監査ログに残す。"""
    result = get_event(law_id)
    finding = _find_finding(result, update.change_id, update.chunk_id, update.doc_id)
    change = _find_change(result, update.change_id)

    try:
        record = set_status(
            FindingKey(
                law_id=law_id,
                change_id=update.change_id,
                chunk_id=update.chunk_id,
                doc_id=update.doc_id,
            ),
            status=update.status,
            actor=update.actor,
            note=update.note,
            law_title=result.get("law_title"),
            # 根拠法令をセットで残す（DESIGN.md 監査ログ）
            evidence_law=f"{result.get('law_title', '')} {change.get('target_path', '')}".strip() or None,
            evidence_location=(finding or {}).get("evidence_location"),
            change_summary=change.get("summary"),
            db_path=db_path(),
        )
    except UnknownStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return record.to_dict()


def _find_change(result: dict, change_id: str) -> dict:
    for change_result in result.get("changes", []):
        if change_result["change"]["change_id"] == change_id:
            return change_result["change"]
    raise HTTPException(status_code=404, detail=f"変更が見つかりません: {change_id}")


def _find_finding(result: dict, change_id: str, chunk_id: str, doc_id: str) -> dict | None:
    for change_result in result.get("changes", []):
        if change_result["change"]["change_id"] != change_id:
            continue
        for finding in change_result.get("findings", []):
            if finding.get("chunk_id") == chunk_id:
                return finding
    # 起票（alerts）はファイル単位に展開されているので、そちらからも探す
    for alert in result.get("alerts", []):
        if alert.get("chunk_id") == chunk_id and alert.get("doc_id") == doc_id:
            return alert.get("finding")
    return None


@router.get("/audit")
def list_audit_log(limit: int = 100, law_id: str | None = None) -> dict[str, Any]:
    """監査ログ。誰が・いつ・何を根拠に・どう判断したかを新しい順に返す。"""
    return {
        "audit": [
            entry.to_dict() for entry in list_audit(limit=limit, law_id=law_id, db_path=db_path())
        ]
    }


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
            "enabled": is_rule_enabled(snapshot["law_id"], db_path=db_path()),
        }
        for snapshot in _load_snapshots()
    ]
    return {"rules": rules}


class RuleUpdate(BaseModel):
    enabled: bool


class RuleCreate(BaseModel):
    """正本の登録。asof は「いつ時点の条文を出発点にするか」。

    省略すると現在の条文で登録する（＝これ以降の改正だけを検知する）。
    デモのように過去に遡って検知させたい場合は日付を指定する。
    """

    law_id: str
    asof: str | None = None


@router.get("/laws")
def search_laws(q: str, limit: int = 10) -> dict[str, Any]:
    """法令をキーワードで探す。登録するとき法令IDを知らなくて済むように。

    **法令名の部分一致なので同名の別法令が混ざる**（育介法を探すと船員向けの
    施行規則も出る）ので、法令の種類も一緒に返して選べるようにする。
    """
    try:
        with egov_client() as client:
            found = client.search_laws(q, limit=limit)
    except EGovError as exc:
        raise HTTPException(status_code=502, detail=f"法令の検索に失敗しました: {exc}") from exc

    registered = {snapshot["law_id"] for snapshot in _load_snapshots()}
    return {
        "laws": [
            {
                "law_id": law["law_info"]["law_id"],
                "law_title": law["revision_info"]["law_title"],
                "law_num": law["law_info"]["law_num"],
                "law_type": law["law_info"]["law_type"],
                "registered": law["law_info"]["law_id"] in registered,
            }
            for law in found
        ]
    }


@router.post("/rules")
def create_rule(payload: RuleCreate) -> dict[str, Any]:
    """正本を登録する。指定時点の条文を取ってきて、比較の出発点として保存する。

    これ以降のチェックで、保存した条文と現在の条文の差分が「法令の変更」になる。
    """
    directory = snapshots_dir()
    if (directory / f"{payload.law_id}.json").exists():
        raise HTTPException(status_code=409, detail=f"すでに登録されています: {payload.law_id}")

    try:
        with egov_client() as client:
            snapshot = fetch_snapshot(client, payload.law_id, asof=payload.asof)
    except EGovError as exc:
        raise HTTPException(status_code=422, detail=f"法令を取得できませんでした: {exc}") from exc

    snapshot.save(snapshot_path(directory, payload.law_id))
    return {
        "law_id": snapshot.law_id,
        "law_title": snapshot.law_title,
        "watching_since": payload.asof,
        "revision": snapshot.law_revision_id,
        "provisions": len(snapshot.provisions),
        "enabled": True,
    }


@router.put("/rules/{law_id}")
def update_rule(law_id: str, update: RuleUpdate) -> dict[str, Any]:
    """正本の監視を止める／再開する。

    止めてもスナップショットや検知結果は消さない。見るのをやめるだけ。
    """
    known = {snapshot["law_id"] for snapshot in _load_snapshots()}
    if law_id not in known:
        raise HTTPException(status_code=404, detail=f"登録されていない正本です: {law_id}")
    set_rule_enabled(law_id, update.enabled, db_path=db_path())
    return {"law_id": law_id, "enabled": update.enabled}


class CheckRequest(BaseModel):
    """今すぐチェックの実行。

    law_id を省くと、登録済みで監視中の正本をすべて順に見る。
    """

    law_id: str | None = None


@router.post("/checks")
def start_check(payload: CheckRequest) -> dict[str, Any]:
    """チェックを始める。**すぐに受付だけ返す**（1件2〜3分かかるため）。

    進捗は GET /api/checks/{job_id} で取りに来てもらう。
    """
    disabled = disabled_law_ids(db_path=db_path())
    targets = (
        [payload.law_id]
        if payload.law_id
        else [s["law_id"] for s in _load_snapshots() if s["law_id"] not in disabled]
    )
    if not targets:
        raise HTTPException(status_code=422, detail="監視中の正本がありません")

    known = {snapshot["law_id"] for snapshot in _load_snapshots()}
    unknown = [law_id for law_id in targets if law_id not in known]
    if unknown:
        raise HTTPException(status_code=404, detail=f"登録されていない正本です: {unknown[0]}")

    if runner.running():
        raise HTTPException(status_code=409, detail="ほかのチェックがまだ実行中です")

    titles = [s["law_title"] for s in _load_snapshots() if s["law_id"] in targets]
    label = "、".join(t[:14] for t in titles) or "チェック"

    def work(report):
        results = []
        for law_id in targets:
            results.append(
                run_check(law_id, report, change_filter=previous_filter(law_id))
            )
        return {"checked": results}

    try:
        job = runner.start(label, work)
    except NotReadyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job.to_dict()


@router.get("/checks/{job_id}")
def get_check(job_id: str) -> dict[str, Any]:
    """チェックの進み具合。終わっていれば結果も入る。"""
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"見つかりません: {job_id}")
    return job.to_dict()


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
