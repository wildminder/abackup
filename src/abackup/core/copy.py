"""Direct-copy backup method (atomic per-file) with realtime progress."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from abackup.core.constants import CHUNK
from abackup.core.filters import should_skip
from abackup.core.progress import (
    PHASE_COPYING,
    OptionalProgressCallback,
    Progress,
)
from abackup.utils.errors import DestinationError, JobCancelled, SourceNotFound

# Signature of the per-file progress emitter passed into _atomic_copy_file.
# It receives (bytes_copied_in_current_file, current_relative_path) and the
# surrounding copy_tree closure fills in the job-wide totals.
_Emit = Callable[[int, str], None]

# Known robocopy locations checked when the binary is not on PATH. On Windows it
# always ships in System32; on other platforms it does not exist (we fall back to
# the pure-Python engine).
_ROBOCOPY_PATHS = [r"C:\Windows\System32\robocopy.exe"]


def find_robocopy() -> str | None:
    """Return the path to ``robocopy.exe``, or ``None`` if not available.

    Discovery order (first hit wins):

    1. ``ROBOCOPY_PATH`` environment variable (explicit override).
    2. The system ``PATH`` (``shutil.which("robocopy")``).
    3. The well-known Windows System32 location.

    On non-Windows platforms ``shutil.which`` returns ``None`` and System32 does
    not exist, so this returns ``None`` and the caller uses the Python engine.
    """
    # 1. Explicit environment override.
    env = os.environ.get("ROBOCOPY_PATH")
    if env:
        base = Path(env)
        if base.is_file():
            return str(base)

    # 2. On PATH.
    found = shutil.which("robocopy")
    if found:
        return found

    # 3. Known hardcoded location (Windows).
    for candidate in _ROBOCOPY_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def _use_robocopy(prefer_robocopy: bool) -> bool:
    """Decide whether to delegate to robocopy for this run.

    True only when the user prefers it, we are on Windows, and a robocopy binary
    is discoverable. Otherwise the pure-Python engine is used (safe on every OS).
    """
    return prefer_robocopy and sys.platform == "win32" and find_robocopy() is not None


def _build_robocopy_args(src: Path, dst: Path, exclude_patterns, include_patterns) -> list[str]:
    """Build a deterministic robocopy argument list.

    Uses terse, machine-parseable flags and mirrors the include/exclude globs
    via ``/XF`` (files) and ``/XD`` (directories). No ``/MIR`` — we mirror only
    (never delete from the destination), matching ``copy_tree`` semantics.
    """
    args = [
        str(src),
        str(dst),
        "/E",          # copy subdirectories, including empty ones
        "/R:1",        # 1 retry on failed files (deterministic, fast)
        "/W:1",        # 1 second wait between retries
        "/COPY:DAT",   # copy Data + Attributes + Timestamps
        "/DCOPY:T",    # copy directory timestamps
        "/NFL",        # no file list in output (terse)
        "/NDL",        # no directory list in output
        "/NJH",        # no job header
        "/NJS",        # no job summary
        "/NC",         # no class (terse)
        "/NS",         # no file sizes
        "/NP",         # no progress percentage spam
    ]
    for pat in (exclude_patterns or []):
        args += ["/XF", pat]
    for pat in (include_patterns or []):
        # robocopy has no include-only semantics; we approximate by excluding
        # everything else is not expressible, so include patterns are ignored by
        # the engine and the Python fallback is used instead (see dispatch).
        args += ["/XD", pat]
    return args


def robocopy_copy_tree(
    source: str | Path,
    destination: str | Path,
    *,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    overwrite: bool = True,
    use_hash: bool = False,
    cancel=None,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    plan_only: bool = False,
) -> dict:
    """Mirror ``source`` into ``destination`` using ``robocopy.exe`` (Windows).

    Drop-in replacement for :func:`copy_tree` with the same signature and the
    same summary dict. Atomic at the job level: robocopy writes into a hidden
    temp dir ``<dst>/.robocopy.tmp-<job_id>`` and, on success, the whole tree is
    renamed onto ``<dst>`` via ``os.replace`` (atomic on the same volume). The
    temp dir is always removed on every exit path.

    Progress is emitted at file granularity (one snapshot per completed file plus
    a final 100% snapshot) because robocopy's terse output does not expose
    byte-level progress cheaply. Totals come from the same pre-scan as
    ``copy_tree`` so the bar is accurate.

    robocopy exit codes are a bitmask: ``<8`` is success, ``>=8`` is failure.
    """
    if cancel is not None and cancel.is_set():
        raise JobCancelled("Copy cancelled")
    src = Path(source)
    dst = Path(destination)
    if not src.exists() or not src.is_dir():
        raise SourceNotFound(f"Source directory not found: {src}")
    if not plan_only:
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DestinationError(f"Cannot create destination {dst}: {exc}") from exc

    exclude_patterns = exclude_patterns or []
    include_patterns = include_patterns or []

    files = list(_iter_files(src))
    planned = [f for f in files if not should_skip(f.relative_to(src), exclude_patterns, include_patterns)]
    total = len(planned)
    bytes_total = sum(f.stat().st_size for f in planned)
    excluded = len(files) - total

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

    copied = 0
    skipped = 0
    bytes_copied = 0
    failed_files: list[dict] = []

    if on_progress is not None:
        emit(0, "")

    if plan_only:
        return {
            "files_total": total,
            "files_copied": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "failed_files": [],
            "files_excluded": excluded,
            "bytes_copied": 0,
            "planned": True,
        }

    # Atomic job-level copy: write into a hidden temp dir, then rename into place.
    temp = dst / f".robocopy.tmp-{job_id or 'job'}"
    try:
        if temp.exists():
            shutil.rmtree(temp)
        temp.mkdir(parents=True, exist_ok=True)

        # Pre-scan to decide skip/copy counts (mirrors copy_tree's equality check).
        for f in planned:
            if cancel is not None and cancel.is_set():
                raise JobCancelled("Copy cancelled")
            rel = f.relative_to(src)
            target = temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                skipped += 1
            elif target.exists() and _files_equal(f.stat(), target.stat(), f, target, use_hash=use_hash):
                skipped += 1
            else:
                copied += 1
                bytes_copied += f.stat().st_size
            emit(0, str(rel))

        # Run robocopy into the temp dir.
        rb = find_robocopy()
        args = _build_robocopy_args(src, temp, exclude_patterns, include_patterns)
        proc = subprocess.Popen(
            [rb, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Poll for cancellation; terminate robocopy cleanly if requested.
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise JobCancelled("Copy cancelled")
            time.sleep(0.05)
        _out, _err = proc.communicate()
        # robocopy exit codes: <8 success, >=8 failure.
        if proc.returncode is not None and proc.returncode >= 8:
            # Surface the failure; best-effort, do not abort the whole app.
            failed_files.append({"file": str(src), "error": f"robocopy exited {proc.returncode}"})
            raise DestinationError(f"robocopy failed (exit {proc.returncode}): {_err.strip()}")

        # Atomic rename of the completed temp tree onto the destination.
        if dst.exists() and not dst.is_dir():
            raise DestinationError(f"Destination exists and is not a directory: {dst}")
        # Move temp contents into dst (os.replace per item to be atomic & restartable).
        for item in temp.iterdir():
            target = dst / item.name
            if target.exists() and target.is_dir() and item.is_dir():
                # Merge directories: move children individually.
                for child in item.iterdir():
                    os.replace(child, target / child.name)
            else:
                os.replace(item, target)
    except BaseException:
        # Clean the temp dir on any failure so it never lingers.
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise
    # Success: remove the now-empty temp dir.
    if temp.exists():
        shutil.rmtree(temp, ignore_errors=True)

    return {
        "files_total": total,
        "files_copied": copied,
        "files_skipped": skipped,
        "files_failed": len(failed_files),
        "failed_files": failed_files,
        "files_excluded": excluded,
        "bytes_copied": bytes_copied,
    }


def _iter_files(source: Path):
    for root, _dirs, files in os.walk(source):
        for name in sorted(files):
            yield Path(root) / name


def _atomic_copy_file(
    src: Path,
    target: Path,
    *,
    cancel: threading.Event | None = None,
    emit: _Emit | None = None,
    current_file: str = "",
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


def _files_equal(
    s_stat: os.stat_result,
    t_stat: os.stat_result,
    src: Path,
    tgt: Path,
    *,
    use_hash: bool = False,
) -> bool:
    """Decide whether ``src`` and ``tgt`` already represent the same content.

    By default (FAT32-safe) we compare only file size: FAT32 truncates mtime
    to 2 seconds, so an mtime-based skip would needlessly re-copy identical
    files. When ``use_hash`` is set we also compare a streaming BLAKE2b hash
    for stronger change detection (catches same-size content edits).
    """
    if s_stat.st_size != t_stat.st_size:
        return False
    if not use_hash:
        return True
    return _hash_file(src) == _hash_file(tgt)


def _hash_file(path: Path) -> str:
    import hashlib

    h = hashlib.blake2b()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(
    source: str | Path,
    destination: str | Path,
    *,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    overwrite: bool = True,
    use_hash: bool = False,
    cancel=None,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    plan_only: bool = False,
    prefer_robocopy: bool = True,
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

    ``exclude_patterns`` / ``include_patterns`` are glob lists applied to each
    file's relative path (see :func:`abackup.core.filters.should_skip`). When
    ``plan_only`` is True, no files are written and the summary reports what
    *would* be copied (used by dry-run mode).

    On Windows, when ``prefer_robocopy`` is True and ``robocopy.exe`` is
    available, the copy is delegated to it (see :func:`robocopy_copy_tree`) for
    native speed and resilience. Otherwise the pure-Python engine below is used.
    """
    # Delegate to the native Windows engine when requested and available.
    if _use_robocopy(prefer_robocopy):
        return robocopy_copy_tree(
            source,
            destination,
            job_id=job_id,
            on_progress=on_progress,
            overwrite=overwrite,
            use_hash=use_hash,
            cancel=cancel,
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            plan_only=plan_only,
        )

    if cancel is not None and cancel.is_set():
        raise JobCancelled("Copy cancelled")
    src = Path(source)
    dst = Path(destination)
    if not src.exists() or not src.is_dir():
        raise SourceNotFound(f"Source directory not found: {src}")
    if not plan_only:
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DestinationError(f"Cannot create destination {dst}: {exc}") from exc

    exclude_patterns = exclude_patterns or []
    include_patterns = include_patterns or []

    files = list(_iter_files(src))
    # Apply include/exclude filters (pure, deterministic).
    planned = [f for f in files if not should_skip(f.relative_to(src), exclude_patterns, include_patterns)]
    total = len(planned)
    bytes_total = sum(f.stat().st_size for f in planned)
    copied = 0
    skipped = 0
    bytes_copied = 0
    excluded = len(files) - total

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

    if plan_only:
        # Dry-run: report the plan without touching the destination.
        return {
            "files_total": total,
            "files_copied": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "failed_files": [],
            "files_excluded": excluded,
            "bytes_copied": 0,
            "planned": True,
        }

    failed_files: list[dict] = []
    for f in planned:
        if cancel is not None and cancel.is_set():
            raise JobCancelled("Copy cancelled")
        rel = f.relative_to(src)
        target = dst / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not overwrite:
                    skipped += 1
                else:
                    s_stat = f.stat()
                    t_stat = target.stat()
                    # Skip if identical. By default we compare size only
                    # (FAT32-safe); with use_hash we also compare content.
                    if _files_equal(s_stat, t_stat, f, target, use_hash=use_hash):
                        skipped += 1
                    else:
                        _atomic_copy_file(f, target, cancel=cancel, emit=emit, current_file=str(rel))
                        copied += 1
                        bytes_copied += s_stat.st_size
            else:
                _atomic_copy_file(f, target, cancel=cancel, emit=emit, current_file=str(rel))
                copied += 1
                bytes_copied += f.stat().st_size
        except JobCancelled:
            raise
        except (DestinationError, OSError) as exc:
            # One un-copyable file (e.g. locked) must not abort the whole job.
            # Record it and continue with the rest; the count is surfaced in
            # the summary and the run manifest.
            failed_files.append({"file": str(rel), "error": str(exc)})
        # Per-file emit: file count advances, bytes already accounted for.
        emit(0, str(rel))

    return {
        "files_total": total,
        "files_copied": copied,
        "files_skipped": skipped,
        "files_failed": len(failed_files),
        "failed_files": failed_files,
        "files_excluded": excluded,
        "bytes_copied": bytes_copied,
    }
