"""Zip backup method (deterministic naming and entry timestamps)."""

from __future__ import annotations

import os
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from abackup.core.paths import safe_archive_name
from abackup.utils.errors import SourceNotFound, DestinationError

# Fixed timestamp so zip byte output is reproducible across runs.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def make_zip(
    source: str | Path,
    destination: str | Path,
    *,
    when: date | None = None,
) -> Path:
    """Create ``<source_name>_<YYYY-MM-DD>.zip`` in ``destination``.

    Files are streamed in sorted order with a fixed entry timestamp, making the
    resulting archive byte-for-byte reproducible for the same inputs.
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
            out, "w", zipfile.ZIP_DEFLATED
        ) as zf:
            files = sorted(
                (p for p in src.rglob("*") if p.is_file()), key=lambda p: p.as_posix()
            )
            for f in files:
                arcname = f.relative_to(src).as_posix()
                info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(f, "rb") as inp:
                    zf.writestr(info, inp.read())
        os.replace(tmp, final)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return final
