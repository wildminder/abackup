import json

from abackup.config import (
    load_settings,
    save_settings,
    load_jobs,
    save_jobs,
    init_storage,
    relocate_storage,
    maybe_migrate_legacy_config,
)
from abackup.models import BackupJob, BackupMethod, Settings
from abackup.utils.errors import ConfigError


def test_settings_save_load_round_trip(tmp_config):
    save_settings(Settings(default_destination="D:/x"), tmp_config)
    loaded = load_settings(tmp_config)
    assert loaded.default_destination == "D:/x"


def test_load_settings_missing_returns_default(tmp_config):
    assert load_settings(tmp_config).default_destination is None


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
    data = json.loads(
        (__import__("pathlib").Path(tmp_config) / "settings.json").read_text()
    )
    assert data["schema_version"] == 1
    assert data["max_workers"] == 4


def test_atomic_write_leaves_no_tmp(tmp_config):
    save_settings(Settings(), tmp_config)
    leftovers = list(__import__("pathlib").Path(tmp_config).glob("*.tmp"))
    assert leftovers == []


def test_relocate_storage_moves_settings_and_jobs(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (old / "jobs.json").write_text("[]", encoding="utf-8")
    new = tmp_path / "new"
    relocate_storage(old, new)
    assert (new / "settings.json").exists()
    assert (new / "jobs.json").exists()
    assert not (old / "settings.json").exists()
    assert not (old / "jobs.json").exists()


def test_relocate_storage_creates_new_dir(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "settings.json").write_text("{}", encoding="utf-8")
    new = tmp_path / "new" / "nested"
    relocate_storage(old, new)
    assert new.is_dir()
    assert (new / "settings.json").exists()


def test_relocate_storage_idempotent_when_same_dir(tmp_path):
    old = tmp_path / "same"
    old.mkdir()
    (old / "settings.json").write_text("{}", encoding="utf-8")
    # No exception, file remains in place.
    relocate_storage(old, old)
    assert (old / "settings.json").exists()


def test_relocate_storage_leaves_no_tmp(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "settings.json").write_text("{}", encoding="utf-8")
    (old / "jobs.json").write_text("[]", encoding="utf-8")
    new = tmp_path / "new"
    relocate_storage(old, new)
    assert list(tmp_path.rglob("*.tmp")) == []


def test_legacy_migration_moves_files(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "settings.json").write_text('{"first_run_completed": true}', encoding="utf-8")
    (legacy / "jobs.json").write_text("[]", encoding="utf-8")
    new = tmp_path / "newhome" / "abackup"
    monkeypatch.setattr("abackup.config.LEGACY_DIR", legacy)
    monkeypatch.setattr("abackup.config.default_config_dir", lambda: new)
    maybe_migrate_legacy_config()
    assert (new / "settings.json").exists()
    assert (new / "jobs.json").exists()
    assert not (legacy / "settings.json").exists()
