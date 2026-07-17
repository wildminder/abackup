"""Structured run logging (JSON lines, atomic append)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RunLogger:
    """Appends JSON-line records to ``<data_dir>/logs/<job_id>.jsonl`` and, for
    durability, also to a single shared ``<data_dir>/logs/abackup.log`` (RM-07).

    All logs are kept under the ``logs/`` subfolder so the config/data root stays
    uncluttered and every log file lives in one place.
    """

    def __init__(self, data_dir: str | Path, job_id: str) -> None:
        self.data_dir = Path(data_dir)
        self.logs_dir = self.data_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.logs_dir / f"{job_id}.jsonl"
        self.shared_path = self.logs_dir / "abackup.log"

    def log(self, level: str, record: dict[str, Any]) -> None:
        entry = {"level": level, **record}
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
        # Persistent shared log (RM-07): best-effort, never block on failure.
        try:
            with open(self.shared_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
