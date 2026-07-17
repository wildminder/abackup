"""Archive engine selection for the backup orchestrator.

``make_archive`` is the single entry point used by the backup orchestrator.
Engine precedence (produces a 7z archive unless no 7z engine exists, then a
deterministic ``.zip``):

1. **py7zr** (pure-Python library) — used first when ``prefer_py7zr=True``
   (the default) and the library is importable. Single-threaded and non-solid
   (per-file streams), so it is slower than the multithreaded binary for large
   trees.
2. **System 7-Zip binary** — used when ``prefer_py7zr=False`` or py7zr is
   unavailable but a ``7z``/``7za`` binary is found on PATH or in common
   install locations. Multithreaded LZMA2, so it uses all CPU cores and is
   dramatically faster than the pure-Python path (typically 5-10x).
3. **py7zr** again — fallback when the binary is absent but py7zr is present.
4. **stdlib ``zipfile``** — last resort (deterministic ``.zip``), used when no
   7z engine is available at all.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess  # noqa: B404 - used to invoke the 7-Zip binary (list args, no shell).
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

from abackup.core.archive import make_zip
from abackup.core.filters import should_skip
from abackup.core.paths import unique_archive_name
from abackup.core.progress import (
    PHASE_DONE,
    PHASE_ZIPPING,
    STATUS_SUCCESS,
    OptionalProgressCallback,
    Progress,
)
from abackup.utils.errors import DestinationError, JobCancelled, SourceNotFound

try:  # pragma: no cover - import guard; the else branch is exercised in tests
    import py7zr
except ImportError:  # pragma: no cover
    py7zr = None  # type: ignore[assignment]

try:  # Windows-only registry access; absent on other platforms.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Candidate 7-Zip executables, in preference order. ``7z.exe`` is the full
# command-line binary; ``7za``/``7zr`` are the standalone/reduced console
# builds; ``7zG.exe`` is the GUI-less build that still accepts the same CLI
# arguments (used only as a last resort to avoid popping a window).
_7Z_BINARIES = ("7z.exe", "7za.exe", "7zr.exe", "7zG.exe")

# Common install locations checked when the binary is not on PATH and not
# registered in the Windows registry.
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


def _seven_zip_registry_paths() -> list[str]:
    """Return 7-Zip install directories registered in the Windows registry.

    7-Zip records its install location under ``SOFTWARE\\7-Zip`` (value
    ``Path``) in both ``HKLM`` and ``HKCU``, plus the ``WOW6432Node`` mirror
    on 64-bit systems. Many installs (e.g. portable/custom locations such as
    ``C:\\WinApp\\Utils\\7-Zip``) are only discoverable this way -- which is
    exactly why the binary was previously missed and the app fell back to the
    slow, single-threaded py7zr library.
    """
    if winreg is None:  # pragma: no cover - non-Windows
        return []
    found: list[str] = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\7-Zip"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\7-Zip"),
    ]
    for hive, subkey in roots:
        value = None
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError as exc:
            logger.warning("7-Zip registry key absent %s\\%s: %s", hive, subkey, exc)
        if value:
            found.append(str(value))
    # De-duplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def find_7z() -> str | None:
    """Return the path to a 7-Zip binary, or ``None`` if not installed.

    Discovery order (first hit wins):

    1. ``SEVEN_ZIP_PATH`` / ``7ZIP_PATH`` environment variable (explicit override).
    2. The system ``PATH`` (``7z`` / ``7za`` / ``7zr``).
    3. The install directory recorded in the Windows registry (covers custom
       and portable installs that are not on PATH).
    4. A handful of well-known hardcoded locations.
    """
    # 1. Explicit environment override.
    env = os.environ.get("SEVEN_ZIP_PATH") or os.environ.get("7ZIP_PATH")
    if env:
        base = Path(env)
        candidates = [base] if base.is_file() else [base / name for name in _7Z_BINARIES]
        for cand in candidates:
            if cand.is_file():
                return str(cand)

    # 2. On PATH.
    for name in ("7z", "7za", "7zr"):
        found = shutil.which(name)
        if found:
            return found

    # 3. Registry-registered install directories (Windows).
    for install_dir in _seven_zip_registry_paths():
        for name in _7Z_BINARIES:
            cand = Path(install_dir) / name
            if cand.is_file():
                return str(cand)

    # 4. Common hardcoded locations.
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
    cancel: threading.Event | None = None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    prefer_py7zr: bool = False,
    threads: int | None = None,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    plan_only: bool = False,
) -> Path:
    """Create an archive of ``source`` in ``destination``.

    Produces a 7z archive. The engine is chosen by ``prefer_py7zr``:

    * ``prefer_py7zr=True`` (default) -> py7zr library (primary).
    * otherwise -> system 7-Zip binary when present, else py7zr as a fallback.
    * if no 7z engine is available at all -> stdlib ``.zip`` (safety net).

    ``exclude_patterns`` / ``include_patterns`` are glob lists applied to each
    file's relative path. When ``plan_only`` is True, no archive is written and
    a deterministic placeholder name is returned (used by dry-run mode).
    """
    if prefer_py7zr and _have_py7zr():
        return make_7z_py7zr(
            source,
            destination,
            when=when,
            compress_level=compress_level,
            cancel=cancel,
            job_id=job_id,
            on_progress=on_progress,
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            plan_only=plan_only,
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
            threads=threads,
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            plan_only=plan_only,
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
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            plan_only=plan_only,
        )
    return make_zip(
        source,
        destination,
        when=when,
        compress_level=compress_level,
        cancel=cancel,
        job_id=job_id,
        on_progress=on_progress,
        exclude_patterns=exclude_patterns,
        include_patterns=include_patterns,
        plan_only=plan_only,
    )


def make_7z_py7zr(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
    compress_level: int = 6,
    cancel: threading.Event | None = None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    plan_only: bool = False,
) -> Path:
    """Create ``<source_name>_<YYYY-MM-DD>.7z`` in ``destination`` via py7zr.

    The pure-Python py7zr library is the 7z fallback engine (used when no
    system 7-Zip binary is available). It is single-threaded and non-solid
    (one stream per file), so it is much slower than the multithreaded
    system binary for large trees -- which is why the binary is preferred by
    default. Files are written one at a time so we can emit per-file
    progress and honour cancellation between files. ``cancel`` raises
    ``JobCancelled``.
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

    exclude_patterns = exclude_patterns or []
    include_patterns = include_patterns or []

    name = unique_archive_name(src.name or "backup", when, ext=".7z", dest_dir=dst)
    final = dst / name
    fd, tmp = tempfile.mkstemp(dir=str(dst), suffix=".tmp")
    os.close(fd)
    try:
        all_files = sorted((p for p in src.rglob("*") if p.is_file()), key=lambda p: p.as_posix())
        files = [
            f
            for f in all_files
            if not should_skip(f.relative_to(src), exclude_patterns, include_patterns)
        ]
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

        if plan_only:
            # Dry-run: report the plan without writing an archive.
            return final

        # NOTE: py7zr's internal compressor (CPython lzma.LZMACompressor)
        # rejects the LZMA2 "threads" key, so py7zr is inherently
        # single-threaded. The fast multithreaded path is the system 7-Zip
        # binary, which is why make_archive prefers it by default.
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


def _poll_7z_progress(
    proc: subprocess.Popen[bytes],
    tmp: str,
    total: int,
    bytes_total: int,
    on_progress: OptionalProgressCallback,
    job_id: str,
    cancel: threading.Event | None,
    timeout: float | None,
) -> None:
    """Poll the 7z temp archive size and forward progress; honour cancel/timeout.

    Raises ``JobCancelled`` if the caller's cancel event is set, or
    ``DestinationError`` if ``timeout`` (seconds) elapses before 7z exits, so a
    wedged process cannot block the run forever.
    """
    start = time.monotonic()
    last_pct = -1
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise JobCancelled("7z cancelled")
        if timeout is not None and (time.monotonic() - start) > timeout:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise DestinationError(f"7z timed out after {timeout:g}s (job {job_id or '?'})")
        cur = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        est = max(bytes_total // 2, cur) if bytes_total else max(1, cur)
        pct = min(99, int(cur / est * 100)) if est else 0
        if pct != last_pct and on_progress is not None:
            last_pct = pct
            bytes_done = int(bytes_total * pct / 100) if bytes_total else cur
            files_done = min(total, int(round(total * pct / 100))) if total else 0
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
        time.sleep(0.05)


def make_7z(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
    compress_level: int = 6,
    cancel: threading.Event | None = None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
    threads: int | None = None,
    timeout: float | None = None,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    plan_only: bool = False,
) -> Path:
    """Create ``<source_name>_<YYYY-MM-DD>.7z`` in ``destination`` via 7-Zip.

    Fallback 7z engine used only when the py7zr library is unavailable but a
    system 7-Zip binary is present. Pre-scans the source for totals, then runs
    the binary and forwards **realtime** ``Progress`` updates.

    Progress source: 7-Zip fully *buffers* its ``-bsp2`` percentage stream when
    stderr is a pipe (non-TTY) and only flushes it at process exit, so parsing
    stderr cannot drive a live bar. Instead we poll the temp archive file's
    *size* (which grows monotonically as 7z compresses) and derive a percentage
    against an adaptive estimate of the final compressed size (seeded at 50% of
    the source bytes, grown if exceeded). This works on every platform with no
    extra dependencies and gives a smoothly moving bar. ``cancel`` terminates
    the subprocess; ``timeout`` (seconds) terminates it if exceeded, raising
    ``DestinationError`` so a wedged 7z cannot block the run forever.
    """
    src = Path(source)
    dst = Path(destination)
    if not src.exists() or not src.is_dir():
        raise SourceNotFound(f"Source directory not found: {src}")
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationError(f"Cannot create destination {dst}: {exc}") from exc

    exclude_patterns = exclude_patterns or []
    include_patterns = include_patterns or []

    name = unique_archive_name(src.name or "backup", when, ext=".7z", dest_dir=dst)
    final = dst / name
    fd, tmp = tempfile.mkstemp(dir=str(dst), suffix=".tmp")
    os.close(fd)
    # 7z's "add" mode refuses to *create* an archive over a pre-existing
    # file (it would try to append to it and fail), so discard the empty
    # placeholder that mkstemp just created; 7z will create it fresh.
    Path(tmp).unlink(missing_ok=True)
    try:
        all_files = sorted((p for p in src.rglob("*") if p.is_file()), key=lambda p: p.as_posix())
        files = [
            f
            for f in all_files
            if not should_skip(f.relative_to(src), exclude_patterns, include_patterns)
        ]
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

        if plan_only:
            # Dry-run: report the plan without writing an archive.
            return final

        exe = find_7z()
        if exe is None:
            # Should not happen (make_archive guards this), but stay safe.
            raise DestinationError("7-Zip binary not found")
        # 7-Zip buffers its -bsp2 percentage stream when stderr is a pipe
        # (non-TTY) and only flushes it at process exit, so parsing stderr
        # cannot drive a live bar. Instead we poll the temp archive file's
        # *size* (which grows monotonically as 7z compresses) and derive a
        # percentage against an adaptive estimate of the final compressed
        # size (seeded at 50% of the source bytes; grown if exceeded).
        cmd = [exe, "a", "-y", "-t7z", f"-mx{compress_level}"]
        # Cap threads so concurrent 7z jobs (run via the batch runner with
        # max_workers>1) don't oversubscribe the CPU (NTH-005). When threads is
        # None we let 7z use all cores (single-job runs stay fast).
        if threads is not None:
            cmd.append(f"-mmt{threads}")
        cmd += [tmp, "."]
        proc = subprocess.Popen(  # noqa: B603 - safe: list form (no shell); exe is a validated path, args are fixed.
            cmd,
            cwd=str(src),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        _poll_7z_progress(proc, tmp, total, bytes_total, on_progress, job_id, cancel, timeout)

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
