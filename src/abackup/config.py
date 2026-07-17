"""Atomic persistence for settings and jobs (JSON, temp + os.replace)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import platformdirs

from abackup.core.paths import (
    default_config_dir,
    ensure_dir,
    get_config_dir,
    get_data_dir,
    jobs_file_path,
    settings_file_path,
)
from abackup.models import BackupJob, Settings
from abackup.utils.errors import ConfigError

# Previous default location (platformdirs). Used only for one-time migration.
LEGACY_DIR = Path(platformdirs.user_config_dir("abackup", "abackup"))


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
        with open(path, encoding="utf-8") as f:
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
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return [BackupJob.from_dict(item) for item in raw]
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"Failed to read jobs at {path}: {exc}") from exc


def save_jobs(jobs: list[BackupJob], config_dir: str | Path | None = None) -> Path:
    config_dir = get_config_dir(config_dir)
    path = jobs_file_path(config_dir)
    _atomic_write(path, [j.to_dict() for j in jobs])
    return path


def relocate_storage(old_dir, new_dir) -> Path:
    """Atomically move ``settings.json`` + ``jobs.json`` from old to new dir.

    Creates the new directory and uses ``os.replace`` (atomic) for each file.
    If ``old_dir`` already equals ``new_dir`` this is a no-op. Returns the new
    config dir.
    """
    old = Path(old_dir)
    new = Path(new_dir)
    if old.resolve() == new.resolve():
        return new
    ensure_dir(new)
    for name in ("settings.json", "jobs.json"):
        src = old / name
        if src.exists():
            os.replace(src, new / name)
    return new


def relocate_data(old_data_dir, new_data_dir) -> Path:
    """Atomically move run logs + manifests from old to new data dir.

    Moves every subdirectory of ``old`` (``logs/``, ``manifests/``, and any
    future subdir) to ``new`` via ``os.replace`` (atomic). No-op if the dirs
    are equal. Returns the new data dir.
    """
    old = Path(old_data_dir)
    new = Path(new_data_dir)
    if old.resolve() == new.resolve():
        return new
    ensure_dir(new)
    new_resolved = new.resolve()
    for sub in (p for p in old.iterdir() if p.is_dir()):
        # Guard against the (unusual) case where the destination lives inside
        # the source: never try to move the destination into itself.
        if sub.resolve() == new_resolved:
            continue
        os.replace(sub, new / sub.name)
    return new


def maybe_migrate_legacy_config() -> None:
    """One-time migration from the old ``platformdirs`` location to the new
    home-based default. No-op if the new location already has settings or the
    legacy location is empty."""
    new_default = default_config_dir()
    if settings_file_path(new_default).exists():
        return
    if settings_file_path(LEGACY_DIR).exists():
        relocate_storage(LEGACY_DIR, new_default)
        # Move run history (logs/manifests) too, so it isn't orphaned.
        relocate_data(get_data_dir(), new_default)


def init_storage(config_dir: str | Path | None = None) -> Path:
    """Ensure config dir + default settings exist. Returns config dir.

    When no explicit ``config_dir`` is given, any data from the legacy
    ``platformdirs`` location is migrated to the new home-based default first.
    """
    if config_dir is None:
        maybe_migrate_legacy_config()
    config_dir = get_config_dir(config_dir)
    ensure_dir(config_dir)
    if not settings_file_path(config_dir).exists():
        save_settings(Settings(), config_dir)
    return config_dir
