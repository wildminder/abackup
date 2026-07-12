"""Path & directory resolution helpers."""

from __future__ import annotations

import re
import sys
from datetime import date
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
            rel = text[len(root_text):].lstrip("\\/")
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
