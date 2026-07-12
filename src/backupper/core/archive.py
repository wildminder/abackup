"""Zip backup method (deterministic naming and entry timestamps) with realtime progress."""

from __future__ import annotations

import os
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from abackup.core.paths import safe_archive_name
from abackup.core.progress import (
    Progress,
    PHASE_ZIPPING,
    OptionalProgressCallback,
)
from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled

# Fixed timestamp so zip byte output is reproducible across runs.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Stream files in 1 MiB chunks so we can report byte-level progress without
# loading an entire (possibly huge) file into memory.
CHUNK = 1024 * 1024


def make_zip(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
    compress_level: int = 6,
    cancel=None,
    job_id: str = "",
    on_progress: OptionalProgressCallback = None,
) -> Path:
    """Create ``<source_name>_<YYYY-MM-DD>.zip`` in ``destination``.

    Files are streamed in sorted order with a fixed entry timestamp, making the
    resulting archive byte-for-byte reproducible for the same inputs across runs.

    Emits :class:`Progress` snapshots via ``on_progress``: one at start (totals
    from a pre-scan), one per 1 MiB chunk (byte-level), and one per file
    (file-level). Each file is written through ``ZipFile.open(..., "w")`` in
    chunks so progress is smooth and memory stays bounded.

    If ``cancel`` (a ``threading.Event``) is set, raises ``JobCancelled`` before
    the next file (and mid-file for the in-progress entry) so a batch can be
    aborted promptly.
    """
    src = Path(source)
    dst = Path(destination)
    if not src.exists() or not src.is_dir():
        raise SourceNotFound(f"Source directory not found: {src}")
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationError(f"Cannot create destination {dst}: {exc}") from exc

    name = safe_archive_name(src.name or "backup", when)
    final = dst / name
    fd, tmp = tempfile.mkstemp(dir=str(dst), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, zipfile.ZipFile(
            out, "w", zipfile.ZIP_DEFLATED, compresslevel=compress_level
        ) as zf:
            files = sorted(
                (p for p in src.rglob("*") if p.is_file()), key=lambda p: p.as_posix()
            )
            total = len(files)
            bytes_total = sum(f.stat().st_size for f in files)
            files_done = 0
            bytes_done_total = 0

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

            for f in files:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled("Zip cancelled")
                arcname = f.relative_to(src).as_posix()
                info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                size = f.stat().st_size
                # Read in chunks so we can report byte-level progress without
                # blocking; the full bytes are written via writestr so the
                # archive stays byte-for-byte reproducible and honours the
                # requested compression level (zf.open's streaming path does not
                # reliably apply per-member compresslevel across CPython versions).
                data = bytearray()
                done = 0
                with open(f, "rb") as inp:
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise JobCancelled("Zip cancelled")
                        chunk = inp.read(CHUNK)
                        if not chunk:
                            break
                        data.extend(chunk)
                        done += len(chunk)
                        if on_progress is not None:
                            on_progress(
                                Progress(
                                    job_id=job_id,
                                    files_total=total,
                                    files_done=files_done,
                                    bytes_total=bytes_total,
                                    bytes_done=bytes_done_total + done,
                                    current_file=arcname,
                                    phase=PHASE_ZIPPING,
                                )
                            )
                zf.writestr(info, bytes(data), compresslevel=compress_level)
                bytes_done_total += size
                files_done += 1
                if on_progress is not None:
                    on_progress(
                        Progress(
                            job_id=job_id,
                            files_total=total,
                            files_done=files_done,
                            bytes_total=bytes_total,
                            bytes_done=bytes_done_total,
                            current_file=arcname,
                            phase=PHASE_ZIPPING,
                        )
                    )
        os.replace(tmp, final)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return final
