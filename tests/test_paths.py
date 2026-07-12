from datetime import date
from pathlib import Path

from abackup.core.paths import (
    get_config_dir,
    get_data_dir,
    ensure_dir,
    safe_archive_name,
    settings_file_path,
    jobs_file_path,
    default_config_dir,
    shorten_path,
)


def test_override_dirs():
    assert get_config_dir("C:/x").as_posix() == "C:/x"
    assert get_data_dir("C:/y").as_posix() == "C:/y"


def test_default_config_dir_windows():
    assert default_config_dir("win32", Path("/x")) == Path("/x/Documents/abackup")


def test_default_config_dir_posix():
    assert default_config_dir("linux", Path("/x")) == Path("/x/abackup")
    assert default_config_dir("darwin", Path("/x")) == Path("/x/abackup")


def test_get_config_dir_override_wins():
    assert get_config_dir("C:/override") == Path("C:/override")


def test_ensure_dir_idempotent(tmp_path):
    p = tmp_path / "a" / "b"
    ensure_dir(p)
    ensure_dir(p)
    assert p.is_dir()


def test_safe_archive_name_basic():
    name = safe_archive_name("My Docs", date(2026, 7, 12))
    assert name == "My_Docs_2026-07-12.zip"


def test_safe_archive_name_sanitizes():
    name = safe_archive_name("a/b:c*?", date(2026, 1, 1))
    assert "/" not in name
    assert name.endswith(".zip")


def test_safe_archive_name_fallback_empty():
    name = safe_archive_name("", date(2026, 1, 1))
    assert name == "backup_2026-01-01.zip"


def test_file_paths(tmp_path):
    assert settings_file_path(tmp_path).name == "settings.json"
    assert jobs_file_path(tmp_path).name == "jobs.json"


def test_shorten_path_empty():
    assert shorten_path("") == ""
    assert shorten_path(None) == ""


def test_shorten_path_relative_to_root():
    root = "C:/Users/art/Documents"
    full = "C:/Users/art/Documents/projects/abackup/src/main.py"
    assert shorten_path(full, root) == "projects/abackup/src/main.py"


def test_shorten_path_root_match_case_insensitive():
    # Windows paths are case-insensitive on the prefix.
    assert shorten_path("c:/x/y/file.txt", "C:/X") == "y/file.txt"


def test_shorten_path_elides_middle_when_long():
    root = "C:/Users/art/Documents"
    full = "C:/Users/art/Documents/" + ("a" * 60) + "/file.txt"
    out = shorten_path(full, root, max_len=40)
    assert len(out) <= 40
    assert out.endswith("…file.txt")
    assert "file.txt" in out


def test_shorten_path_not_under_root_uses_basename():
    full = "D:/elsewhere/deep/nested/really/long/path/file.txt"
    out = shorten_path(full, "C:/Other", max_len=40)
    # Not under root -> basename fallback (no leading drive noise).
    assert out == "file.txt"


def test_shorten_path_basename_too_long_gets_elided():
    name = "x" * 50 + ".txt"
    out = shorten_path(name, max_len=20)
    assert len(out) <= 20
    assert out.endswith("…")


def test_shorten_path_short_unchanged():
    # Short path under root is returned unchanged (relative form).
    assert shorten_path("C:/root/sub/file.txt", "C:/root", max_len=40) == "sub/file.txt"
