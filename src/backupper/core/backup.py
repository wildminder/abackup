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
from abackup.models import BackupJob, BackupMethod
from abackup.utils.errors import SourceNotFound, DestinationError
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
) -> BackupResult:
    """Run a single backup job.

    Writes a run manifest + log under the data dir, and returns an updated
    ``BackupJob`` (with ``last_run_at``/``last_status``) for the caller to
    persist. Does NOT mutate the jobs config itself.
    """
    clock = clock or _now
    data_dir = get_data_dir(data_dir)
    ensure_dir(Path(data_dir) / "manifests")
    ensure_dir(Path(data_dir) / "logs")
    logger = RunLogger(data_dir, job.id)

    try:
        if job.method == BackupMethod.ZIP:
            out = make_zip(
                job.source, job.destination, compress_level=zip_compression_level
            )
            summary: dict = {"archive": str(out)}
        else:
            summary = copy_tree(job.source, job.destination, on_progress=on_progress)
        status = "success"
    except (SourceNotFound, DestinationError) as exc:
        logger.log("error", {"job_id": job.id, "error": str(exc)})
        updated = BackupJob(
            **{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "failed"}
        )
        return BackupResult(job.id, job.method.value, "failed", {}, None, str(exc), updated)

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
