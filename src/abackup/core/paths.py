"""Path & directory resolution helpers."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import platformdirs

_UNSAFE = re.compile(r"[^\w.\-]+")


def default_config_dir(platform: str | None = None, home: Path | None = None) -> Path:
    """Resolve the default settings/jobs storage directory.

    - Windows: ``<home>/Documents/abackup``
    - Other platforms: ``<home>/abackup``

    ``platform``/``home`` are injectable so tests are deterministic without
    touching ``sys`` or ``Path.home()``.
    """
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "win32":
        return home / "Documents" / "abackup"
    return home / "abackup"


def get_config_dir(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    return default_config_dir()


def get_data_dir(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("abackup", "abackup"))


def is_inside(child: str | Path, parent: str | Path) -> bool:
    """Return ``True`` if ``child`` resolves to ``parent`` or lives under it.

    Used to reject a backup destination that is the source itself or a
    subfolder of the source (which would recurse / overwrite). Resolution is
    injected via ``Path.resolve`` so symlinks and ``..`` are normalized.
    """
    child_path = Path(child).resolve()
    parent_path = Path(parent).resolve()
    return child_path == parent_path or parent_path in child_path.parents


def ensure_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents) if missing. Idempotent."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_archive_name(source_name: str, when: date | None = None, ext: str = ".zip") -> str:
    """Deterministic archive name: ``<source>_<YYYY-MM-DD><ext>``.

    Unsafe characters are replaced with underscores; falls back to ``backup``.
    """
    when = when or date.today()
    base = _UNSAFE.sub("_", source_name).strip("_") or "backup"
    return f"{base}_{when.isoformat()}{ext}"


def unique_archive_name(
    source_name: str,
    when: date | None = None,
    ext: str = ".zip",
    dest_dir: str | Path = ".",
) -> str:
    """Collision-free archive name: ``<base>_<YYYY-MM-DD>[_N]<ext>``.

    The first run on a given day yields ``<base>_<YYYY-MM-DD><ext>``; subsequent
    same-day runs append an incrementing ``_N`` so a previous archive is never
    overwritten (fixes NTH-006). ``dest_dir`` scopes the collision check.
    """
    when = when or date.today()
    base = _UNSAFE.sub("_", source_name).strip("_") or "backup"
    stem = f"{base}_{when.isoformat()}"
    dest = Path(dest_dir)
    candidate = f"{stem}{ext}"
    if not (dest / candidate).exists():
        return candidate
    i = 1
    while True:
        candidate = f"{stem}_{i}{ext}"
        if not (dest / candidate).exists():
            return candidate
        i += 1


def settings_file_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "settings.json"


def jobs_file_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "jobs.json"


def shorten_path(
    path: str | Path | None,
    root: str | Path | None = None,
    max_len: int = 40,
) -> str:
    """Return a compact, display-friendly form of ``path``.

    - If ``root`` is given and ``path`` lives under it, the root prefix is
      stripped so only the path *relative to the backup source* is shown
      (e.g. ``subdir/file.txt`` instead of a long absolute path).
    - If the (relative or absolute) result is longer than ``max_len``, the
      middle is elided (``root\\…\\file.txt``) while keeping the basename.
    - If the path is not under ``root``, the basename is used as a fallback.
    - Empty/None input returns ``""``.
    """
    if not path:
        return ""
    text = str(path)
    base = Path(text)
    if root:
        root_text = str(root)
        # Case-insensitive prefix match (Windows paths).
        if text.lower().startswith(root_text.lower()):
            rel = text[len(root_text) :].lstrip("\\/")
            text = rel or base.name
        else:
            # Not under the source root -> fall back to the basename only.
            text = base.name
    if len(text) <= max_len:
        return text
    # Elide the middle, preserving the basename.
    name = base.name
    if len(name) >= max_len - 1:
        return name[: max_len - 1] + "…"
    keep = max_len - len(name) - 1  # room for "…" + basename
    return f"{text[:keep]}…{name}"


def shorten_display_path(path: str | Path, max_len: int = 50) -> str:
    """Compact a full path for display, eliding the middle.

    Keeps the drive (if any), the first folder, and the last component,
    inserting ``…`` in the middle, e.g. ``C:\\Users\\…\\abackup``. If the
    result is still longer than ``max_len`` the last component is truncated.
    Short paths are returned unchanged. The original separator style
    (``\\`` vs ``/``) is preserved.
    """
    text = str(path)
    if len(text) <= max_len:
        return text
    sep = "\\" if "\\" in text else "/"
    is_unc = text.startswith("\\\\") or text.startswith("//")
    parts = [p for p in text.split(sep) if p != ""]
    if len(parts) <= 2 and not is_unc:
        return text[: max_len - 1] + "…"

    # head = drive/root + first folder; tail = last component.
    if is_unc and len(parts) >= 2:
        head = sep + sep + parts[0] + sep + parts[1]
        tail = parts[-1] if len(parts) >= 3 else ""
    elif len(parts[0]) == 2 and parts[0].endswith(":"):
        # Windows drive, e.g. "C:".
        head = parts[0] + (sep + parts[1] if len(parts) > 1 else "")
        tail = parts[-1]
    elif text.startswith(sep):
        # POSIX absolute path.
        head = sep + parts[0]
        tail = parts[-1]
    else:
        # Relative path.
        head = parts[0]
        tail = parts[-1]

    if not tail:
        return text[: max_len - 1] + "…"
    candidate = f"{head}{sep}…{sep}{tail}"
    if len(candidate) <= max_len:
        return candidate

    # Still too long: drop the first folder, keep only drive/root + … + tail.
    if is_unc and len(parts) >= 2:
        head = sep + sep + parts[0] + sep
    elif len(parts[0]) == 2 and parts[0].endswith(":"):
        head = parts[0] + sep
    elif text.startswith(sep):
        head = sep
    else:
        head = ""
    prefix = head
    candidate = f"{prefix}…{sep}{tail}"
    if len(candidate) <= max_len:
        return candidate

    # Last resort: truncate the tail itself.
    room = max_len - len(prefix) - len(sep) - 1  # 1 for the "…"
    if room < 1:
        return text[: max_len - 1] + "…"
    return f"{prefix}…{sep}{tail[:room]}"


def format_job_label(
    name: str,
    method: str,
    source: str,
    destination: str,
    max_len: int = 50,
) -> str:
    """Build the job list label: ``name [method]: source -> destination``.

    ``source`` and ``destination`` are elided in the middle (keeping drive,
    first folder and last component) when longer than ``max_len``.
    """
    src = shorten_display_path(source, max_len)
    dst = shorten_display_path(destination, max_len)
    return f"{name} [{method}]: {src} -> {dst}"


def resolve_destination(
    job,
    *,
    clock: Callable[[], datetime] | None = None,
    stamp: bool = False,
) -> str:
    """Resolve the effective destination directory for a job.

    When ``stamp`` is True (or ``job.subfolder_stamp`` is set), a timestamped
    subfolder ``<destination>/<YYYY-MM-DD_HHMMSS>`` is appended so each run lands
    in its own folder (RM-10). Otherwise the job's ``destination`` is returned
    unchanged. ``clock`` is injectable for deterministic tests.
    """
    if not stamp and not getattr(job, "subfolder_stamp", False):
        return job.destination
    clock = clock or datetime.now
    when = clock()
    # Use a filesystem-safe timestamp (no colons) for the subfolder name.
    stamp_str = when.strftime("%Y-%m-%d_%H%M%S")
    return str(Path(job.destination) / stamp_str)
