"""Archive engine selection for the backup orchestrator.

``make_archive`` is the single entry point used by the backup orchestrator. When
7z output is preferred (``prefer_7z``), it uses the following precedence:

1. **py7zr** (pure-Python library) — primary. No external binary required, works
   everywhere, and lets us emit per-file progress.
2. **System 7-Zip binary** — fallback when py7zr is somehow unavailable. Shells
   out to ``7z`` for LZMA2 compression.
3. **stdlib ``zipfile``** — last resort (deterministic ``.zip``), used when 7z is
   disabled or no 7z engine is available.
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

try:  # pragma: no cover - import guard; the else branch is exercised in tests
    import py7zr
except ImportError:  # pragma: no cover
    py7zr = None  # type: ignore[assignment]

# Common install locations checked when the binary is not on PATH.
_COMMON_7Z_PATHS = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    "/opt/homebrew/bin/7z",
    "/usr/local/bin/7z",
    "/usr/bin/7z",
]


def _have_py7zr() -> bool:
    """Return ``True`` when the py7zr library is importable."""
    return py7zr is not None


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
    prefer_py7zr: bool = True,
) -> Path:
    """Create an archive of ``source`` in ``destination``.

    When ``prefer_7z`` is ``False`` (the user explicitly chose the ``.zip``
    method), always uses the deterministic stdlib ``.zip`` writer. When the user
    wants 7z (``prefer_7z=True``), the engine is chosen by ``prefer_py7zr``:

    * ``prefer_py7zr=True`` (default) -> py7zr library (primary).
    * otherwise -> system 7-Zip binary when present, else py7zr as a fallback.
    * if no 7z engine is available at all -> stdlib ``.zip`` (safety net).
    """
    if not prefer_7z:
        return make_zip(
            source,
            destination,
            when=when,
            compress_level=compress_level,
            cancel=cancel,
            job_id=job_id,
            on_progress=on_progress,
        )
    if prefer_py7zr and _have_py7zr():
        return make_7z_py7zr(
            source,
            destination,
            when=when,
            compress_level=compress_level,
            cancel=cancel,
            job_id=job_id,
            on_progress=on_progress,
        )
    if find_7z() is not None:
        return make_7z(
            source,
            destination,
            when=when,
            compress_level=compress_level,
            cancel=cancel,
            job_id=job_id,
            on_progress=on_progress,
        )
    if _have_py7zr():
        return make_7z_py7zr(
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


def make_7z_py7zr(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
    compress_level: int = 6,
    cancel=None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
) -> Path:
    """Create ``<source_name>_<YYYY-MM-DD>.7z`` in ``destination`` via py7zr.

    The pure-Python py7zr library is the primary 7z engine (no external binary
    needed). Files are written individually so we can emit per-file progress and
    honour cancellation between files. ``cancel`` raises ``JobCancelled``.
    """
    if py7zr is None:  # pragma: no cover - guarded by make_archive
        raise DestinationError("py7zr library is not available")

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

        filters = [{"id": py7zr.FILTER_LZMA2, "preset": compress_level}]
        bytes_done = 0
        files_done = 0
        with py7zr.SevenZipFile(tmp, "w", filters=filters) as zf:
            for f in files:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled("7z (py7zr) cancelled")
                rel = f.relative_to(src).as_posix()
                zf.write(str(f), arcname=rel)
                bytes_done += f.stat().st_size
                files_done += 1
                if on_progress is not None:
                    on_progress(
                        Progress(
                            job_id=job_id,
                            files_total=total,
                            files_done=files_done,
                            bytes_total=bytes_total,
                            bytes_done=bytes_done,
                            phase=PHASE_ZIPPING,
                        )
                    )

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

    Fallback 7z engine used only when the py7zr library is unavailable but a
    system 7-Zip binary is present. Pre-scans the source for totals and emits a
    start ``Progress`` snapshot plus a completion snapshot (the 7z binary does not
    easily expose per-chunk bytes, so the bar moves start -> done). ``cancel``
    terminates the subprocess.
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
