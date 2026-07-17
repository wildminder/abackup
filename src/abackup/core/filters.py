"""Include/exclude glob filtering for backup sources (pure, deterministic)."""

from __future__ import annotations

import fnmatch
from pathlib import Path


def _matches_any(rel: Path, patterns: list[str]) -> bool:
    """Return True if ``rel`` matches any of the glob ``patterns``.

    A pattern matches when it matches the full relative path, the basename, or
    any of its path segments (so directory-style patterns like ``__pycache__``
    or ``node_modules`` skip the whole subtree).
    """
    rel_str = rel.as_posix()
    parts = rel.parts
    basename = parts[-1] if parts else ""
    for pat in patterns:
        if fnmatch.fnmatch(rel_str, pat):
            return True
        # A bare pattern like "*.txt" should match the basename too.
        if fnmatch.fnmatch(basename, pat):
            return True
        # Also match against each ancestor segment so a directory pattern
        # (e.g. "node_modules" or "node_modules/*") excludes everything under it.
        for i in range(1, len(parts) + 1):
            if fnmatch.fnmatch("/".join(parts[:i]), pat):
                return True
    return False


def should_skip(rel_path: str | Path, exclude: list[str], include: list[str]) -> bool:
    """Decide whether a relative path should be skipped during a backup.

    Rules (applied in this order):
      1. If ``include`` is non-empty, a path is skipped unless it matches at
         least one include pattern (or is a descendant of a matched directory).
      2. A path is skipped if it matches any ``exclude`` pattern.

    With empty ``include`` and empty ``exclude`` nothing is skipped.
    """
    rel = Path(rel_path)
    if include:
        if not _matches_any(rel, include):
            return True
    if _matches_any(rel, exclude):
        return True
    return False
