"""Job management: pure (immutable) CRUD operations over a job list."""

from __future__ import annotations

from typing import List

from abackup.models import BackupJob
from abackup.utils.errors import JobNotFound


def add_job(jobs: List[BackupJob], job: BackupJob) -> List[BackupJob]:
    """Append a job, or replace an existing one with the same id."""
    if any(j.id == job.id for j in jobs):
        return [job if j.id == job.id else j for j in jobs]
    return jobs + [job]


def upsert_job(jobs: List[BackupJob], job: BackupJob) -> List[BackupJob]:
    return add_job(jobs, job)


def get_job(jobs: List[BackupJob], job_id: str) -> BackupJob:
    for j in jobs:
        if j.id == job_id:
            return j
    raise JobNotFound(f"Job not found: {job_id}")


def update_job(jobs: List[BackupJob], job: BackupJob) -> List[BackupJob]:
    if not any(j.id == job.id for j in jobs):
        raise JobNotFound(f"Job not found: {job.id}")
    return [job if j.id == job.id else j for j in jobs]


def remove_job(jobs: List[BackupJob], job_id: str) -> List[BackupJob]:
    if not any(j.id == job_id for j in jobs):
        raise JobNotFound(f"Job not found: {job_id}")
    return [j for j in jobs if j.id != job_id]


def list_jobs(jobs: List[BackupJob]) -> List[BackupJob]:
    return list(jobs)
