"""Validation for adding a backup job (pure, testable)."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from abackup.core.paths import is_inside

logger = logging.getLogger(__name__)


def estimate_source_bytes(source: str | Path) -> int:
    """Sum the sizes of every regular file under ``source``."""
    src = Path(source)
    total = 0
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        try:
            total += p.stat().st_size
        except OSError as exc:
            # Unreadable file: ignore for the estimate; the copy step will
            # surface it as a per-file failure.
            logger.warning("skipping unreadable file %s: %s", p, exc)
    return total


def validate_add_job(
    source: str | Path,
    destination: str | Path,
    *,
    margin: float = 0.1,
    disk_free=None,
) -> list[str]:
    """Validate an add-job request; return a list of human-readable errors.

    An empty list means the request is valid. Checks, in order:
      1. source exists and is a directory,
      2. destination is provided,
      3. destination is not the source or inside it,
      4. destination is creatable/writable,
      5. there is enough free space on the destination (with a safety margin).

    Validation is pure: it never creates the destination directory (the caller
    does that after a successful validation). ``disk_free`` is injectable
    (defaults to ``shutil.disk_usage``) so tests can simulate full / large
    disks deterministically.
    """
    errors: list[str] = []
    src = Path(source)
    if not source or not src.exists() or not src.is_dir():
        return ["Source must be an existing folder."]

    if not destination:
        return ["Destination is required."]

    if is_inside(destination, source):
        return ["Destination must not be the source or inside it."]

    dst = Path(destination)
    # Pure check: verify the destination is creatable/writable WITHOUT creating
    # it, so validation stays side-effect free (the caller creates it later).
    if dst.exists():
        if not dst.is_dir():
            return ["Destination must be a folder."]
        if not os.access(dst, os.W_OK):
            return ["Cannot write to destination folder."]
    else:
        parent = dst.parent
        if not parent.is_dir():
            return ["Cannot create destination folder (parent does not exist)."]
        if not os.access(parent, os.W_OK):
            return ["Cannot create destination folder (parent not writable)."]

    needed = estimate_source_bytes(src)
    free_fn = disk_free or shutil.disk_usage
    volume = dst if dst.exists() else dst.parent
    try:
        free = free_fn(volume).free
    except OSError:
        # If we cannot stat the destination volume, don't block the user.
        return errors

    if needed > free * (1 - margin):
        needed_mb = needed / (1024 * 1024)
        free_mb = free / (1024 * 1024)
        errors.append(f"Not enough free space on destination: need ~{needed_mb:.1f} MB, have ~{free_mb:.1f} MB.")
    return errors
