"""バックグラウンドで走らせる処理の管理（「今すぐチェック」用）。

1回のチェックは2〜3分かかる。同期で返すとブラウザが待たされて固まるので、
押した瞬間に受付だけ返し、進捗を別途取りに来てもらう。

**進捗の文言は画面にそのまま出る**ので、技術語（Stage・チャンク・RRF）は使わない
（DESIGN.md 画面構成の文言ルール）。

再起動すると消えるメモリ上の管理でよい。チェックの結果そのものは
結果JSONとチェック履歴に残るので、ジョブの記録を永続化する必要はない。
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal

JobState = Literal["running", "done", "failed"]

MAX_KEEP = 20  # 覚えておくジョブの数。古いものから捨てる


@dataclass
class Job:
    job_id: str
    label: str
    state: JobState = "running"
    progress: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str = ""
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "label": self.label,
            "state": self.state,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._counter = 0

    def start(self, label: str, work: Callable[[Callable[[str], None]], dict[str, Any]]) -> Job:
        """`work` を別スレッドで走らせる。`work` は進捗を報告する関数を受け取る。"""
        with self._lock:
            self._counter += 1
            job = Job(
                job_id=f"job-{self._counter:04d}",
                label=label,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            for stale in self._order[:-MAX_KEEP]:
                self._jobs.pop(stale, None)
            self._order = self._order[-MAX_KEEP:]

        def report(message: str) -> None:
            with self._lock:
                job.progress.append(message)

        def run() -> None:
            try:
                job.result = work(report)
                job.state = "done"
            except Exception as exc:  # 何で落ちても画面に理由を返す（黙って止まらない）
                job.state = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            finally:
                job.finished_at = datetime.now(UTC).isoformat(timespec="seconds")

        threading.Thread(target=run, daemon=True, name=f"job-{job.job_id}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def running(self) -> list[Job]:
        with self._lock:
            return [job for job in self._jobs.values() if job.state == "running"]


runner = JobRunner()
