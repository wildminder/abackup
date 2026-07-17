"""Tests for the pure scheduler (RM-01a)."""

from datetime import UTC, datetime

from abackup.core.scheduler import due_jobs, is_due
from abackup.models import BackupJob


def _job(interval=None, last_run=None):
    return BackupJob(
        source="C:/s",
        destination="D:/d",
        method="copy",
        schedule_interval_hours=interval,
        last_run_at=last_run,
    )


def test_scheduler_no_schedule_never_due():
    assert is_due(_job(None)) is False


def test_scheduler_never_run_is_due():
    assert is_due(_job(1)) is True


def test_scheduler_not_due_before_interval():
    last = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 1, 1, 0, 30, 0, tzinfo=UTC)
    assert is_due(_job(1, last.isoformat()), now) is False


def test_scheduler_due_after_interval():
    last = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 1, 1, 2, 0, 0, tzinfo=UTC)
    assert is_due(_job(1, last.isoformat()), now) is True


def test_due_jobs_filters_list():
    a = _job(1)  # never run -> due
    b = _job(None)  # no schedule -> not due
    now = datetime(2026, 1, 1, 2, 0, 0, tzinfo=UTC)
    last = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    c = _job(1, last.isoformat())  # due
    result = due_jobs([a, b, c], now)
    assert set(j.id for j in result) == {a.id, c.id}
