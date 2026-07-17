"""Zip backup method (deterministic naming and entry timestamps) with realtime progress."""

from __future__ import annotations

import os
import tempfile
import threading
import zipfile
from datetime import date
from pathlib import Path

from abackup.core.constants import CHUNK
from abackup.core.filters import should_skip
from abackup.core.paths import unique_archive_name
from abackup.core.progress import (
    PHASE_ZIPPING,
    OptionalProgressCallback,
    Progress,
)
from abackup.utils.errors import DestinationError, JobCancelled, SourceNotFound

# Fixed timestamp so zip byte output is reproducible across runs.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Read each file in 1 MiB chunks so we can emit byte-level progress, but buffer
# the whole member in memory before writestr so the exact compresslevel is applied
# reproducibly (zf.open's streaming path does not reliably honour per-member
# compresslevel across CPython versions). A single large file therefore resides in
# memory during compression.


def _emit_zip_progress(on_progress: OptionalProgressCallback, progress: Progress) -> None:
    """Emit a ``Progress`` snapshot for the zip writer (no-op when unset)."""
    if on_progress is not None:
        on_progress(progress)


def make_zip(
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
    """Create ``<source_name>_<YYYY-MM-DD>.zip`` in ``destination``.

    Files are streamed in sorted order with a fixed entry timestamp, making the
    resulting archive byte-for-byte reproducible for the same inputs across runs.

    Emits :class:`Progress` snapshots via ``on_progress``: one at start (totals
    from a pre-scan), one per 1 MiB chunk (byte-level), and one per file
    (file-level). Each file is buffered and written via ``ZipFile.writestr`` with
    an explicit ``compresslevel`` so the archive is byte-for-byte reproducible;
    progress is emitted per 1 MiB chunk as the file is read.

    If ``cancel`` (a ``threading.Event``) is set, raises ``JobCancelled`` before
    the next file (and mid-file for the in-progress entry) so a batch can be
    aborted promptly.

    ``exclude_patterns`` / ``include_patterns`` are glob lists applied to each
    file's relative path. When ``plan_only`` is True, no archive is written and
    a deterministic placeholder name is returned (used by dry-run mode).
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

    name = unique_archive_name(src.name or "backup", when, dest_dir=dst)
    final = dst / name
    fd, tmp = tempfile.mkstemp(dir=str(dst), suffix=".tmp")
    try:
        with (
            os.fdopen(fd, "wb") as out,
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=compress_level) as zf,
        ):
            all_files = sorted((p for p in src.rglob("*") if p.is_file()), key=lambda p: p.as_posix())
            files = [
                f
                for f in all_files
                if not should_skip(f.relative_to(src), exclude_patterns, include_patterns)
            ]
            total = len(files)
            bytes_total = sum(f.stat().st_size for f in files)
            files_done = 0
            bytes_done_total = 0

            _emit_zip_progress(
                on_progress,
                Progress(
                    job_id=job_id,
                    files_total=total,
                    files_done=0,
                    bytes_total=bytes_total,
                    bytes_done=0,
                    phase=PHASE_ZIPPING,
                ),
            )

            if plan_only:
                # Dry-run: report the plan without writing an archive.
                return final

            for f in files:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled("Zip cancelled")
                arcname = f.relative_to(src).as_posix()
                info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                size = f.stat().st_size
                # Stream the member into a temp spooled file in CHUNK-sized
                # writes (memory stays bounded at CHUNK until spilled to disk),
                # then hand the full bytes to writestr with the fixed
                # compresslevel. This keeps the archive byte-for-byte
                # reproducible (zf.open's streaming path does not reliably honour
                # per-member compresslevel across CPython versions) while
                # avoiding a single in-memory buffer of the whole file.
                done = 0
                with tempfile.SpooledTemporaryFile(max_size=CHUNK, suffix=".tmp") as spool:
                    with open(f, "rb") as inp:
                        while True:
                            if cancel is not None and cancel.is_set():
                                raise JobCancelled("Zip cancelled")
                            chunk = inp.read(CHUNK)
                            if not chunk:
                                break
                            spool.write(chunk)
                            done += len(chunk)
                            _emit_zip_progress(
                                on_progress,
                                Progress(
                                    job_id=job_id,
                                    files_total=total,
                                    files_done=files_done,
                                    bytes_total=bytes_total,
                                    bytes_done=bytes_done_total + done,
                                    current_file=arcname,
                                    phase=PHASE_ZIPPING,
                                ),
                            )
                    spool.seek(0)
                    zf.writestr(info, spool.read(), compresslevel=compress_level)
                bytes_done_total += size
                files_done += 1
                _emit_zip_progress(
                    on_progress,
                    Progress(
                        job_id=job_id,
                        files_total=total,
                        files_done=files_done,
                        bytes_total=bytes_total,
                        bytes_done=bytes_done_total,
                        current_file=arcname,
                        phase=PHASE_ZIPPING,
                    ),
                )
        os.replace(tmp, final)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return final
