"""Backup orchestrator: validate -> dispatch -> manifest (pure w.r.t. config)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from abackup.core.archive import make_zip
from abackup.core.copy import copy_tree
from abackup.core.paths import get_data_dir, ensure_dir
from abackup.core.progress import (
    Progress,
    PHASE_DONE,
    PHASE_FAILED,
    PHASE_CANCELLED,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_CANCELLED,
)
from abackup.models import BackupJob, BackupMethod
from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled
from abackup.utils.logging import RunLogger

ProgressFn = Callable[[int, int, str], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BackupResult:
    job_id: str
    method: str
    status: str
    summary: dict
    manifest_path: Optional[str] = None
    error: Optional[str] = None
    updated_job: Optional[BackupJob] = None


def run_job(
    job: BackupJob,
    *,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    on_progress: Optional[ProgressFn] = None,
    clock=None,
    zip_compression_level: int = 6,
    cancel=None,
) -> BackupResult:
    """Run a single backup job.

    Writes a run manifest + log under the data dir, and returns an updated
    ``BackupJob`` (with ``last_run_at``/``last_status``) for the caller to
    persist. Does NOT mutate the jobs config itself.

    If ``cancel`` (a ``threading.Event``) is set mid-run, the underlying copy/zip
    raises ``JobCancelled`` and this returns a result with ``status="cancelled"``.
    """
    clock = clock or _now
    data_dir = get_data_dir(data_dir)
    ensure_dir(Path(data_dir) / "manifests")
    ensure_dir(Path(data_dir) / "logs")
    logger = RunLogger(data_dir, job.id)

    # Forward progress to the caller while remembering the latest snapshot so we
    # can emit a terminal status (success/failed/cancelled) with accurate totals.
    last: dict = {}

    def _forward(p: Progress) -> None:
        last["p"] = p
        if on_progress is not None:
            on_progress(p)

    def _terminal(phase: str, status: str) -> None:
        if on_progress is None:
            return
        prev = last.get("p")
        on_progress(
            Progress(
                job_id=job.id,
                files_total=prev.files_total if prev else 0,
                files_done=prev.files_done if prev else 0,
                bytes_total=prev.bytes_total if prev else 0,
                bytes_done=prev.bytes_done if prev else 0,
                current_file="",
                phase=phase,
                status=status,
            )
        )

    try:
        if job.method == BackupMethod.ZIP:
            out = make_zip(
                job.source,
                job.destination,
                compress_level=zip_compression_level,
                cancel=cancel,
                job_id=job.id,
                on_progress=_forward,
                log=logger.log,
            )
            summary: dict = {"archive": str(out)}
        else:
            summary = copy_tree(
                job.source,
                job.destination,
                job_id=job.id,
                on_progress=_forward,
                cancel=cancel,
            )
        status = "success"
    except JobCancelled:
        _terminal(PHASE_CANCELLED, STATUS_CANCELLED)
        updated = BackupJob(
            **{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "cancelled"}
        )
        return BackupResult(
            job.id, job.method.value, "cancelled", {}, None, "cancelled", updated
        )
    except (SourceNotFound, DestinationError) as exc:
        logger.log("error", {"job_id": job.id, "error": str(exc)})
        _terminal(PHASE_FAILED, STATUS_FAILED)
        updated = BackupJob(
            **{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "failed"}
        )
        return BackupResult(job.id, job.method.value, "failed", {}, None, str(exc), updated)

    _terminal(PHASE_DONE, STATUS_SUCCESS)

    manifest = {
        "job_id": job.id,
        "source": job.source,
        "destination": job.destination,
        "method": job.method.value,
        "started_at": clock().isoformat(),
        "status": status,
        "summary": summary,
    }
    manifest_path = Path(data_dir) / "manifests" / f"{job.id}.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.log("info", manifest)

    updated = BackupJob(
        **{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": status}
    )
    return BackupResult(
        job.id, job.method.value, status, summary, str(manifest_path), None, updated
    )
