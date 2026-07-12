"""Structured run logging (JSON lines, atomic append)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RunLogger:
    """Appends JSON-line records to ``<data_dir>/logs/<job_id>.jsonl``."""

    def __init__(self, data_dir: str | Path, job_id: str) -> None:
        self.path = Path(data_dir) / "logs" / f"{job_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, record: dict[str, Any]) -> None:
        entry = {"level": level, **record}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
