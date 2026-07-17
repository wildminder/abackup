"""Multithreaded batch runner: run many backup jobs via a queue + worker pool."""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from abackup.config import load_jobs, load_settings, save_jobs
from abackup.core.backup import BackupResult, run_job
from abackup.core.jobs import upsert_job
from abackup.core.notify import beep, notify
from abackup.core.progress import PHASE_CANCELLED, STATUS_CANCELLED, Progress
from abackup.models import BackupJob

# Signature: on_job_done(job_id, result)
JobDoneFn = Callable[[str, BackupResult], None]
# Signature: on_progress(job_id, progress_snapshot)
JobProgressFn = Callable[[str, Progress], None]
# Signature: clock() -> current timestamp (injectable for testing)
ClockFn = Callable[[], datetime]


def _cancelled_result(job: BackupJob, clock: ClockFn) -> BackupResult:
    """Build a 'cancelled' result (with an updated job) for a job that did not run."""
    updated = BackupJob(**{**job.to_dict(), "last_run_at": clock().isoformat(), "last_status": "cancelled"})
    return BackupResult(job.id, job.method.value, "cancelled", {}, None, "cancelled", updated)


def run_jobs_batch(
    jobs: list[BackupJob],
    *,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    max_workers: int = 4,
    on_job_done: JobDoneFn | None = None,
    on_progress: JobProgressFn | None = None,
    clock: ClockFn | None = None,
    zip_compression_level: int | None = None,
    seven_zip_compression_level: int | None = None,
    prefer_py7zr: bool | None = None,
    cancel: threading.Event | None = None,
    run_mode: str | None = None,
    dry_run: bool = False,
    notify_on_finish: bool = False,
    sound_on_failure: bool = False,
) -> list[BackupResult]:
    """Run every job using a bounded worker-thread pool + queue (or sequentially).

    Jobs are enqueued and consumed by ``min(max_workers, len(jobs))`` worker
    threads (at least one). Each worker persists its own ``updated_job`` under a
    lock (so ``jobs.json`` is never corrupted) and invokes ``on_job_done``.
    Results are returned in the original input order for determinism.

    If ``cancel`` (a ``threading.Event``) is set, queued-but-not-started jobs are
    marked ``cancelled`` and in-flight jobs abort at the next cancellation check
    inside the copy/zip routines.

    When ``run_mode == "sequential"`` (or ``max_workers == 1``), jobs run one by
    one in input order on the calling thread (no worker pool). When ``dry_run``
    is True, jobs are planned but not written.
    """
    if not jobs:
        return []

    if clock is None:
        clock = datetime.now
    settings = load_settings(config_dir)
    if zip_compression_level is None:
        zip_compression_level = settings.zip_compression_level
    if prefer_py7zr is None:
        prefer_py7zr = settings.prefer_py7zr
    if seven_zip_compression_level is None:
        seven_zip_compression_level = settings.seven_zip_compression_level
    if run_mode is None:
        run_mode = settings.run_mode

    order = [j.id for j in jobs]
    results: dict[str, BackupResult] = {}
    lock = threading.Lock()

    # Cap 7z threads so concurrent 7z jobs don't oversubscribe the CPU (NTH-005).
    # Single-worker runs keep seven_zip_threads=None so 7z uses all cores (fast path).
    cpu = os.cpu_count() or 1
    n_workers_for_threads = max(1, min(max_workers, len(jobs))) if run_mode != "sequential" else 1
    seven_zip_threads = max(1, cpu // n_workers_for_threads) if n_workers_for_threads > 1 else None

    def _run_one(job: BackupJob) -> BackupResult:
        return run_job(
            job,
            config_dir=config_dir,
            data_dir=data_dir,
            clock=clock,
            zip_compression_level=zip_compression_level,
            seven_zip_compression_level=seven_zip_compression_level,
            prefer_py7zr=prefer_py7zr,
            threads=seven_zip_threads,
            cancel=cancel,
            dry_run=dry_run,
            on_progress=((lambda p, _job=job: on_progress(_job.id, p)) if on_progress else None),
        )

    def _persist(result: BackupResult) -> None:
        if result.updated_job is not None:
            with lock:
                current = load_jobs(config_dir)
                save_jobs(upsert_job(current, result.updated_job), config_dir)

    # Sequential mode: run on the calling thread, in order, no pool.
    if run_mode == "sequential" or max_workers <= 1:
        for job in jobs:
            if cancel is not None and cancel.is_set():
                results[job.id] = _cancelled_result(job, clock)
                if on_job_done is not None:
                    on_job_done(job.id, results[job.id])
                continue
            result = _run_one(job)
            results[job.id] = result
            _persist(result)
            if on_job_done is not None:
                on_job_done(job.id, result)
    else:
        # Parallel mode: bounded worker pool + queue.
        q: queue.Queue[BackupJob | None] = queue.Queue()
        for job in jobs:
            q.put(job)

        lock = threading.Lock()

        def worker() -> None:
            while True:
                try:
                    job = q.get_nowait()
                except queue.Empty:
                    return
                # A job that hasn't started yet should not run once cancellation
                # has been requested.
                if cancel is not None and cancel.is_set():
                    results[job.id] = _cancelled_result(job, clock)
                    if on_job_done is not None:
                        on_job_done(job.id, results[job.id])
                    if on_progress is not None:
                        on_progress(
                            job.id,
                            Progress(
                                job_id=job.id,
                                phase=PHASE_CANCELLED,
                                status=STATUS_CANCELLED,
                            ),
                        )
                    q.task_done()
                    continue
                try:
                    result = _run_one(job)
                    _persist(result)
                    results[job.id] = result
                    if on_job_done is not None:
                        on_job_done(job.id, result)
                finally:
                    q.task_done()

        n_workers = max(1, min(max_workers, len(jobs)))
        threads = [threading.Thread(target=worker, name=f"backup-worker-{i}", daemon=True) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # RM-08 / RM-09: notify on completion, beep on any failure (best-effort).
    ordered = [results[jid] for jid in order]
    if not dry_run:
        failed = sum(1 for r in ordered if r.status == "failed")
        if failed > 0 and sound_on_failure:
            beep()
        if notify_on_finish:
            success = sum(1 for r in ordered if r.status == "success")
            cancelled = sum(1 for r in ordered if r.status == "cancelled")
            notify(
                "abackup",
                f"Completed {len(ordered)} jobs: {success} success, {failed} failed, {cancelled} cancelled.",
            )
    return ordered
