"""Backup orchestrator: validate -> dispatch -> manifest (pure w.r.t. config)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from abackup.config import _atomic_write
from abackup.core.compression import make_archive, make_zip
from abackup.core.copy import copy_tree
from abackup.core.paths import ensure_dir, get_data_dir
from abackup.core.progress import (
    PHASE_CANCELLED,
    PHASE_DONE,
    PHASE_FAILED,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_SUCCESS,
    OptionalProgressCallback,
    Progress,
)
from abackup.core.retention import enforce_retention
from abackup.models import BackupJob, BackupMethod
from abackup.utils.errors import DestinationError, JobCancelled, SourceNotFound
from abackup.utils.logging import RunLogger


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class BackupResult:
    job_id: str
    method: str
    status: str
    summary: dict
    manifest_path: str | None = None
    error: str | None = None
    updated_job: BackupJob | None = None


def run_job(
    job: BackupJob,
    *,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    on_progress: OptionalProgressCallback = None,
    clock: Callable[[], datetime] | None = None,
    zip_compression_level: int = 6,
    seven_zip_compression_level: int = 3,
    prefer_py7zr: bool = False,
    use_hash: bool = False,
    threads: int | None = None,
    cancel: threading.Event | None = None,
    dry_run: bool = False,
) -> BackupResult:
    """Run a single backup job.

    Writes a run manifest + log under the data dir, and returns an updated
    ``BackupJob`` (with ``last_run_at``/``last_status``) for the caller to
    persist. Does NOT mutate the jobs config itself.

    If ``cancel`` (a ``threading.Event``) is set mid-run, the underlying copy/zip
    raises ``JobCancelled`` and this returns a result with ``status="cancelled"``.

    When ``dry_run`` is True, the job is planned (files scanned, include/exclude
    applied) but nothing is written and no manifest is produced; the summary
    reports the planned totals.
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
                exclude_patterns=job.exclude_patterns,
                include_patterns=job.include_patterns,
                plan_only=dry_run,
            )
            summary: dict = {"archive": str(out)}
        elif job.method == BackupMethod.SEVEN_ZIP:
            out = make_archive(
                job.source,
                job.destination,
                compress_level=seven_zip_compression_level,
                prefer_py7zr=prefer_py7zr,
                cancel=cancel,
                job_id=job.id,
                on_progress=_forward,
                threads=threads,
                exclude_patterns=job.exclude_patterns,
                include_patterns=job.include_patterns,
                plan_only=dry_run,
            )
            summary = {"archive": str(out)}
        else:
            summary = copy_tree(
                job.source,
                job.destination,
                job_id=job.id,
                on_progress=_forward,
                use_hash=use_hash,
                cancel=cancel,
                exclude_patterns=job.exclude_patterns,
                include_patterns=job.include_patterns,
                plan_only=dry_run,
            )
        status = "success"
    except JobCancelled:
        _terminal(PHASE_CANCELLED, STATUS_CANCELLED)
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "cancelled"})
        return BackupResult(job.id, job.method.value, "cancelled", {}, None, "cancelled", updated)
    except (SourceNotFound, DestinationError) as exc:
        logger.log("error", {"job_id": job.id, "error": str(exc)})
        _terminal(PHASE_FAILED, STATUS_FAILED)
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "failed"})
        return BackupResult(job.id, job.method.value, "failed", {}, None, str(exc), updated)

    if dry_run:
        # No writes, no manifest, no retention. Report the plan.
        _terminal(PHASE_DONE, STATUS_SUCCESS)
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "success"})
        return BackupResult(job.id, job.method.value, "success", summary, None, None, updated)

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
    _atomic_write(manifest_path, manifest)
    logger.log("info", manifest)

    # Retention: for archive methods, prune old archives in the destination.
    deleted: list[str] = []
    if job.retention_count is not None and job.method != BackupMethod.COPY:
        from pathlib import Path as _Path

        dest = _Path(job.destination)
        if dest.is_dir():
            ext = ".zip" if job.method == BackupMethod.ZIP else ".7z"
            archives = [p for p in dest.glob(f"*{ext}") if p.is_file()]
            deleted = [str(p) for p in enforce_retention(archives, job.retention_count)]

    updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": status})
    if deleted:
        summary = {**summary, "archives_deleted": deleted}
    return BackupResult(job.id, job.method.value, status, summary, str(manifest_path), None, updated)
