"""Atomic persistence for settings and jobs (JSON, temp + os.replace)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from abackup.core.paths import (
    get_config_dir,
    ensure_dir,
    settings_file_path,
    jobs_file_path,
)
from abackup.models import Settings, BackupJob
from abackup.utils.errors import ConfigError


def _atomic_write(path: Path, data: Any) -> None:
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_settings(config_dir: str | Path | None = None) -> Settings:
    config_dir = get_config_dir(config_dir)
    path = settings_file_path(config_dir)
    if not path.exists():
        return Settings()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return Settings.from_dict(json.load(f))
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"Failed to read settings at {path}: {exc}") from exc


def save_settings(settings: Settings, config_dir: str | Path | None = None) -> Path:
    config_dir = get_config_dir(config_dir)
    path = settings_file_path(config_dir)
    _atomic_write(path, settings.to_dict())
    return path


def load_jobs(config_dir: str | Path | None = None) -> list[BackupJob]:
    config_dir = get_config_dir(config_dir)
    path = jobs_file_path(config_dir)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [BackupJob.from_dict(item) for item in raw]
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"Failed to read jobs at {path}: {exc}") from exc


def save_jobs(jobs: list[BackupJob], config_dir: str | Path | None = None) -> Path:
    config_dir = get_config_dir(config_dir)
    path = jobs_file_path(config_dir)
    _atomic_write(path, [j.to_dict() for j in jobs])
    return path


def init_storage(config_dir: str | Path | None = None) -> Path:
    """Ensure config dir + default settings exist. Returns config dir."""
    config_dir = get_config_dir(config_dir)
    ensure_dir(config_dir)
    if not settings_file_path(config_dir).exists():
        save_settings(Settings(), config_dir)
    return config_dir
