import threading
from datetime import UTC, datetime

from abackup.core.backup import run_job
from abackup.models import BackupJob


def _clock():
    return datetime(2026, 7, 12, 10, 0, 0, tzinfo=UTC)


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
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock, prefer_py7zr=False)
    assert result.status == "success"
    assert "archive" in result.summary


def test_run_job_seven_zip(sample_tree, dest_dir, tmp_config, tmp_data):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="7z")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock, prefer_py7zr=False)
    assert result.status == "success"
    assert result.summary["archive"].endswith(".7z")


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
    from pathlib import Path

    import abackup.core.backup as backup_mod

    captured = {}

    def fake_make_zip(
        source,
        destination,
        *,
        when=None,
        compress_level=6,
        cancel=None,
        job_id="",
        on_progress=None,
        **kwargs,
    ):
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


def test_run_job_uses_seven_zip_compression_level(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    from pathlib import Path

    import abackup.core.backup as backup_mod

    captured = {}

    def fake_make_archive(
        source,
        destination,
        *,
        when=None,
        compress_level=6,
        cancel=None,
        job_id="",
        on_progress=None,
        prefer_7z=True,
        prefer_py7zr=True,
        threads=None,
        **kwargs,
    ):
        captured["compress_level"] = compress_level
        return Path(destination) / "x.7z"

    monkeypatch.setattr(backup_mod, "make_archive", fake_make_archive)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="7z")
    run_job(
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        seven_zip_compression_level=4,
    )
    assert captured["compress_level"] == 4


def test_run_job_zip_level_independent_from_seven_zip_level(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    from pathlib import Path

    import abackup.core.backup as backup_mod

    captured = {}

    def fake_make_zip(
        source,
        destination,
        *,
        when=None,
        compress_level=6,
        cancel=None,
        job_id="",
        on_progress=None,
        **kwargs,
    ):
        captured.setdefault("zip", compress_level)
        return Path(destination) / "x.zip"

    def fake_make_archive(
        source,
        destination,
        *,
        when=None,
        compress_level=6,
        cancel=None,
        job_id="",
        on_progress=None,
        prefer_7z=True,
        prefer_py7zr=True,
        threads=None,
        **kwargs,
    ):
        captured.setdefault("seven", compress_level)
        return Path(destination) / "x.7z"

    monkeypatch.setattr(backup_mod, "make_zip", fake_make_zip)
    monkeypatch.setattr(backup_mod, "make_archive", fake_make_archive)

    zip_job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="zip")
    run_job(
        zip_job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        zip_compression_level=9,
        seven_zip_compression_level=2,
    )
    seven_job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="7z")
    run_job(
        seven_job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        zip_compression_level=9,
        seven_zip_compression_level=2,
    )
    # Each method uses its own level, independent of the other.
    assert captured["zip"] == 9
    assert captured["seven"] == 2


def test_run_job_cancel_copy_mid_run(sample_tree, dest_dir, tmp_config, tmp_data):
    cancel = threading.Event()
    seen = []

    def on_progress(p):
        seen.append(p)
        if p.current_file:
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


def test_run_job_copy_emits_progress(sample_tree, dest_dir, tmp_config, tmp_data):
    seen = []
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    run_job(
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        on_progress=lambda p: seen.append(p),
    )
    assert seen
    assert seen[-1].status == "success"
    assert seen[-1].percent() == 100
    assert seen[-1].bytes_total > 0


def test_run_job_zip_emits_progress(sample_tree, dest_dir, tmp_config, tmp_data):
    seen = []
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="zip")
    run_job(
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        prefer_py7zr=False,
        on_progress=lambda p: seen.append(p),
    )
    assert any(p.phase == "zipping" for p in seen)
    assert seen[-1].status == "success"
    assert seen[-1].percent() == 100


def test_run_job_missing_source_emits_failed(sample_tree, dest_dir, tmp_config, tmp_data):
    seen = []
    job = BackupJob(source=str(dest_dir / "missing"), destination=str(dest_dir), method="copy")
    run_job(
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        on_progress=lambda p: seen.append(p),
    )
    assert seen[-1].status == "failed"
    assert seen[-1].phase == "failed"


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
        job,
        config_dir=tmp_config,
        data_dir=tmp_data,
        clock=_clock,
        prefer_py7zr=False,
        cancel=cancel,
    )
    assert result.status == "cancelled"
    assert result.updated_job.last_status == "cancelled"


def test_run_job_manifest_includes_failed_files(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    import json
    from pathlib import Path

    import abackup.core.backup as backup_mod

    def fake_copy_tree(source, destination, **kwargs):
        return {
            "files_total": 2,
            "files_copied": 1,
            "files_skipped": 0,
            "files_failed": 1,
            "failed_files": [{"file": "bad.txt", "error": "locked"}],
            "bytes_copied": 5,
        }

    monkeypatch.setattr(backup_mod, "copy_tree", fake_copy_tree)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    # The job still completes (status success); failures are recorded.
    assert result.status == "success"
    manifest = json.loads(Path(result.manifest_path).read_text())
    assert manifest["summary"]["files_failed"] == 1
    assert manifest["summary"]["failed_files"][0]["file"] == "bad.txt"


def test_run_job_summary_includes_failed_count(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    import abackup.core.backup as backup_mod

    def fake_copy_tree(source, destination, **kwargs):
        return {
            "files_total": 2,
            "files_copied": 1,
            "files_skipped": 0,
            "files_failed": 1,
            "failed_files": [{"file": "bad.txt", "error": "locked"}],
            "bytes_copied": 5,
        }

    monkeypatch.setattr(backup_mod, "copy_tree", fake_copy_tree)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    assert result.summary["files_failed"] == 1
    assert result.summary["failed_files"][0]["error"] == "locked"


def test_run_job_default_prefer_py7zr_is_false(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    """CRIT-001: run_job must default prefer_py7zr=False to match Settings/README."""
    from pathlib import Path

    import abackup.core.backup as backup_mod

    captured = {}

    def fake_make_archive(
        source,
        destination,
        *,
        when=None,
        compress_level=6,
        cancel=None,
        job_id="",
        on_progress=None,
        prefer_py7zr=True,
        threads=None,
        **kwargs,
    ):
        captured["prefer_py7zr"] = prefer_py7zr
        return Path(destination) / "x.7z"

    monkeypatch.setattr(backup_mod, "make_archive", fake_make_archive)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="7z")
    run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock)
    assert captured["prefer_py7zr"] is False


def test_runner_passes_prefer_py7zr_through(tmp_config, tmp_data, monkeypatch):
    """CRIT-001: run_jobs_batch forwards prefer_py7zr to run_job unchanged."""
    import abackup.core.runner as runner_mod
    from abackup.models import BackupJob

    captured = {}

    def fake_run_job(job, **kwargs):
        captured["prefer_py7zr"] = kwargs.get("prefer_py7zr")
        from abackup.core.backup import BackupResult

        return BackupResult(
            job.id,
            job.method.value,
            "success",
            {},
            None,
            None,
            job,
        )

    monkeypatch.setattr(runner_mod, "run_job", fake_run_job)
    from pathlib import Path

    job = BackupJob(source=str(Path(tmp_data) / "s"), destination=str(Path(tmp_data) / "o"), method="copy")
    runner_mod.run_jobs_batch([job], config_dir=tmp_config, data_dir=tmp_data, prefer_py7zr=False)
    assert captured["prefer_py7zr"] is False


def test_run_job_dry_run_no_write(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    """RM-05b: dry-run plans but writes nothing and produces no manifest."""
    import abackup.core.backup as backup_mod

    # Spy on the real copy_tree to confirm it is invoked in plan_only mode
    # (so the plan is computed) but writes nothing to the destination.
    real_copy = backup_mod.copy_tree
    calls = {"copy": 0}

    def spy_copy_tree(source, destination, **kwargs):
        calls["copy"] += 1
        return real_copy(source, destination, **kwargs)

    monkeypatch.setattr(backup_mod, "copy_tree", spy_copy_tree)
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock, dry_run=True)
    # copy_tree is called (to compute the plan) but in plan_only mode it writes nothing.
    assert calls["copy"] == 1
    assert result.status == "success"
    assert result.manifest_path is None
    assert not (dest_dir / "out").exists()
    # Dry-run still records last_run_at/status on the updated job.
    assert result.updated_job.last_status == "success"


def test_run_job_retention_deletes_old_archives(sample_tree, dest_dir, tmp_config, tmp_data, monkeypatch):
    """RM-03: after a successful zip job, old archives beyond retention are pruned."""
    import abackup.core.backup as backup_mod

    # Make make_zip return distinct archive names so retention has something to prune.
    created = []

    def fake_make_zip(source, destination, **kwargs):
        from pathlib import Path

        p = Path(destination) / f"arc_{len(created)}.zip"
        p.write_text("x")
        created.append(p)
        return p

    monkeypatch.setattr(backup_mod, "make_zip", fake_make_zip)
    # Pre-create 4 old archives in the destination.
    for i in range(4):
        (dest_dir / f"old_{i}.zip").write_text("old")
    job = BackupJob(
        source=str(sample_tree),
        destination=str(dest_dir),
        method="zip",
        retention_count=2,
    )
    result = run_job(job, config_dir=tmp_config, data_dir=tmp_data, clock=_clock, prefer_py7zr=False)
    assert result.status == "success"
    # 4 old + 1 new = 5; retention 2 -> 3 deleted.
    deleted = result.summary.get("archives_deleted", [])
    assert len(deleted) == 3
    # Exactly 2 archives remain.
    assert len(list(dest_dir.glob("*.zip"))) == 2
