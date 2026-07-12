"""Direct-copy backup method (atomic per-file) with realtime progress."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from abackup.core.progress import (
    Progress,
    PHASE_COPYING,
    OptionalProgressCallback,
)
from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled

# Copy in 1 MiB chunks: small enough for smooth progress, large enough for throughput.
CHUNK = 1024 * 1024

# Signature of the per-file progress emitter passed into _atomic_copy_file.
# It receives (bytes_copied_in_current_file, current_relative_path) and the
# surrounding copy_tree closure fills in the job-wide totals.
_Emit = Callable[[int, str], None]


def _iter_files(source: Path):
    for root, _dirs, files in os.walk(source):
        for name in sorted(files):
            yield Path(root) / name


def _atomic_copy_file(
    src: Path, target: Path, *, cancel=None, emit: Optional[_Emit] = None, current_file: str = ""
) -> None:
    """Copy ``src`` to ``target`` atomically (temp file + rename), preserving mtime.

    Copies in 1 MiB chunks and checks ``cancel`` (a ``threading.Event``) between
    chunks, raising ``JobCancelled`` if it is set so a long copy is interruptible.
    ``emit`` is called after each chunk with the running byte count for realtime
    progress (it must be cheap and never block).
    """
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled("Copy cancelled")
                chunk = inp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if emit is not None:
                    emit(done, current_file)
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
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    overwrite: bool = True,
    cancel=None,
) -> dict:
    """Mirror ``source`` into ``destination``.

    Returns a summary dict. Each file is written to a temp file then atomically
    renamed into place, so a crash never leaves a half-written final file.

    Emits :class:`Progress` snapshots via ``on_progress``: one at start (totals
    known from a pre-scan), one per 1 MiB chunk (byte-level), and one per file
    (file-level). This gives the TUI a smooth, accurate bar.

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
    bytes_total = sum(f.stat().st_size for f in files)
    copied = 0
    skipped = 0
    bytes_copied = 0

    def emit(local_bytes: int, current_file: str) -> None:
        if on_progress is not None:
            on_progress(
                Progress(
                    job_id=job_id,
                    files_total=total,
                    files_done=copied + skipped,
                    bytes_total=bytes_total,
                    bytes_done=bytes_copied + local_bytes,
                    current_file=current_file,
                    phase=PHASE_COPYING,
                )
            )

    if on_progress is not None:
        emit(0, "")

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
                    _atomic_copy_file(f, target, cancel=cancel, emit=emit, current_file=str(rel))
                    copied += 1
                    bytes_copied += s_stat.st_size
        else:
            _atomic_copy_file(f, target, cancel=cancel, emit=emit, current_file=str(rel))
            copied += 1
            bytes_copied += f.stat().st_size
        # Per-file emit: file count advances, bytes already accounted for.
        emit(0, str(rel))

    return {
        "files_total": total,
        "files_copied": copied,
        "files_skipped": skipped,
        "bytes_copied": bytes_copied,
    }
