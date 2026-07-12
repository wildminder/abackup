import json

from abackup.config import (
    load_settings,
    save_settings,
    load_jobs,
    save_jobs,
    init_storage,
)
from abackup.models import BackupJob, BackupMethod, Settings
from abackup.utils.errors import ConfigError


def test_settings_save_load_round_trip(tmp_config):
    save_settings(Settings(first_run_completed=True), tmp_config)
    loaded = load_settings(tmp_config)
    assert loaded.first_run_completed is True


def test_load_settings_missing_returns_default(tmp_config):
    assert load_settings(tmp_config).first_run_completed is False


def test_load_settings_corrupt_raises(tmp_config):
    p = __import__("pathlib").Path(tmp_config) / "settings.json"
    p.write_text("{not valid json", encoding="utf-8")
    try:
        load_settings(tmp_config)
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_jobs_save_load_round_trip(tmp_config):
    job = BackupJob(source="C:/a", destination="D:/b", method="copy")
    save_jobs([job], tmp_config)
    jobs = load_jobs(tmp_config)
    assert len(jobs) == 1
    assert jobs[0].id == job.id


def test_load_jobs_missing_returns_empty(tmp_config):
    assert load_jobs(tmp_config) == []


def test_init_storage_creates_defaults(tmp_config):
    init_storage(tmp_config)
    assert (json.loads((__import__("pathlib").Path(tmp_config) / "settings.json").read_text()))[
        "first_run_completed"
    ] is False


def test_atomic_write_leaves_no_tmp(tmp_config):
    save_settings(Settings(), tmp_config)
    leftovers = list(__import__("pathlib").Path(tmp_config).glob("*.tmp"))
    assert leftovers == []
