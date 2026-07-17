"""Job management: pure (immutable) CRUD operations over a job list."""

from __future__ import annotations

from abackup.models import BackupJob
from abackup.utils.errors import JobNotFound


def add_job(jobs: list[BackupJob], job: BackupJob) -> list[BackupJob]:
    """Append a job, or replace an existing one with the same id."""
    if any(j.id == job.id for j in jobs):
        return [job if j.id == job.id else j for j in jobs]
    return jobs + [job]


def upsert_job(jobs: list[BackupJob], job: BackupJob) -> list[BackupJob]:
    """Insert or replace ``job`` by id (delegates to :func:`add_job`)."""
    return add_job(jobs, job)


def get_job(jobs: list[BackupJob], job_id: str) -> BackupJob:
    for j in jobs:
        if j.id == job_id:
            return j
    raise JobNotFound(f"Job not found: {job_id}")


def update_job(jobs: list[BackupJob], job: BackupJob) -> list[BackupJob]:
    if not any(j.id == job.id for j in jobs):
        raise JobNotFound(f"Job not found: {job.id}")
    return [job if j.id == job.id else j for j in jobs]


def remove_job(jobs: list[BackupJob], job_id: str) -> list[BackupJob]:
    if not any(j.id == job_id for j in jobs):
        raise JobNotFound(f"Job not found: {job_id}")
    return [j for j in jobs if j.id != job_id]


def list_jobs(jobs: list[BackupJob]) -> list[BackupJob]:
    return list(jobs)


def filter_by_tag(jobs: list[BackupJob], tag: str | None) -> list[BackupJob]:
    """Return jobs matching ``tag``.

    When ``tag`` is None, all jobs are returned (no filtering). When ``tag`` is
    a string, only jobs whose ``tag`` equals it are returned.
    """
    if tag is None:
        return list(jobs)
    return [j for j in jobs if j.tag == tag]
