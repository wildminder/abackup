"""Append-only per-job run history store (RM-06).

Each job accumulates one JSON-line record per execution under
``<data_dir>/history/<job_id>.jsonl``. Unlike the per-run manifest
(``<data_dir>/manifests/<job_id>.json``, overwritten each run), this log is
*append-only* so the full run timeline survives. All writes are atomic
(temp file + ``os.replace``) and every function is pure w.r.t. the clock
(injected via the caller).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Reuse the same namespace as models.py so ids are deterministic (uuid5).
NAMESPACE = uuid.UUID("b3a1f2c4-0000-4000-8000-000000000001")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunHistoryEntry:
    """One recorded execution of a backup job."""

    job_id: str
    run_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    files_total: int
    files_done: int
    bytes_total: int
    bytes_done: int
    archive_size: int | None
    status: str
    method: str
    error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunHistoryEntry:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _history_path(data_dir: str | Path, job_id: str) -> Path:
    return Path(data_dir) / "history" / f"{job_id}.jsonl"


def _make_run_id(job_id: str, started_at: str) -> str:
    return uuid.uuid5(NAMESPACE, f"{job_id}|{started_at}").hex


def append_run(data_dir: str | Path, entry: RunHistoryEntry) -> Path:
    """Atomically append ``entry`` as one JSON line; returns the history file path.

    The append is atomic (temp file + ``os.replace``) and preserves prior lines:
    the temp file is seeded with the existing content before the new line is added,
    so a crash mid-write never truncates history.
    """
    path = _history_path(data_dir, entry.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(existing + line)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def load_history(data_dir: str | Path, job_id: str) -> list[RunHistoryEntry]:
    """Return all runs for ``job_id`` in chronological order (oldest first)."""
    path = _history_path(data_dir, job_id)
    if not path.exists():
        return []
    entries: list[RunHistoryEntry] = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(RunHistoryEntry.from_dict(json.loads(raw)))
            except (json.JSONDecodeError, TypeError, ValueError):
                # Skip a malformed line rather than crashing history display.
                continue
    return entries


def load_all_history(data_dir: str | Path) -> dict[str, list[RunHistoryEntry]]:
    """Return ``{job_id: [entries...]}`` for every history file present."""
    root = Path(data_dir) / "history"
    if not root.is_dir():
        return {}
    result: dict[str, list[RunHistoryEntry]] = {}
    for path in sorted(root.glob("*.jsonl")):
        job_id = path.stem
        result[job_id] = load_history(data_dir, job_id)
    return result
