"""Data models: Settings, BackupJob, BackupMethod."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from abackup.utils.errors import ConfigError

# Fixed namespace so IDs are deterministic (uuid5) rather than random (uuid4).
NAMESPACE = uuid.UUID("b3a1f2c4-0000-4000-8000-000000000001")


class BackupMethod(str, Enum):
    COPY = "copy"
    ZIP = "zip"

    @classmethod
    def from_str(cls, value: str) -> "BackupMethod":
        try:
            return cls(value)
        except ValueError as exc:
            raise ConfigError(f"Invalid backup method: {value!r}") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Settings:
    schema_version: int = 1
    default_destination: str | None = None
    log_level: str = "INFO"
    max_workers: int = 4
    zip_compression_level: int = 6
    created_at: str = field(default_factory=lambda: _now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def validate(self) -> None:
        """Raise ``ConfigError`` if any field is out of its valid range."""
        if not (0 <= self.zip_compression_level <= 9):
            raise ConfigError("zip_compression_level must be between 0 and 9")
        if self.max_workers < 1:
            raise ConfigError("max_workers must be >= 1")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ConfigError("log_level must be one of DEBUG/INFO/WARNING/ERROR")


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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["method"] = self.method.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackupJob":
        data = dict(data)
        data["method"] = BackupMethod.from_str(data.get("method", "copy"))
        return cls(**data)
