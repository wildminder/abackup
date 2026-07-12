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
    shorten_display_path,
    format_job_label,
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


def test_safe_archive_name_custom_ext():
    name = safe_archive_name("My Docs", date(2026, 1, 1), ext=".7z")
    assert name == "My_Docs_2026-01-01.7z"


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


def test_shorten_display_path_short_unchanged():
    assert shorten_display_path("C:/Users/art/abackup") == "C:/Users/art/abackup"
    assert shorten_display_path("abackup") == "abackup"


def test_shorten_display_path_windows_drive_first_last():
    # Long Windows path: keep drive + first folder + last component.
    long = "C:/Users/art/Documents/Projects/abackup/with/a/very/long/path/that/exceeds"
    out = shorten_display_path(long, max_len=50)
    assert len(out) <= 50
    assert out.startswith("C:/Users")
    assert out.endswith("…/exceeds")
    assert "Documents" not in out
    assert "abackup" not in out  # 'abackup' is not the last component here


def test_shorten_display_path_windows_backslash():
    long = "C:\\Users\\user\\Documents\\Projects\\abackup\\deep\\file.txt"
    out = shorten_display_path(long, max_len=50)
    assert "\\" in out  # original separator preserved
    assert out.startswith("C:\\Users")
    assert out.endswith("…\\file.txt")


def test_shorten_display_path_posix_absolute():
    long = "/home/user/Documents/Projects/abackup/deep/file.txt"
    out = shorten_display_path(long, max_len=50)
    assert out.startswith("/home")
    assert out.endswith("…/file.txt")


def test_shorten_display_path_relative():
    long = "Users/art/Documents/Projects/abackup/deep/file.txt"
    out = shorten_display_path(long, max_len=50)
    assert out.startswith("Users")
    assert out.endswith("…/file.txt")


def test_shorten_display_path_unc():
    long = "//server/share/Projects/abackup/deep/file.txt"
    out = shorten_display_path(long, max_len=30)
    assert out.startswith("//server/share")
    assert out.endswith("…/file.txt")


def test_shorten_display_path_still_too_long_truncates_tail():
    # Even after dropping the first folder, head + "…" + tail exceeds
    # max_len, so the (very long) last component itself is truncated.
    long = "C:/Users/art/" + ("a" * 5) + "/" + ("b" * 40)
    out = shorten_display_path(long, max_len=30)
    assert len(out) <= 30
    assert out.startswith("C:/…")
    assert "…" in out


def test_format_job_label_basic():
    label = format_job_label(
        "Docs", "7z", "C:/Users/art/Documents", "D:/Backups"
    )
    assert label == "Docs [7z]: C:/Users/art/Documents -> D:/Backups"


def test_format_job_label_elides_long_paths():
    src = "C:/Users/art/Documents/Projects/abackup/with/a/very/long/source/path"
    dst = "D:/Backups/Archive/Projects/abackup/with/a/very/long/dest/path"
    label = format_job_label("Docs", "copy", src, dst, max_len=40)
    assert label.startswith("Docs [copy]: ")
    assert "->" in label
    # Both long paths are elided (no raw long segment remains).
    assert "Documents/Projects" not in label
    assert "Archive/Projects" not in label
    src_part, dst_part = label.split("->", 1)
    assert len(src_part) <= len("Docs [copy]: ") + 40
    assert len(dst_part.strip()) <= 40
