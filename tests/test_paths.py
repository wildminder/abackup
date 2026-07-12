from datetime import date

from abackup.core.paths import (
    get_config_dir,
    get_data_dir,
    ensure_dir,
    safe_archive_name,
    settings_file_path,
    jobs_file_path,
)


def test_override_dirs():
    assert get_config_dir("C:/x").as_posix() == "C:/x"
    assert get_data_dir("C:/y").as_posix() == "C:/y"


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
