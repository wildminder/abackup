"""Multithreaded batch runner: run many backup jobs via a queue + worker pool."""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable, List, Optional

from abackup.config import load_jobs, save_jobs
from abackup.core.backup import BackupResult, run_job
from abackup.core.jobs import upsert_job
from abackup.models import BackupJob

# Signature: on_job_done(job_id, result)
ProgressFn = Callable[[str, BackupResult], None]


def run_jobs_batch(
    jobs: List[BackupJob],
    *,
    config_dir=None,
    data_dir=None,
    max_workers: int = 4,
    on_job_done: Optional[ProgressFn] = None,
    clock=None,
) -> List[BackupResult]:
    """Run every job concurrently using a bounded worker-thread pool + queue.

    Jobs are enqueued and consumed by ``min(max_workers, len(jobs))`` worker
    threads (at least one). Each worker persists its own ``updated_job`` under a
    lock (so ``jobs.json`` is never corrupted) and invokes ``on_job_done``.
    Results are returned in the original input order for determinism.
    """
    if not jobs:
        return []

    if clock is None:
        clock = datetime.now

    order = [j.id for j in jobs]
    results: dict[str, BackupResult] = {}
    q: "queue.Queue[Optional[BackupJob]]" = queue.Queue()
    for job in jobs:
        q.put(job)

    lock = threading.Lock()

    def worker() -> None:
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            try:
                result = run_job(
                    job, config_dir=config_dir, data_dir=data_dir, clock=clock
                )
                if result.updated_job is not None:
                    with lock:
                        current = load_jobs(config_dir)
                        save_jobs(upsert_job(current, result.updated_job), config_dir)
                results[job.id] = result
                if on_job_done is not None:
                    on_job_done(job.id, result)
            finally:
                q.task_done()

    n_workers = max(1, min(max_workers, len(jobs)))
    threads = [
        threading.Thread(target=worker, name=f"backup-worker-{i}", daemon=True)
        for i in range(n_workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return [results[jid] for jid in order]
