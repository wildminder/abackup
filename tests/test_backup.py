import threading
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


def test_run_job_uses_compression_level(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    import abackup.core.backup as backup_mod
    from pathlib import Path

    captured = {}

    def fake_make_zip(source, destination, *, when=None, compress_level=6, cancel=None):
        captured["compress_level"] = compress_level
        return Path(destination) / "x.zip"

    monkeypatch.setattr(backup_mod, "make_zip", fake_make_zip)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="zip")
    run_job(
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        zip_compression_level=3,
    )
    assert captured["compress_level"] == 3


def test_run_job_cancel_copy_mid_run(sample_tree, dest_dir, tmp_config, tmp_data):
    cancel = threading.Event()
    seen = []

    def on_progress(done, total, path):
        seen.append(path)
        if len(seen) >= 1:
            cancel.set()

    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    result = run_job(
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        on_progress=on_progress,
        cancel=cancel,
    )
    assert result.status == "cancelled"
    assert result.updated_job.last_status == "cancelled"
    assert result.error == "cancelled"


def test_run_job_cancel_zip_mid_run(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    import builtins

    import abackup.core.archive as archive_mod

    for i in range(20):
        (sample_tree / f"f{i:02d}.txt").write_text(f"content-{i}", encoding="utf-8")
    cancel = threading.Event()
    real_open = builtins.open
    first = {}

    def fake_open(path, *args, **kwargs):
        f = real_open(path, *args, **kwargs)
        if not first.get("done") and str(path).endswith(".txt"):
            orig_read = f.read

            def read(n=-1):
                data = orig_read(n)
                cancel.set()
                first["done"] = True
                return data

            f.read = read
        return f

    monkeypatch.setattr(archive_mod, "open", fake_open, raising=False)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="zip")
    result = run_job(
        job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock, cancel=cancel
    )
    assert result.status == "cancelled"
    assert result.updated_job.last_status == "cancelled"
