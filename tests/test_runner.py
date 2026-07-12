from pathlib import Path

from abackup.config import load_jobs
from abackup.core.runner import run_jobs_batch
from abackup.models import BackupJob


def _make_job(i, source, base_dest):
    return BackupJob(
        source=str(source),
        destination=str(base_dest / f"out_{i}"),
        method="copy",
        name=f"job{i}",
    )


def test_empty_returns_empty(tmp_config, tmp_data):
    assert run_jobs_batch([], config_dir=tmp_config, data_dir=tmp_data) == []


def test_sequential_order_max_workers_1(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [
        _make_job(0, sample_tree, tmp_path / "d0"),
        _make_job(1, sample_tree, tmp_path / "d1"),
        _make_job(2, sample_tree, tmp_path / "d2"),
    ]
    results = run_jobs_batch(
        jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=1
    )
    assert [r.job_id for r in results] == [j.id for j in jobs]
    assert all(r.status == "success" for r in results)


def test_concurrent_all_complete(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [
        _make_job(i, sample_tree, tmp_path / f"d{i}") for i in range(3)
    ]
    results = run_jobs_batch(
        jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=3
    )
    assert {r.job_id for r in results} == {j.id for j in jobs}
    assert all(r.status == "success" for r in results)


def test_failure_isolation(sample_tree, tmp_path, tmp_config, tmp_data):
    good = [
        _make_job(0, sample_tree, tmp_path / "d0"),
        _make_job(1, sample_tree, tmp_path / "d1"),
    ]
    bad = BackupJob(
        source=str(tmp_path / "missing"),
        destination=str(tmp_path / "d2" / "out"),
        method="copy",
        name="bad",
    )
    jobs = [good[0], bad, good[1]]
    results = run_jobs_batch(
        jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=2
    )
    assert len(results) == 3
    by_id = {r.job_id: r for r in results}
    assert by_id[bad.id].status == "failed"
    assert by_id[good[0].id].status == "success"
    assert by_id[good[1].id].status == "success"


def test_on_job_done_called_per_job(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [_make_job(i, sample_tree, tmp_path / f"d{i}") for i in range(4)]
    seen = []
    run_jobs_batch(
        jobs,
        config_dir=tmp_config,
        data_dir=tmp_data,
        max_workers=2,
        on_job_done=lambda jid, r: seen.append(jid),
    )
    assert sorted(seen) == sorted(j.id for j in jobs)


def test_per_job_status_persisted(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [_make_job(i, sample_tree, tmp_path / f"d{i}") for i in range(3)]
    run_jobs_batch(jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=2)
    stored = load_jobs(tmp_config)
    assert {j.id for j in stored} == {j.id for j in jobs}
    assert all(j.last_status == "success" for j in stored)


def test_queue_backpressure_many_jobs(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [_make_job(i, sample_tree, tmp_path / f"d{i}") for i in range(20)]
    results = run_jobs_batch(
        jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=2
    )
    assert len(results) == 20
    assert all(r.status == "success" for r in results)


def test_concurrent_writes_no_corruption(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [_make_job(i, sample_tree, tmp_path / f"d{i}") for i in range(10)]
    run_jobs_batch(jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=4)
    stored = load_jobs(tmp_config)
    assert len(stored) == 10
    assert all(j.last_status == "success" for j in stored)
    leftovers = list(Path(tmp_config).glob("*.tmp"))
    assert leftovers == []


def test_no_tmp_leftovers_after_batch(sample_tree, tmp_path, tmp_config, tmp_data):
    jobs = [_make_job(i, sample_tree, tmp_path / f"d{i}") for i in range(5)]
    run_jobs_batch(jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=3)
    assert list(Path(tmp_config).glob("*.tmp")) == []


def test_run_jobs_batch_passes_level_from_settings(
    sample_tree, tmp_path, tmp_config, tmp_data, monkeypatch
):
    from abackup.config import save_settings
    from abackup.models import Settings

    import abackup.core.runner as runner_mod

    save_settings(Settings(zip_compression_level=2), tmp_config)
    captured = []
    real_run_job = runner_mod.run_job

    def spy(
        job,
        *,
        config_dir=None,
        data_dir=None,
        on_progress=None,
        clock=None,
        zip_compression_level=6,
    ):
        captured.append(zip_compression_level)
        return real_run_job(
            job,
            config_dir=config_dir,
            data_dir=data_dir,
            on_progress=on_progress,
            clock=clock,
            zip_compression_level=zip_compression_level,
        )

    monkeypatch.setattr(runner_mod, "run_job", spy)
    jobs = [_make_job(0, sample_tree, tmp_path / "d0")]
    run_jobs_batch(jobs, config_dir=tmp_config, data_dir=tmp_data, max_workers=1)
    assert captured == [2]


def test_run_jobs_batch_explicit_level_overrides_settings(
    sample_tree, tmp_path, tmp_config, tmp_data, monkeypatch
):
    from abackup.config import save_settings
    from abackup.models import Settings

    import abackup.core.runner as runner_mod

    save_settings(Settings(zip_compression_level=2), tmp_config)
    captured = []
    real_run_job = runner_mod.run_job

    def spy(
        job,
        *,
        config_dir=None,
        data_dir=None,
        on_progress=None,
        clock=None,
        zip_compression_level=6,
    ):
        captured.append(zip_compression_level)
        return real_run_job(
            job,
            config_dir=config_dir,
            data_dir=data_dir,
            on_progress=on_progress,
            clock=clock,
            zip_compression_level=zip_compression_level,
        )

    monkeypatch.setattr(runner_mod, "run_job", spy)
    jobs = [_make_job(0, sample_tree, tmp_path / "d0")]
    run_jobs_batch(
        jobs,
        config_dir=tmp_config,
        data_dir=tmp_data,
        max_workers=1,
        zip_compression_level=7,
    )
    assert captured == [7]
