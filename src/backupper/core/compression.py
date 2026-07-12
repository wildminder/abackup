"""Archive engine selection: prefer 7-Zip when available, else stdlib zipfile.

``make_archive`` is the single entry point used by the backup orchestrator. It
detects an installed 7-Zip binary (``find_7z``) and, when allowed, shells out to
it for better compression (LZMA2) and speed (multithreaded). If 7z is missing or
disabled, it falls back to the deterministic stdlib ``make_zip``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

from abackup.core.archive import make_zip
from abackup.core.paths import safe_archive_name
from abackup.core.progress import (
    Progress,
    PHASE_ZIPPING,
    PHASE_DONE,
    STATUS_SUCCESS,
    OptionalProgressCallback,
)
from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled

# Common install locations checked when the binary is not on PATH.
_COMMON_7Z_PATHS = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    "/opt/homebrew/bin/7z",
    "/usr/local/bin/7z",
    "/usr/bin/7z",
]


def find_7z() -> str | None:
    """Return the path to a 7-Zip binary, or ``None`` if not installed."""
    for name in ("7z", "7za", "7zr"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _COMMON_7Z_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def make_archive(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
    compress_level: int = 6,
    cancel=None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    prefer_7z: bool = True,
) -> Path:
    """Create an archive of ``source`` in ``destination``.

    Uses 7-Zip (producing a ``.7z``) when ``prefer_7z`` is set and a binary is
    detected; otherwise falls back to the deterministic stdlib ``.zip``.
    """
    if prefer_7z and find_7z():
        return make_7z(
            source,
            destination,
            when=when,
            compress_level=compress_level,
            cancel=cancel,
            job_id=job_id,
            on_progress=on_progress,
        )
    return make_zip(
        source,
        destination,
        when=when,
        compress_level=compress_level,
        cancel=cancel,
        job_id=job_id,
        on_progress=on_progress,
    )


def make_7z(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
    compress_level: int = 6,
    cancel=None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
) -> Path:
    """Create ``<source_name>_<YYYY-MM-DD>.7z`` in ``destination`` via 7-Zip.

    Pre-scans the source for totals and emits a start ``Progress`` snapshot plus
    a completion snapshot (the 7z binary does not easily expose per-chunk bytes,
    so the bar moves start -> done). ``cancel`` terminates the subprocess.
    """
    src = Path(source)
    dst = Path(destination)
    if not src.exists() or not src.is_dir():
        raise SourceNotFound(f"Source directory not found: {src}")
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationError(f"Cannot create destination {dst}: {exc}") from exc

    name = safe_archive_name(src.name or "backup", when, ext=".7z")
    final = dst / name
    fd, tmp = tempfile.mkstemp(dir=str(dst), suffix=".tmp")
    os.close(fd)
    try:
        files = sorted(
            (p for p in src.rglob("*") if p.is_file()), key=lambda p: p.as_posix()
        )
        total = len(files)
        bytes_total = sum(f.stat().st_size for f in files)

        if on_progress is not None:
            on_progress(
                Progress(
                    job_id=job_id,
                    files_total=total,
                    files_done=0,
                    bytes_total=bytes_total,
                    bytes_done=0,
                    phase=PHASE_ZIPPING,
                )
            )

        exe = find_7z()
        if exe is None:
            # Should not happen (make_archive guards this), but stay safe.
            raise DestinationError("7-Zip binary not found")
        cmd = [exe, "a", "-y", "-t7z", f"-mx{compress_level}", tmp, "."]
        proc = subprocess.Popen(
            cmd,
            cwd=str(src),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Poll for cancellation so a batch can be aborted promptly.
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise JobCancelled("7z cancelled")
            time.sleep(0.05)

        if proc.returncode != 0:
            raise DestinationError(f"7z failed with exit code {proc.returncode}")

        os.replace(tmp, final)

        if on_progress is not None:
            on_progress(
                Progress(
                    job_id=job_id,
                    files_total=total,
                    files_done=total,
                    bytes_total=bytes_total,
                    bytes_done=bytes_total,
                    phase=PHASE_DONE,
                    status=STATUS_SUCCESS,
                )
            )
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return final
