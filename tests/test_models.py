from abackup.models import BackupJob, BackupMethod, Settings
from abackup.utils.errors import ConfigError


def test_settings_round_trip():
    s = Settings(first_run_completed=True, default_destination="D:/x")
    d = s.to_dict()
    s2 = Settings.from_dict(d)
    assert s2.first_run_completed is True
    assert s2.default_destination == "D:/x"
    assert s2.is_first_run is False


def test_settings_defaults_first_run():
    assert Settings().is_first_run is True


def test_backup_method_from_str_invalid():
    try:
        BackupMethod.from_str("nope")
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_job_make_id_deterministic():
    j1 = BackupJob(source="C:/a", destination="D:/b", method="copy", created_at="2026-01-01T00:00:00+00:00")
    j2 = BackupJob(source="C:/a", destination="D:/b", method="copy", created_at="2026-01-01T00:00:00+00:00")
    assert j1.id == j2.id
    assert j1.id == j1.make_id()


def test_job_name_defaults_to_source_basename():
    j = BackupJob(source="C:/Users/art/Documents", destination="D:/b", method="zip")
    assert j.name == "Documents"


def test_job_method_str_coerced():
    j = BackupJob(source="C:/a", destination="D:/b", method="zip")
    assert j.method is BackupMethod.ZIP
    assert j.to_dict()["method"] == "zip"


def test_job_from_dict_round_trip():
    j = BackupJob(source="C:/a", destination="D:/b", method="copy", name="n", last_status="success")
    j2 = BackupJob.from_dict(j.to_dict())
    assert j2.source == j.source
    assert j2.method == j.method
    assert j2.last_status == "success"


def test_settings_max_workers_default():
    assert Settings().max_workers == 4


def test_settings_max_workers_round_trip():
    s = Settings(max_workers=8)
    assert Settings.from_dict(s.to_dict()).max_workers == 8


def test_settings_from_dict_keeps_default_without_field():
    # Old settings.json (no max_workers) must still load with the default.
    s = Settings.from_dict({"first_run_completed": True})
    assert s.max_workers == 4
    assert s.first_run_completed is True


def test_zip_level_default_6():
    assert Settings().zip_compression_level == 6


def test_zip_level_round_trip():
    s = Settings(zip_compression_level=9)
    assert Settings.from_dict(s.to_dict()).zip_compression_level == 9


def test_settings_from_dict_defaults_level():
    # Old settings.json (no zip_compression_level) loads with default 6.
    s = Settings.from_dict({"first_run_completed": True})
    assert s.zip_compression_level == 6


def test_settings_validate_rejects_level_10():
    try:
        Settings(zip_compression_level=10).validate()
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_settings_validate_rejects_level_neg():
    try:
        Settings(zip_compression_level=-1).validate()
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_settings_validate_rejects_bad_log_level():
    try:
        Settings(log_level="VERBOSE").validate()
    except ConfigError:
        return
    raise AssertionError("expected ConfigError")


def test_settings_validate_ok():
    # Valid settings must not raise.
    Settings(zip_compression_level=0, max_workers=1, log_level="DEBUG").validate()
