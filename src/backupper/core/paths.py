"""Path & directory resolution helpers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import platformdirs

_UNSAFE = re.compile(r"[^\w.\-]+")


def get_config_dir(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("abackup", "abackup"))


def get_data_dir(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("abackup", "abackup"))


def ensure_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents) if missing. Idempotent."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_archive_name(source_name: str, when: date | None = None) -> str:
    """Deterministic archive name: ``<source>_<YYYY-MM-DD>.zip``.

    Unsafe characters are replaced with underscores; falls back to ``backup``.
    """
    when = when or date.today()
    base = _UNSAFE.sub("_", source_name).strip("_") or "backup"
    return f"{base}_{when.isoformat()}.zip"


def settings_file_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "settings.json"


def jobs_file_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "jobs.json"
