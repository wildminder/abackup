import json
from pathlib import Path

from abackup.config import (
    export_config,
    import_config,
    init_storage,
    load_jobs,
    load_settings,
    maybe_migrate_legacy_config,
    relocate_data,
    relocate_storage,
    save_jobs,
    save_settings,
)
from abackup.models import BackupJob, Settings
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
    data = json.loads((__import__("pathlib").Path(tmp_config) / "settings.json").read_text())
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
    # Legacy data dir (logs/manifests) lives under the platformdirs data root.
    legacy_data = tmp_path / "legacy_data"
    legacy_data.mkdir()
    (legacy_data / "logs").mkdir()
    (legacy_data / "logs" / "x.jsonl").write_text("{}")
    (legacy_data / "manifests").mkdir()
    (legacy_data / "manifests" / "y.json").write_text("{}")
    new = tmp_path / "newhome" / "abackup"
    monkeypatch.setattr("abackup.config.LEGACY_DIR", legacy)
    monkeypatch.setattr("abackup.config.default_config_dir", lambda: new)
    monkeypatch.setattr("abackup.config.get_data_dir", lambda override=None: legacy_data)
    maybe_migrate_legacy_config()
    assert (new / "settings.json").exists()
    assert (new / "jobs.json").exists()
    assert not (legacy / "settings.json").exists()
    # Run history (logs + manifests) is relocated too.
    assert (new / "logs" / "x.jsonl").exists()
    assert (new / "manifests" / "y.json").exists()
    assert not (legacy_data / "logs").exists()
    assert not (legacy_data / "manifests").exists()


def test_relocate_data_moves_logs_and_manifests(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "logs").mkdir()
    (old / "logs" / "x.jsonl").write_text("{}")
    (old / "manifests").mkdir()
    (old / "manifests" / "y.json").write_text("{}")
    new = tmp_path / "new"
    relocate_data(old, new)
    assert (new / "logs" / "x.jsonl").exists()
    assert (new / "manifests" / "y.json").exists()
    assert not (old / "logs").exists()
    assert not (old / "manifests").exists()


def test_relocate_data_idempotent_same_dir(tmp_path):
    old = tmp_path / "same"
    old.mkdir()
    (old / "logs").mkdir()
    (old / "logs" / "x.jsonl").write_text("{}")
    relocate_data(old, old)
    assert (old / "logs" / "x.jsonl").exists()


def test_relocate_data_creates_new_dir(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "logs").mkdir()
    (old / "logs" / "x.jsonl").write_text("{}")
    new = tmp_path / "new" / "nested"
    relocate_data(old, new)
    assert new.is_dir()
    assert (new / "logs" / "x.jsonl").exists()


def test_relocate_data_no_tmp_leftovers(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "logs").mkdir()
    (old / "logs" / "x.jsonl").write_text("{}")
    new = tmp_path / "new"
    relocate_data(old, new)
    assert list(tmp_path.rglob("*.tmp")) == []


def test_relocate_storage_also_moves_data(tmp_path):
    old = tmp_path / "old"

    old.mkdir()
    (old / "settings.json").write_text("{}", encoding="utf-8")
    (old / "jobs.json").write_text("[]", encoding="utf-8")
    (old / "logs").mkdir()
    (old / "logs" / "x.jsonl").write_text("{}")
    (old / "manifests").mkdir()
    (old / "manifests" / "y.json").write_text("{}")
    new = tmp_path / "new"
    relocate_storage(old, new)
    relocate_data(old, new)
    assert (new / "settings.json").exists()
    assert (new / "jobs.json").exists()
    assert (new / "logs" / "x.jsonl").exists()
    assert (new / "manifests" / "y.json").exists()
    assert not (old / "settings.json").exists()
    assert not (old / "logs").exists()


def test_export_config_writes_portable_file(tmp_config, tmp_path):
    save_settings(Settings(default_destination="D:/x"), tmp_config)
    save_jobs([BackupJob(source="C:/a", destination="D:/b", method="copy")], tmp_config)
    dest = tmp_path / "portable.json"
    export_config(tmp_config, dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert "settings" in data and "jobs" in data
    assert data["settings"]["default_destination"] == "D:/x"
    assert len(data["jobs"]) == 1


def test_import_config_overwrites(tmp_config, tmp_path):
    save_jobs([BackupJob(source="C:/a", destination="D:/b", method="copy")], tmp_config)
    dest = tmp_path / "portable.json"
    export_config(tmp_config, dest)
    # Change the source config, then import -> should be overwritten.
    save_jobs([BackupJob(source="C:/other", destination="D:/b", method="copy")], tmp_config)
    import_config(dest, tmp_config)
    jobs = load_jobs(tmp_config)
    assert len(jobs) == 1
    assert jobs[0].source == "C:/a"


def test_import_config_merge_upserts_by_id(tmp_config, tmp_path):
    save_jobs([BackupJob(source="C:/a", destination="D:/b", method="copy", id="1", name="a")], tmp_config)
    dest = tmp_path / "portable.json"
    export_config(tmp_config, dest)
    # Existing job "1" plus a new job "2"; merge should keep both, "1" updated.
    save_jobs(
        [
            BackupJob(source="C:/a2", destination="D:/b", method="copy", id="1", name="a"),
            BackupJob(source="C:/c", destination="D:/d", method="copy", id="2", name="c"),
        ],
        tmp_config,
    )
    import_config(dest, tmp_config, merge=True)
    jobs = {j.id: j for j in load_jobs(tmp_config)}
    assert set(jobs) == {"1", "2"}
    # Job "1" came from the imported file (overwrote the existing one).
    assert jobs["1"].source == "C:/a"


def test_import_config_rejects_invalid_json(tmp_config, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    try:
        import_config(bad, tmp_config)
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_import_config_rejects_invalid_job(tmp_config, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"settings": {}, "jobs": [{"method": "copy"}]}), encoding="utf-8")
    try:
        import_config(bad, tmp_config)
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_export_import_roundtrip(tmp_config, tmp_path):
    save_settings(Settings(default_destination="D:/x", max_workers=7), tmp_config)
    save_jobs(
        [
            BackupJob(source="C:/a", destination="D:/b", method="copy", name="a"),
            BackupJob(source="C:/c", destination="D:/d", method="7z", name="c"),
        ],
        tmp_config,
    )
    dest = tmp_path / "portable.json"
    export_config(tmp_config, dest)
    new_dir = tmp_path / "new"
    import_config(dest, new_dir)
    settings = load_settings(new_dir)
    jobs = load_jobs(new_dir)
    assert settings.max_workers == 7
    assert settings.default_destination == "D:/x"
    assert len(jobs) == 2
    assert {j.name for j in jobs} == {"a", "c"}


def test_save_jobs_relative_when_enabled(tmp_config):
    save_settings(Settings(relative_paths=True), tmp_config)
    src = Path(tmp_config) / "sources" / "docs"
    save_jobs([BackupJob(source=str(src), destination="D:/b", method="copy")], tmp_config)
    raw = json.loads((Path(tmp_config) / "jobs.json").read_text(encoding="utf-8"))
    assert raw[0]["source"] == "sources/docs"


def test_load_jobs_resolves_relative_to_absolute(tmp_config):
    save_settings(Settings(relative_paths=True), tmp_config)
    src = Path(tmp_config) / "sources" / "docs"
    save_jobs([BackupJob(source=str(src), destination="D:/b", method="copy")], tmp_config)
    jobs = load_jobs(tmp_config)
    assert Path(jobs[0].source).is_absolute()
    assert Path(jobs[0].source) == src.resolve()


def test_relative_paths_off_stores_absolute(tmp_config):
    save_settings(Settings(relative_paths=False), tmp_config)
    src = Path(tmp_config) / "sources" / "docs"
    save_jobs([BackupJob(source=str(src), destination="D:/b", method="copy")], tmp_config)
    raw = json.loads((Path(tmp_config) / "jobs.json").read_text(encoding="utf-8"))
    assert raw[0]["source"] == str(src)

