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
from abackup.core.history import RunHistoryEntry, _make_run_id, append_run
from abackup.core.paths import ensure_dir, get_data_dir, resolve_destination
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


def format_summary(summary: dict) -> str:
    """Render a ``BackupResult.summary`` dict as a friendly one-line string.

    Used by the TUI so users see e.g. ``archive: D:/Backups/job.7z`` instead of
    the raw Python dict repr.
    """
    if not summary:
        return ""
    parts = []
    if "archive" in summary:
        parts.append(f"archive: {summary['archive']}")
    if "files" in summary:
        parts.append(f"files: {summary['files']}")
    if "bytes" in summary:
        mb = summary["bytes"] / (1024 * 1024)
        parts.append(f"{mb:.1f} MB")
    if "failed_files" in summary and summary["failed_files"]:
        parts.append(f"failed: {len(summary['failed_files'])}")
    if "archives_deleted" in summary:
        parts.append(f"deleted: {summary['archives_deleted']}")
    if not parts:
        # Fall back to a compact key=value rendering for unknown keys.
        parts.append(", ".join(f"{k}: {v}" for k, v in summary.items()))
    return " · ".join(parts)


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
    prefer_robocopy: bool = True,
    use_hash: bool = False,
    threads: int | None = None,
    cancel: threading.Event | None = None,
    dry_run: bool = False,
    portable: bool = False,
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

    When ``portable`` is True, no manifest/log/history is written and the backup
    is performed atomically (staged in a temp location, then moved/replaced into
    place only on success). This is the config-free one-shot mode used by the
    CLI ``--source/--destination/--method`` invocation.
    """
    clock = clock or _now
    data_dir = get_data_dir(data_dir)
    if portable:
        # No persistent side outputs in portable mode.
        logger = None
    else:
        ensure_dir(Path(data_dir) / "manifests")
        ensure_dir(Path(data_dir) / "logs")
        logger = RunLogger(data_dir, job.id)
    started_at = clock()

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

    def _record_history(status: str, summary: dict, error: str | None, archive_out=None) -> None:
        """Append a RunHistoryEntry for this execution (RM-06)."""
        if portable:
            return
        finished_at = clock()
        prev = last.get("p")
        archive_size = None
        if archive_out is not None and not dry_run:
            try:
                archive_size = Path(archive_out).stat().st_size
            except OSError:
                archive_size = None
        entry = RunHistoryEntry(
            job_id=job.id,
            run_id=_make_run_id(job.id, started_at.isoformat()),
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=(finished_at - started_at).total_seconds(),
            files_total=prev.files_total if prev else 0,
            files_done=prev.files_done if prev else 0,
            bytes_total=prev.bytes_total if prev else 0,
            bytes_done=prev.bytes_done if prev else 0,
            archive_size=archive_size,
            status=status,
            method=job.method.value,
            error=error,
            summary=summary,
        )
        try:
            append_run(data_dir, entry)
        except OSError:
            # History is best-effort; never fail a backup because of it.
            pass

    # RM-10: optionally write each run into its own timestamped subfolder.
    dest = resolve_destination(job, clock=clock, stamp=job.subfolder_stamp)

    # Portable copy atomicity: stage into a temp dir, then move into place only
    # on success. Archive methods are already atomic (temp file + os.replace).
    import shutil
    import tempfile

    staging_dest = None
    effective_dest = dest
    if portable and job.method == BackupMethod.COPY and not dry_run:
        staging_dest = Path(tempfile.mkdtemp(prefix="abackup-stage-"))
        effective_dest = staging_dest

    try:
        if job.method == BackupMethod.ZIP:
            out = make_zip(
                job.source,
                dest,
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
                dest,
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
                effective_dest,
                job_id=job.id,
                on_progress=_forward,
                use_hash=use_hash,
                prefer_robocopy=prefer_robocopy,
                cancel=cancel,
                exclude_patterns=job.exclude_patterns,
                include_patterns=job.include_patterns,
                plan_only=dry_run,
            )
        status = "success"
    except JobCancelled:
        if staging_dest is not None and staging_dest.exists():
            shutil.rmtree(staging_dest, ignore_errors=True)
        _terminal(PHASE_CANCELLED, STATUS_CANCELLED)
        _record_history("cancelled", {}, "cancelled")
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "cancelled"})
        return BackupResult(job.id, job.method.value, "cancelled", {}, None, "cancelled", updated)
    except (SourceNotFound, DestinationError) as exc:
        if staging_dest is not None and staging_dest.exists():
            shutil.rmtree(staging_dest, ignore_errors=True)
        if logger is not None:
            logger.log("error", {"job_id": job.id, "error": str(exc)})
        _terminal(PHASE_FAILED, STATUS_FAILED)
        _record_history("failed", {}, str(exc))
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "failed"})
        return BackupResult(job.id, job.method.value, "failed", {}, None, str(exc), updated)

    if dry_run:
        # No writes, no manifest, no retention. Report the plan.
        _terminal(PHASE_DONE, STATUS_SUCCESS)
        _record_history("success", summary, None)
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "success"})
        return BackupResult(job.id, job.method.value, "success", summary, None, None, updated)

    # Portable copy atomicity: move the staged tree into the real destination.
    if staging_dest is not None:
        dest_path = Path(dest)
        try:
            if dest_path.exists():
                shutil.rmtree(dest_path, ignore_errors=True)
            shutil.move(str(staging_dest), str(dest_path))
        except OSError as exc:
            # e.g. destination is an existing file -> cannot move a dir onto it.
            if staging_dest.exists():
                shutil.rmtree(staging_dest, ignore_errors=True)
            if logger is not None:
                logger.log("error", {"job_id": job.id, "error": str(exc)})
            _terminal(PHASE_FAILED, STATUS_FAILED)
            _record_history("failed", {}, str(exc))
            updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "failed"})
            return BackupResult(job.id, job.method.value, "failed", {}, None, str(exc), updated)

    _terminal(PHASE_DONE, STATUS_SUCCESS)

    # For archive methods `out` is a path; for copy it is the summary dict.
    archive_out = out if job.method != BackupMethod.COPY else None
    _record_history("success", summary, None, archive_out)

    if portable:
        # Config-free mode: no manifest/log persistence.
        updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": status})
        return BackupResult(job.id, job.method.value, status, summary, None, None, updated)

    manifest = {
        "job_id": job.id,
        "source": job.source,
        "destination": dest,
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
