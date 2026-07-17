"""Retention policy: keep only the most recent N archives for a job (pure)."""

from __future__ import annotations

import os
from pathlib import Path


def _sort_key(p: Path) -> tuple:
    """Sort archives oldest-first so we can delete from the front.

    Prefer mtime; fall back to name for stable, deterministic ordering when
    mtimes are equal (e.g. archives created in the same second during tests).
    """
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (mtime, p.name)


def enforce_retention(archive_paths: list[Path], keep: int | None) -> list[Path]:
    """Delete overflow archives beyond ``keep`` (most recent kept).

    Returns the list of archives that were deleted. When ``keep`` is None all
    archives are kept (no deletion). Archives are sorted oldest-first by mtime
    (then name) so the oldest are removed first.
    """
    if keep is None or keep < 1:
        return []
    paths = [Path(p) for p in archive_paths]
    if len(paths) <= keep:
        return []
    ordered = sorted(paths, key=_sort_key)
    to_delete = ordered[: len(paths) - keep]
    deleted: list[Path] = []
    for p in to_delete:
        try:
            os.remove(p)
            deleted.append(p)
        except OSError:
            # A file we cannot remove (locked/permission) is skipped, not fatal.
            continue
    return deleted
