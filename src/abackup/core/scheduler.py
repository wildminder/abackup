"""Pure scheduling helpers: decide which jobs are due to run (deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime

from abackup.models import BackupJob


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def is_due(job: BackupJob, now: datetime | None = None) -> bool:
    """Return True when ``job`` has a schedule and is due to run at ``now``.

    A job is due when:
      * it has ``schedule_interval_hours`` set, and
      * it has never run (``last_run_at`` is None), or
      * ``now - last_run_at >= schedule_interval_hours``.

    ``now`` defaults to ``datetime.now(UTC)``; inject a fixed clock in tests.
    """
    if job.schedule_interval_hours is None or job.schedule_interval_hours < 1:
        return False
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    last = _parse(job.last_run_at)
    if last is None:
        return True
    delta = now - last
    return delta.total_seconds() >= job.schedule_interval_hours * 3600


def due_jobs(jobs: list[BackupJob], now: datetime | None = None) -> list[BackupJob]:
    """Return the subset of ``jobs`` that are currently due to run."""
    return [j for j in jobs if is_due(j, now)]
