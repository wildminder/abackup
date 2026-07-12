import pytest
from textual.widgets import Input, RadioButton, Static

from abackup.cli import ABackupApp
from abackup.config import load_jobs, load_settings, save_jobs, save_settings
from abackup.models import BackupJob, Settings
from abackup.tui.screens.first_run import FirstRunScreen
from abackup.tui.screens.main_menu import MainMenuScreen
from abackup.tui.screens.run_job import RunJobScreen


async def test_first_run_wizard_creates_job_and_settings(
    tmp_config, tmp_data, sample_tree, dest_dir
):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, FirstRunScreen)
        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#zip", RadioButton).value = True
        await pilot.click("#save")
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)

        jobs = load_jobs(tmp_config)
        assert len(jobs) == 1
        assert jobs[0].method.value == "zip"
        assert load_settings(tmp_config).first_run_completed is True


async def test_first_run_wizard_rejects_missing_source(tmp_config, tmp_data, dest_dir):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.screen.query_one("#source", Input).value = str(dest_dir / "does_not_exist")
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        await pilot.click("#save")
        await pilot.pause()
        # Still on first-run screen, no job created.
        assert isinstance(app.screen, FirstRunScreen)
        assert load_jobs(tmp_config) == []


async def test_run_job_screen_updates_status(
    tmp_config, tmp_data, sample_tree, dest_dir
):
    job = BackupJob(
        source=str(sample_tree), destination=str(dest_dir / "out"), method="copy"
    )
    save_jobs([job], tmp_config)
    save_settings(Settings(first_run_completed=True), tmp_config)

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunJobScreen(tmp_config, tmp_data, job))
        await pilot.pause()
        await app.screen._worker.wait()
        await pilot.pause()
        # Job status persisted after the run completed.
        assert load_jobs(tmp_config)[0].last_status == "success"


async def test_main_menu_delete(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(
        source=str(sample_tree), destination=str(dest_dir), method="copy"
    )
    save_jobs([job], tmp_config)
    save_settings(Settings(first_run_completed=True), tmp_config)

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#delete")
        await pilot.pause()
        assert load_jobs(tmp_config) == []


async def test_main_menu_run_button(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(
        source=str(sample_tree), destination=str(dest_dir / "out"), method="copy"
    )
    save_jobs([job], tmp_config)
    save_settings(Settings(first_run_completed=True), tmp_config)

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#run")
        await pilot.pause()
        assert isinstance(app.screen, RunJobScreen)
        await app.screen._worker.wait()
        await pilot.pause()
        assert load_jobs(tmp_config)[0].last_status == "success"


async def test_main_menu_add_button(tmp_config, tmp_data):
    save_settings(Settings(first_run_completed=True), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, FirstRunScreen)
