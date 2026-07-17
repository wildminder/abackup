"""Data models: Settings, BackupJob, BackupMethod."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from abackup.utils.errors import ConfigError

# Fixed namespace so IDs are deterministic (uuid5) rather than random (uuid4).
NAMESPACE = uuid.UUID("b3a1f2c4-0000-4000-8000-000000000001")


class BackupMethod(str, Enum):
    COPY = "copy"
    ZIP = "zip"
    SEVEN_ZIP = "7z"

    @classmethod
    def from_str(cls, value: str) -> BackupMethod:
        try:
            return cls(value)
        except ValueError as exc:
            raise ConfigError(f"Invalid backup method: {value!r}") from exc


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Settings:
    schema_version: int = 1
    default_destination: str | None = None
    log_level: str = "INFO"
    max_workers: int = 4
    zip_compression_level: int = 6
    seven_zip_compression_level: int = 3
    prefer_py7zr: bool = False
    theme: str = "dark"
    run_mode: str = "parallel"
    run_on_startup: bool = False
    notify_on_finish: bool = False
    sound_on_failure: bool = False
    created_at: str = field(default_factory=lambda: _now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        data = dict(data)
        # Backward-compat: the old "prefer_7z" key meant "prefer 7z over zip";
        # it now controls the 7z engine (py7zr library vs system binary).
        if "prefer_7z" in data and "prefer_py7zr" not in data:
            data["prefer_py7zr"] = data.pop("prefer_7z")
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def validate(self) -> None:
        """Raise ``ConfigError`` if any field is out of its valid range."""
        if not (0 <= self.zip_compression_level <= 9):
            raise ConfigError("zip_compression_level must be between 0 and 9")
        if not (0 <= self.seven_zip_compression_level <= 9):
            raise ConfigError("seven_zip_compression_level must be between 0 and 9")
        if self.max_workers < 1:
            raise ConfigError("max_workers must be >= 1")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ConfigError("log_level must be one of DEBUG/INFO/WARNING/ERROR")
        if self.theme not in {"light", "dark"}:
            raise ConfigError("theme must be one of light/dark")
        if self.run_mode not in {"parallel", "sequential"}:
            raise ConfigError("run_mode must be one of parallel/sequential")


@dataclass
class BackupJob:
    source: str
    destination: str
    method: BackupMethod
    name: str = ""
    id: str = ""
    created_at: str = field(default_factory=lambda: _now().isoformat())
    last_run_at: str | None = None
    last_status: str | None = None
    schedule_interval_hours: int | None = None
    exclude_patterns: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    retention_count: int | None = None
    tag: str | None = None
    subfolder_stamp: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.method, str):
            self.method = BackupMethod.from_str(self.method)
        if not self.name:
            self.name = Path(self.source).name or "backup"
        if not self.id:
            self.id = self.make_id()

    def make_id(self) -> str:
        seed = f"{self.source}|{self.destination}|{self.method.value}|{self.created_at}"
        return uuid.uuid5(NAMESPACE, seed).hex

    def validate(self) -> None:
        """Raise ``ConfigError`` if any Tier-1 field is out of its valid range."""
        if self.schedule_interval_hours is not None and self.schedule_interval_hours < 1:
            raise ConfigError("schedule_interval_hours must be >= 1")
        if self.retention_count is not None and self.retention_count < 1:
            raise ConfigError("retention_count must be >= 1")
        if not isinstance(self.exclude_patterns, list) or not all(
            isinstance(p, str) for p in self.exclude_patterns
        ):
            raise ConfigError("exclude_patterns must be a list of strings")
        if not isinstance(self.include_patterns, list) or not all(
            isinstance(p, str) for p in self.include_patterns
        ):
            raise ConfigError("include_patterns must be a list of strings")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["method"] = self.method.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupJob:
        data = dict(data)
        data["method"] = BackupMethod.from_str(data.get("method", "copy"))
        return cls(**data)
