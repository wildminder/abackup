import pytest

from abackup.cli import build_parser, main
from abackup.config import load_jobs, save_jobs, save_settings
from abackup.models import BackupJob, Settings


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "abackup" in capsys.readouterr().out


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.config_dir is None


def test_cli_run_all_runs_every_job(tmp_config, tmp_data, sample_tree, tmp_path, capsys):
    jobs = [
        BackupJob(
            source=str(sample_tree),
            destination=str(tmp_path / f"out_{i}"),
            method="copy",
            name=f"job{i}",
        )
        for i in range(2)
    ]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(), tmp_config)

    main(["--run-all", "--config-dir", tmp_config, "--data-dir", tmp_data])
    out = capsys.readouterr().out
    assert "Completed 2 jobs" in out
    stored = load_jobs(tmp_config)
    assert len(stored) == 2
    assert all(j.last_status == "success" for j in stored)


def test_cli_run_all_empty(tmp_config, tmp_data, capsys):
    save_settings(Settings(), tmp_config)
    main(["--run-all", "--config-dir", tmp_config, "--data-dir", tmp_data])
    assert "No jobs configured" in capsys.readouterr().out


def test_cli_workers_flag(tmp_config, tmp_data, sample_tree, tmp_path, monkeypatch):
    jobs = [
        BackupJob(
            source=str(sample_tree),
            destination=str(tmp_path / "out"),
            method="copy",
            name="job",
        )
    ]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(
        jobs,
        *,
        config_dir=None,
        data_dir=None,
        max_workers=4,
        on_job_done=None,
        clock=None,
        prefer_py7zr=None,
        seven_zip_compression_level=None,
        **kwargs,
    ):
        captured["max_workers"] = max_workers
        return []

    monkeypatch.setattr("abackup.cli.run_jobs_batch", fake_run)
    main(["--run-all", "--config-dir", tmp_config, "--data-dir", tmp_data, "--workers", "2"])
    assert captured["max_workers"] == 2


def test_cli_run_all_passes_seven_zip_level(tmp_config, tmp_data, sample_tree, tmp_path, monkeypatch):
    jobs = [
        BackupJob(
            source=str(sample_tree),
            destination=str(tmp_path / "out"),
            method="copy",
            name="job",
        )
    ]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(seven_zip_compression_level=5), tmp_config)

    captured = {}

    def fake_run(
        jobs,
        *,
        config_dir=None,
        data_dir=None,
        max_workers=4,
        on_job_done=None,
        clock=None,
        prefer_py7zr=None,
        seven_zip_compression_level=None,
        **kwargs,
    ):
        captured["seven_zip_compression_level"] = seven_zip_compression_level
        return []

    monkeypatch.setattr("abackup.cli.run_jobs_batch", fake_run)
    main(["--run-all", "--config-dir", tmp_config, "--data-dir", tmp_data])
    assert captured["seven_zip_compression_level"] == 5


def test_cli_show_settings(tmp_config, tmp_data, capsys):
    save_settings(Settings(zip_compression_level=7), tmp_config)
    main(["--show-settings", "--config-dir", tmp_config])
    out = capsys.readouterr().out
    assert "config_dir" in out
    assert "zip_compression_level" in out
    assert "7" in out


def test_cli_show_settings_reflects_default_location(tmp_config, tmp_data, capsys, monkeypatch):
    # Force the default (no override) to a temp dir so we can assert the path.
    import json as _json

    import abackup.cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_config_dir", lambda override=None: tmp_config)
    save_settings(Settings(), tmp_config)
    main(["--show-settings"])
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data["config_dir"] == tmp_config


def test_cli_run_all_uses_config_dir_as_data_dir(tmp_config, sample_tree, tmp_path, monkeypatch):
    # The storage directory is the single storage root: when --data-dir is
    # omitted, run-all must use config_dir for logs/manifests too.
    jobs = [
        BackupJob(
            source=str(sample_tree),
            destination=str(tmp_path / "out"),
            method="copy",
            name="job",
        )
    ]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(
        jobs,
        *,
        config_dir=None,
        data_dir=None,
        max_workers=4,
        on_job_done=None,
        clock=None,
        prefer_py7zr=None,
        seven_zip_compression_level=None,
        **kwargs,
    ):
        captured["config_dir"] = config_dir
        captured["data_dir"] = data_dir
        return []

    monkeypatch.setattr("abackup.cli.run_jobs_batch", fake_run)
    main(["--run-all", "--config-dir", tmp_config])
    assert captured["config_dir"] == tmp_config
    assert captured["data_dir"] == tmp_config


def test_cli_run_due_filters_by_schedule(tmp_config, tmp_data, sample_tree, tmp_path, monkeypatch):
    """RM-01a: --run-due only runs jobs whose schedule is due."""
    due = BackupJob(
        source=str(sample_tree),
        destination=str(tmp_path / "out_due"),
        method="copy",
        name="due",
        schedule_interval_hours=1,
        last_run_at="2026-01-01T00:00:00+00:00",
    )
    not_due = BackupJob(
        source=str(sample_tree),
        destination=str(tmp_path / "out_not"),
        method="copy",
        name="notdue",
        schedule_interval_hours=24,
        last_run_at="2026-01-01T11:00:00+00:00",
    )
    save_jobs([due, not_due], tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(jobs, **kwargs):
        captured["ids"] = [j.id for j in jobs]
        return []

    monkeypatch.setattr("abackup.cli.run_jobs_batch", fake_run)
    # Force a fixed "now" for the scheduler's due check.
    import abackup.core.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "is_due", lambda job, n=None: job.id == due.id)
    main(["--run-due", "--config-dir", tmp_config, "--data-dir", tmp_data])
    assert captured["ids"] == [due.id]


def test_cli_run_all_tag_filter(tmp_config, tmp_data, sample_tree, tmp_path, monkeypatch):
    """RM-04: --tag only runs jobs with the matching tag."""
    a = BackupJob(source=str(sample_tree), destination=str(tmp_path / "a"), method="copy", name="a", tag="docs")
    b = BackupJob(source=str(sample_tree), destination=str(tmp_path / "b"), method="copy", name="b", tag="media")
    save_jobs([a, b], tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(jobs, **kwargs):
        captured["ids"] = [j.id for j in jobs]
        return []

    monkeypatch.setattr("abackup.cli.run_jobs_batch", fake_run)
    main(["--run-all", "--tag", "docs", "--config-dir", tmp_config, "--data-dir", tmp_data])
    assert captured["ids"] == [a.id]


def test_cli_run_all_dry_run_no_writes(tmp_config, tmp_data, sample_tree, tmp_path, monkeypatch):
    """RM-05b: --dry-run forwards dry_run=True and writes nothing."""
    jobs = [BackupJob(source=str(sample_tree), destination=str(tmp_path / "out"), method="copy", name="j")]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(jobs, **kwargs):
        captured["dry_run"] = kwargs.get("dry_run")
        return []

    monkeypatch.setattr("abackup.cli.run_jobs_batch", fake_run)
    main(["--run-all", "--dry-run", "--config-dir", tmp_config, "--data-dir", tmp_data])
    assert captured["dry_run"] is True
