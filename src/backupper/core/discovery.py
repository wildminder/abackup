"""First-run detection (pure helpers)."""

from __future__ import annotations

from abackup.models import Settings


def is_first_run(settings: Settings) -> bool:
    return not settings.first_run_completed


def mark_first_run_done(settings: Settings) -> Settings:
    """Return a copy of ``settings`` with first-run completed."""
    return Settings(
        schema_version=settings.schema_version,
        first_run_completed=True,
        default_destination=settings.default_destination,
        log_level=settings.log_level,
        created_at=settings.created_at,
    )
