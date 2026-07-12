"""Direct-copy backup method (atomic per-file)."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled

# Signature: on_progress(done, total, current_relative_path)
ProgressFn = Callable[[int, int, str], None]


def _iter_files(source: Path):
    for root, _dirs, files in os.walk(source):
        for name in sorted(files):
            yield Path(root) / name


def _atomic_copy_file(src: Path, target: Path, cancel=None) -> None:
    """Copy ``src`` to ``target`` atomically (temp file + rename), preserving mtime.

    Copies in 1 MiB chunks and checks ``cancel`` (a ``threading.Event``) between
    chunks, raising ``JobCancelled`` if it is set so a long copy is interruptible.
    """
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            while True:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled("Copy cancelled")
                chunk = inp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    s = src.stat()
    os.utime(target, (s.st_atime, s.st_mtime))


def copy_tree(
    source: str | Path,
    destination: str | Path,
    *,
    on_progress: Optional[ProgressFn] = None,
    overwrite: bool = True,
    cancel=None,
) -> dict:
    """Mirror ``source`` into ``destination``.

    Returns a summary dict. Each file is written to a temp file then atomically
    renamed into place, so a crash never leaves a half-written final file.

    If ``cancel`` (a ``threading.Event``) is set, raises ``JobCancelled`` before
    the next file (and mid-file for the in-progress copy) so a batch can be
    aborted promptly.
    """
    if cancel is not None and cancel.is_set():
        raise JobCancelled("Copy cancelled")
    src = Path(source)
    dst = Path(destination)
    if not src.exists() or not src.is_dir():
        raise SourceNotFound(f"Source directory not found: {src}")
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationError(f"Cannot create destination {dst}: {exc}") from exc

    files = list(_iter_files(src))
    total = len(files)
    copied = 0
    skipped = 0
    bytes_copied = 0

    for f in files:
        if cancel is not None and cancel.is_set():
            raise JobCancelled("Copy cancelled")
        rel = f.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not overwrite:
                skipped += 1
            else:
                s_stat = f.stat()
                t_stat = target.stat()
                # Skip if identical (size + mtime) to avoid needless rewrites.
                if s_stat.st_size == t_stat.st_size and s_stat.st_mtime == t_stat.st_mtime:
                    skipped += 1
                else:
                    _atomic_copy_file(f, target, cancel=cancel)
                    copied += 1
                    bytes_copied += s_stat.st_size
        else:
            _atomic_copy_file(f, target, cancel=cancel)
            copied += 1
            bytes_copied += f.stat().st_size
        if on_progress is not None:
            on_progress(copied + skipped, total, str(rel))

    return {
        "files_total": total,
        "files_copied": copied,
        "files_skipped": skipped,
        "bytes_copied": bytes_copied,
    }
