from datetime import datetime, timezone

from abackup.core.backup import run_job
from abackup.models import BackupJob, BackupMethod
from abackup.utils.errors import SourceNotFound


def _clock():
    return datetime(2026, 7, 12, 10, 0, 0, tzinfo=timezone.utc)


def test_run_job_copy(sample_tree, dest_dir, tmp_config, tmp_data):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    assert result.status == "success"
    assert (dest_dir / "out" / "b.txt").read_text() == "world"
    assert result.updated_job.last_status == "success"
    assert result.updated_job.last_run_at == "2026-07-12T10:00:00+00:00"
    assert result.manifest_path.endswith(".json")


def test_run_job_zip(sample_tree, dest_dir, tmp_config, tmp_data):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="zip")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    assert result.status == "success"
    assert "archive" in result.summary


def test_run_job_invalid_source_fails(dest_dir, tmp_config, tmp_data):
    job = BackupJob(source=str(dest_dir / "missing"), destination=str(dest_dir), method="copy")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    assert result.status == "failed"
    assert isinstance(result.error, str)
    assert result.updated_job.last_status == "failed"


def test_run_job_writes_manifest(sample_tree, dest_dir, tmp_config, tmp_data):
    import json
    from pathlib import Path

    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    manifest = json.loads(Path(result.manifest_path).read_text())
    assert manifest["status"] == "success"
    assert manifest["method"] == "copy"
