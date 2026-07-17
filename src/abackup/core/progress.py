"""Realtime progress carrier shared by core backup routines and the TUI.

A single immutable :class:`Progress` snapshot is emitted by the copy/zip
routines (and forwarded by the batch runner) so consumers can render a smooth,
byte-accurate progress bar plus file-level context. Keeping it frozen makes it
safe to hand the same snapshot across threads without accidental mutation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Phases a job moves through.
PHASE_PENDING = "pending"
PHASE_SCANNING = "scanning"
PHASE_COPYING = "copying"
PHASE_ZIPPING = "zipping"
PHASE_DONE = "done"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"

# Terminal statuses.
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True)
class Progress:
    """Immutable snapshot of a job's backup progress.

    ``bytes_total``/``bytes_done`` drive the primary (smooth) bar; when sizes
    are unknown/zero we fall back to the file ratio so the bar still moves.
    """

    job_id: str = ""
    files_total: int = 0
    files_done: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    current_file: str = ""
    phase: str = PHASE_PENDING
    status: str = STATUS_RUNNING

    def fraction(self) -> float:
        if self.bytes_total > 0:
            return min(1.0, self.bytes_done / self.bytes_total)
        if self.files_total > 0:
            return min(1.0, self.files_done / self.files_total)
        return 1.0

    def percent(self) -> int:
        return int(self.fraction() * 100)


ProgressCallback = Callable[["Progress"], None]
OptionalProgressCallback = ProgressCallback | None
