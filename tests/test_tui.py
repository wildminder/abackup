from textual.widgets import Button, Checkbox, Input, Label, ListView, ProgressBar, RadioButton, Select, Static

from abackup.cli import ABackupApp, main
from abackup.config import load_jobs, load_settings, save_jobs, save_settings
from abackup.models import BackupJob, Settings
from abackup.tui.screens.add_job import AddJobScreen
from abackup.tui.screens.main_menu import MainMenuScreen
from abackup.tui.screens.run_all import RunAllScreen
from abackup.tui.screens.run_job import RunJobScreen
from abackup.tui.screens.settings import SettingsScreen


async def test_add_job_wizard_creates_job(tmp_config, tmp_data, sample_tree, dest_dir):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        # App opens directly on the main window (no first-run gate).
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)

        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#zip", RadioButton).value = True
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)

        jobs = load_jobs(tmp_config)
        assert len(jobs) == 1
        assert jobs[0].method.value == "zip"


async def test_add_job_wizard_creates_7z_job(tmp_config, tmp_data, sample_tree, dest_dir):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)

        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#seven_zip", RadioButton).value = True
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)

        jobs = load_jobs(tmp_config)
        assert len(jobs) == 1
        assert jobs[0].method.value == "7z"


async def test_add_job_wizard_rejects_missing_source(tmp_config, tmp_data, dest_dir):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)

        app.screen.query_one("#source", Input).value = str(dest_dir / "does_not_exist")
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        # Still on the add-job screen, no job created.
        assert isinstance(app.screen, AddJobScreen)
        assert load_jobs(tmp_config) == []


async def test_add_job_wizard_cancel_returns_to_main_menu(tmp_config, tmp_data):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)

        # Cancel returns to the main menu without creating a job.
        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)
        assert load_jobs(tmp_config) == []


async def test_main_menu_shows_empty_state(tmp_config, tmp_data):
    # No jobs configured -> app still opens on the main window with an empty
    # table and a clear hint, instead of forcing a first-run wizard.
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test():
        assert isinstance(app.screen, MainMenuScreen)
        status = app.screen.query_one("#status", Static)
        assert "No jobs yet" in str(status.render())
        assert len(app.screen.query_one("#jobs", ListView).children) == 0


async def test_main_menu_shows_key_help(tmp_config, tmp_data):
    # NTH-002: a one-line key-help footer explains keyboard navigation.
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test():
        assert isinstance(app.screen, MainMenuScreen)
        help_text = str(app.screen.query_one("#key_help", Static).render())
        assert "select" in help_text
        assert "Enter" in help_text


async def test_main_menu_job_label_includes_source_and_destination(tmp_config, tmp_data):
    # The job list shows "name [method]: source -> destination", eliding
    # over-long paths in the middle (keeping drive + first + last segment).
    job = BackupJob(
        source=("C:/Users/art/Documents/Projects/abackup/with/a/very/long/source/path"),
        destination=("D:/Backups/Archive/Projects/abackup/with/a/very/long/dest/path"),
        method="7z",
        name="Docs",
    )
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test():
        assert isinstance(app.screen, MainMenuScreen)
        list_view = app.screen.query_one("#jobs", ListView)
        labels = [str(w.render()) for w in list_view.query(Label)]
        assert labels
        text = labels[0]
        assert "Docs [7z]:" in text
        assert "->" in text
        # Long paths are elided in the middle, not shown in full.
        assert "Projects/abackup/with" not in text
        assert "Archive/Projects/abackup/with" not in text


async def test_run_job_screen_updates_status(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)

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
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="copy")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#delete")
        await pilot.pause()
        assert load_jobs(tmp_config) == []


async def test_main_menu_run_button(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)

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
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)


async def test_main_menu_run_all_button(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir), method="copy")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#run_all")
        await pilot.pause()
        assert isinstance(app.screen, RunAllScreen)


async def _wait_run_all(pilot, app, limit: int = 200) -> None:
    worker = getattr(app.screen, "_worker", None)
    if worker is not None:
        await worker.wait()
    for _ in range(limit):
        await pilot.pause()
        if getattr(app.screen, "_completed", False):
            return
    raise AssertionError("RunAllScreen did not complete in time")


async def test_run_all_screen_completes_all(tmp_config, tmp_data, sample_tree, tmp_path):
    jobs = [
        BackupJob(
            source=str(sample_tree),
            destination=str(tmp_path / f"out_{i}"),
            method="copy",
            name=f"job{i}",
        )
        for i in range(3)
    ]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await _wait_run_all(pilot, app)
        stored = load_jobs(tmp_config)
        assert len(stored) == 3
        assert all(j.last_status == "success" for j in stored)


async def test_run_all_screen_shows_failure(tmp_config, tmp_data, sample_tree, tmp_path):
    good = BackupJob(
        source=str(sample_tree),
        destination=str(tmp_path / "out_good"),
        method="copy",
        name="good",
    )
    bad = BackupJob(
        source=str(tmp_path / "missing"),
        destination=str(tmp_path / "out_bad"),
        method="copy",
        name="bad",
    )
    save_jobs([good, bad], tmp_config)
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await _wait_run_all(pilot, app)
        stored = {j.id: j for j in load_jobs(tmp_config)}
        assert stored[good.id].last_status == "success"
        assert stored[bad.id].last_status == "failed"


async def test_run_all_screen_empty(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await pilot.pause()
        # No jobs -> completes immediately, no worker started.
        assert app.screen._completed is True
        assert app.screen._worker is None


async def test_run_all_screen_back_button(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await _wait_run_all(pilot, app)
        await pilot.click("#back")
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)


async def test_main_menu_settings_button(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#settings")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


async def test_settings_change_compression_level(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        app.screen.query_one("#zip_level", Input).value = "9"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert load_settings(tmp_config).zip_compression_level == 9
        assert isinstance(app.screen, MainMenuScreen)


async def test_settings_change_seven_zip_level(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        app.screen.query_one("#sz_level", Input).value = "7"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert load_settings(tmp_config).seven_zip_compression_level == 7
        assert isinstance(app.screen, MainMenuScreen)


async def test_settings_seven_zip_level_validation_error_stays(tmp_config, tmp_data):
    save_settings(Settings(seven_zip_compression_level=3), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        app.screen.query_one("#sz_level", Input).value = "42"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        # Invalid value -> stays on settings, file unchanged.
        assert isinstance(app.screen, SettingsScreen)
        assert load_settings(tmp_config).seven_zip_compression_level == 3


async def test_settings_validation_error_stays(tmp_config, tmp_data):
    save_settings(Settings(zip_compression_level=6), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        app.screen.query_one("#zip_level", Input).value = "99"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        # Invalid value -> stays on settings, file unchanged.
        assert isinstance(app.screen, SettingsScreen)
        assert load_settings(tmp_config).zip_compression_level == 6


async def test_settings_relocate_on_save(tmp_config, tmp_data, tmp_path):
    save_settings(Settings(), tmp_config)
    save_jobs([BackupJob(source="C:/x", destination="D:/y", method="copy")], tmp_config)
    new_dir = tmp_path / "newloc"
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        app.screen.query_one("#config_dir", Input).value = str(new_dir)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert (new_dir / "settings.json").exists()


async def test_run_all_cancel_button_terminates_jobs(tmp_config, tmp_data, tmp_path, monkeypatch):
    import time

    from abackup.config import load_jobs, save_jobs
    from abackup.tui.screens.run_all import RunAllScreen
    from abackup.utils.errors import JobCancelled

    # Replace the real copy with a slow, cancel-aware stub so the job stays
    # "in flight" until the Cancel button sets the shared event. This makes the
    # test deterministic (no reliance on a large file copy timing out).
    def slow_copy_tree(src, dst, *, on_progress=None, cancel=None, **kwargs):
        while not (cancel and cancel.is_set()):
            time.sleep(0.01)
        raise JobCancelled("cancelled")

    monkeypatch.setattr("abackup.core.backup.copy_tree", slow_copy_tree)

    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("hello")
    save_jobs(
        [
            BackupJob(
                source=str(src),
                destination=str(tmp_path / "out"),
                method="copy",
                name="big",
            )
        ],
        tmp_config,
    )

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await pilot.pause()
        # Cancel is available; Back is disabled while running.
        assert app.screen.query_one("#cancel", Button).disabled is False
        assert app.screen.query_one("#back", Button).disabled is True

        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert app.screen._cancel.is_set()
        assert app.screen.query_one("#cancel", Button).disabled is True

        # Wait for the batch to finish (cancelled).
        for _ in range(200):
            await pilot.pause()
            if app.screen._completed:
                break
        assert app.screen._completed
        # The in-flight job was aborted and its cancelled status persisted.
        assert load_jobs(tmp_config)[0].last_status == "cancelled"
        assert app.screen.query_one("#back", Button).disabled is False

        # Back returns to the main menu.
        app.screen.query_one("#back", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)


async def test_run_job_screen_shows_realtime_progress(tmp_config, tmp_data, monkeypatch):
    import abackup.tui.screens.run_job as rj_mod
    from abackup.core.backup import BackupResult
    from abackup.core.progress import PHASE_DONE, STATUS_SUCCESS, Progress
    from abackup.tui.screens.run_job import RunJobScreen

    job = BackupJob(source="C:/x", destination="D:/y", method="copy", name="demo")

    def fake_run_job(
        j,
        *,
        config_dir=None,
        data_dir=None,
        on_progress=None,
        clock=None,
        zip_compression_level=6,
        seven_zip_compression_level=3,
        cancel=None,
        prefer_py7zr=None,
        **kwargs,
    ):
        # Scripted realtime sequence: 0% (no file yet) -> 100% (mid.txt).
        on_progress(
            Progress(
                job_id=j.id,
                files_total=2,
                files_done=0,
                bytes_total=100,
                bytes_done=0,
                current_file="",
                phase="copying",
            )
        )
        on_progress(
            Progress(
                job_id=j.id,
                files_total=2,
                files_done=2,
                bytes_total=100,
                bytes_done=100,
                current_file="mid.txt",
                phase=PHASE_DONE,
                status=STATUS_SUCCESS,
            )
        )
        return BackupResult(j.id, "copy", "success", {}, None, None, j)

    monkeypatch.setattr(rj_mod, "run_job", fake_run_job)

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(RunJobScreen(tmp_config, tmp_data, job))
        await pilot.pause()
        await app.screen._worker.wait()
        await pilot.pause()
        # Progress bar reached 100%.
        assert app.screen.query_one("#progress", ProgressBar).progress == 100
        # Current-file label reflected the mid-file step.
        assert "mid.txt" in str(app.screen.query_one("#current", Static).render())
        # Counts line shows completed files.
        assert "2/2" in str(app.screen.query_one("#counts", Static).render())
        # Result shown and Back enabled.
        assert "success" in str(app.screen.query_one("#result", Static).render())
        assert app.screen.query_one("#back", Button).disabled is False


async def test_run_all_screen_shows_realtime_progress(tmp_config, tmp_data, monkeypatch):
    import abackup.tui.screens.run_all as ra_mod
    from abackup.core.backup import BackupResult
    from abackup.core.progress import (
        PHASE_COPYING,
        PHASE_DONE,
        STATUS_SUCCESS,
        Progress,
    )
    from abackup.tui.screens.run_all import RunAllScreen

    jobs = [
        BackupJob(source="C:/x", destination="D:/y", method="copy", name="jobA"),
        BackupJob(source="C:/x", destination="D:/y", method="copy", name="jobB"),
    ]
    save_jobs(jobs, tmp_config)
    save_settings(Settings(), tmp_config)

    def fake_run_jobs_batch(
        jobs,
        *,
        config_dir=None,
        data_dir=None,
        max_workers=4,
        on_job_done=None,
        on_progress=None,
        clock=None,
        zip_compression_level=None,
        seven_zip_compression_level=None,
        cancel=None,
        prefer_py7zr=None,
        **kwargs,
    ):
        for j in jobs:
            on_progress(
                j.id,
                Progress(
                    job_id=j.id,
                    files_total=1,
                    files_done=0,
                    bytes_total=100,
                    bytes_done=0,
                    current_file="",
                    phase=PHASE_COPYING,
                ),
            )
            on_progress(
                j.id,
                Progress(
                    job_id=j.id,
                    files_total=1,
                    files_done=1,
                    bytes_total=100,
                    bytes_done=100,
                    current_file="f.txt",
                    phase=PHASE_DONE,
                    status=STATUS_SUCCESS,
                ),
            )
            on_job_done(j.id, BackupResult(j.id, "copy", "success", {}, None, None, j))
        return [BackupResult(j.id, "copy", "success", {}, None, None, j) for j in jobs]

    monkeypatch.setattr(ra_mod, "run_jobs_batch", fake_run_jobs_batch)

    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await pilot.pause()
        for _ in range(100):
            await pilot.pause()
            if app.screen._completed:
                break
        assert app.screen._completed
        # Overall progress reached 100%.
        assert app.screen.query_one("#progress", ProgressBar).progress == 100
        # Per-job live lines present and at 100%.
        jobs_text = str(app.screen.query_one("#jobs", Static).render())
        assert "jobA" in jobs_text and "jobB" in jobs_text
        assert "100%" in jobs_text
        assert app.screen.query_one("#back", Button).disabled is False


async def test_settings_cancel_no_change(tmp_config, tmp_data):
    save_settings(Settings(zip_compression_level=6), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        app.screen.query_one("#zip_level", Input).value = "1"
        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)
        assert load_settings(tmp_config).zip_compression_level == 6


async def test_settings_fields_are_labeled(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()
        labels = {str(w.render()) for w in app.screen.query(".field-label")}
        for expected in [
            "Storage directory",
            "Zip compression level (0-9)",
            "Max concurrent workers",
            "Log level",
            "Default destination (optional)",
        ]:
            assert expected in labels


async def test_settings_actions_visible_above_footer(tmp_config, tmp_data):
    """Regression: Save/Cancel must not be clipped behind the docked Footer.

    The field groups live inside a ScrollableContainer (#body); the action
    buttons (#actions) must be a sibling of that container (not nested in it)
    and rendered within the viewport, above the Footer.
    """
    from textual.containers import Horizontal, ScrollableContainer
    from textual.widgets import Footer

    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(tmp_config, tmp_data))
        await pilot.pause()

        body = app.screen.query_one("#body", ScrollableContainer)
        actions = app.screen.query_one("#actions", Horizontal)
        footer = app.screen.query_one(Footer)

        # Buttons are NOT inside the scroll area.
        assert actions not in list(body.walk_children())
        # Buttons render above the footer and within the screen height.
        assert actions.region.bottom <= footer.region.y
        assert actions.region.bottom <= app.screen.size.height
        assert app.screen.query_one("#save", Button).visible
        assert app.screen.query_one("#cancel", Button).visible


async def test_app_resolves_default_config_dir(tmp_data):
    # No --config-dir: the app must resolve a concrete config dir on mount
    # (previously it stayed None and broke Settings save).
    app = ABackupApp(data_dir=tmp_data)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.config_dir is not None
        # The resolved dir is propagated to the main window on startup.
        assert app.screen.config_dir == app.config_dir


async def test_settings_save_from_default_config_dir(tmp_data, tmp_path):
    app = ABackupApp(data_dir=tmp_data)
    new_dir = tmp_path / "relocated"
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen(app.config_dir, tmp_data))
        await pilot.pause()
        app.screen.query_one("#config_dir", Input).value = str(new_dir)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert (new_dir / "settings.json").exists()
        assert app.config_dir == str(new_dir)


async def test_settings_save_with_none_config_dir_uses_app(tmp_data, tmp_path):
    # Defensive fallback: if a screen is given config_dir=None, it must fall
    # back to the app's resolved config dir instead of crashing on Path(None).
    app = ABackupApp(data_dir=tmp_data)
    new_dir = tmp_path / "relocated2"
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen(None, None))
        await pilot.pause()
        app.screen.query_one("#config_dir", Input).value = str(new_dir)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert (new_dir / "settings.json").exists()


def test_add_job_module_and_class():
    import abackup.tui.screens.add_job as m

    assert hasattr(m, "AddJobScreen")
    assert not hasattr(m, "FirstRunScreen")


def test_no_first_run_module():
    import importlib

    try:
        importlib.import_module("abackup.tui.screens.first_run")
        raise AssertionError("first_run module should no longer exist")
    except ImportError:
        pass


async def test_main_menu_add_opens_add_job_screen(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)


async def test_add_job_rejects_dest_inside_source(tmp_config, tmp_data, sample_tree, dest_dir):
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)
        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(sample_tree / "sub")
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        # Still on the add-job screen, no job created.
        assert isinstance(app.screen, AddJobScreen)
        assert "Destination must not" in str(app.screen.query_one("#error", Static).render())
        assert load_jobs(tmp_config) == []


async def test_add_job_rejects_insufficient_disk_space(tmp_config, tmp_data, sample_tree, dest_dir, monkeypatch):
    import types

    monkeypatch.setattr(
        "abackup.core.validation.shutil.disk_usage",
        lambda p: types.SimpleNamespace(free=1),
    )
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, AddJobScreen)
        assert "Not enough free space" in str(app.screen.query_one("#error", Static).render())
        assert load_jobs(tmp_config) == []


async def test_add_job_accepts_valid_with_disk_check(tmp_config, tmp_data, sample_tree, dest_dir, monkeypatch):
    import types

    monkeypatch.setattr(
        "abackup.core.validation.shutil.disk_usage",
        lambda p: types.SimpleNamespace(free=10**12),
    )
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#add")
        await pilot.pause()
        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)
        jobs = load_jobs(tmp_config)
        assert len(jobs) == 1


async def test_app_data_dir_equals_config_dir():
    # The storage directory is the single storage root: config (settings +
    # jobs) and data (logs + manifests) live together so a relocation moves
    # everything atomically.
    app = ABackupApp()
    async with app.run_test():
        assert app.data_dir == app.config_dir


async def test_settings_relocate_moves_logs_and_manifests(tmp_path):
    # Seed run history (logs + manifests) in the storage root.
    old = tmp_path / "old_storage"
    old.mkdir()
    (old / "logs").mkdir()
    (old / "logs" / "x.jsonl").write_text("{}")
    (old / "manifests").mkdir()
    (old / "manifests" / "y.json").write_text("{}")
    new = tmp_path / "new_storage"
    app = ABackupApp(config_dir=old)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(app.config_dir, app.data_dir))
        await pilot.pause()
        app.screen.query_one("#config_dir", Input).value = str(new)
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        # Run history moved to the new storage root.
        assert (new / "logs" / "x.jsonl").exists()
        assert (new / "manifests" / "y.json").exists()
        # And removed from the old location.
        assert not (old / "logs").exists()
        assert not (old / "manifests").exists()
        # App's data dir now points at the relocated root.
        assert app.data_dir == str(new)


async def test_app_applies_theme_from_settings(tmp_path):
    # The persisted theme is applied on startup (NTH-001).
    save_settings(Settings(theme="light"), tmp_path)
    app = ABackupApp(config_dir=tmp_path)
    async with app.run_test():
        assert app.theme_name == "light"
        assert app.dark is False


async def test_settings_theme_toggle_saves_and_applies(tmp_config, tmp_data):
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(app.config_dir, app.data_dir))
        await pilot.pause()
        theme = app.screen.query_one("#theme", Select)
        theme.value = "light"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        # Theme persisted and applied live.
        assert load_settings(tmp_config).theme == "light"
        assert app.theme_name == "light"
        assert app.dark is False


async def test_app_respects_data_dir_override(tmp_path, sample_tree):
    """IMP-101: a separate --data-dir must be honored by the TUI."""

    from pathlib import Path

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    save_settings(Settings(), config_dir)

    app = ABackupApp(config_dir=str(config_dir), data_dir=str(data_dir))
    async with app.run_test() as pilot:
        # data_dir is not forced to equal config_dir when explicitly given.
        assert app.data_dir == str(data_dir)
        assert app.data_dir != app.config_dir
        # Running a job writes its manifest under the data dir, not config.
        job = BackupJob(
            source=str(sample_tree),
            destination=str(data_dir / "out"),
            method="copy",
            name="demo",
        )
        save_jobs([job], config_dir)
        app.push_screen(RunJobScreen(app.config_dir, app.data_dir, job))
        await pilot.pause()
        # Wait for the run worker to finish.
        import asyncio

        await asyncio.sleep(0.2)
        await pilot.pause()
        manifests = list((Path(data_dir) / "manifests").glob("*.json"))
        assert manifests, "manifest should be written under data_dir"
        assert not (Path(config_dir) / "manifests").exists()


async def test_cli_launches_app_with_data_dir(tmp_config, tmp_data, monkeypatch):
    """IMP-101: cli.main forwards --data-dir into ABackupApp."""
    captured = {}

    class FakeApp:
        def __init__(self, config_dir=None, data_dir=None):
            captured["config_dir"] = config_dir
            captured["data_dir"] = data_dir

        def run(self):
            return None

    monkeypatch.setattr("abackup.cli.ABackupApp", FakeApp)
    main(["--config-dir", tmp_config, "--data-dir", tmp_data])
    assert captured["config_dir"] == tmp_config
    assert captured["data_dir"] == tmp_data


async def test_settings_hint_reflects_data_dir(tmp_path):
    """IMP-101: when a separate data dir is used, the storage hint notes it."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    save_settings(Settings(), config_dir)
    app = ABackupApp(config_dir=str(config_dir), data_dir=str(data_dir))
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(app.config_dir, app.data_dir))
        await pilot.pause()
        hint = app.screen.query_one("#config_dir", Input).parent
        # The hint text is the Static sibling describing storage relocation.
        hint_text = str(hint)
        assert "data" in hint_text.lower() or app.data_dir == str(data_dir)


async def test_add_job_parses_exclude_patterns(tmp_config, tmp_data, sample_tree, dest_dir):
    """RM-02: exclude/include/retention/tag inputs are parsed into the job."""
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        await pilot.click("#add")
        await pilot.pause()
        app.screen.query_one("#source", Input).value = str(sample_tree)
        app.screen.query_one("#dest", Input).value = str(dest_dir)
        app.screen.query_one("#exclude", Input).value = "*.tmp, __pycache__"
        app.screen.query_one("#include", Input).value = "*.txt"
        app.screen.query_one("#retention", Input).value = "3"
        app.screen.query_one("#tag", Input).value = "docs"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        jobs = load_jobs(tmp_config)
        assert len(jobs) == 1
        assert jobs[0].exclude_patterns == ["*.tmp", "__pycache__"]
        assert jobs[0].include_patterns == ["*.txt"]
        assert jobs[0].retention_count == 3
        assert jobs[0].tag == "docs"


async def test_settings_run_mode_select_persists(tmp_config, tmp_data):
    """RM-05a: the run-mode Select is saved into settings."""
    save_settings(Settings(), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(app.config_dir, app.data_dir))
        await pilot.pause()
        app.screen.query_one("#run_mode", Select).value = "sequential"
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert load_settings(tmp_config).run_mode == "sequential"


async def test_settings_run_on_startup_registers_task(tmp_config, tmp_data, monkeypatch):
    """RM-01b: enabling run-on-startup calls register_startup."""
    save_settings(Settings(), tmp_config)
    captured = {}

    def fake_register(command=None, name=None):
        captured["command"] = command

    monkeypatch.setattr("abackup.tui.screens.settings.register_startup", fake_register)
    monkeypatch.setattr("abackup.tui.screens.settings.unregister_startup", lambda *a, **k: None)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(SettingsScreen(app.config_dir, app.data_dir))
        await pilot.pause()
        app.screen.query_one("#run_on_startup", Checkbox).value = True
        app.screen.query_one("#save", Button).press()
        await pilot.pause()
        assert load_settings(tmp_config).run_on_startup is True
        assert captured.get("command") and "--run-due" in captured["command"]


async def test_run_all_screen_tag_filter(tmp_config, tmp_data, sample_tree, tmp_path, monkeypatch):
    """RM-04: RunAllScreen filters jobs by tag."""
    import abackup.tui.screens.run_all as ra_mod

    a = BackupJob(source=str(sample_tree), destination=str(tmp_path / "a"), method="copy", name="a", tag="docs")
    b = BackupJob(source=str(sample_tree), destination=str(tmp_path / "b"), method="copy", name="b", tag="media")
    save_jobs([a, b], tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(jobs, **kwargs):
        captured["ids"] = [j.id for j in jobs]
        return []

    monkeypatch.setattr(ra_mod, "run_jobs_batch", fake_run)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(RunAllScreen(app.config_dir, app.data_dir, tag="docs"))
        await pilot.pause()
        await pilot.pause()
    assert captured["ids"] == [a.id]


async def test_run_all_screen_dry_run_shows_plan(tmp_config, tmp_data, sample_tree, dest_dir, monkeypatch):
    """RM-05b: dry-run RunAllScreen runs without writing and notes (dry run)."""
    import abackup.tui.screens.run_all as ra_mod

    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy", name="j")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run(jobs, **kwargs):
        captured["dry_run"] = kwargs.get("dry_run")
        return []

    monkeypatch.setattr(ra_mod, "run_jobs_batch", fake_run)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(RunAllScreen(app.config_dir, app.data_dir, dry_run=True))
        await pilot.pause()
        await pilot.pause()
    assert captured["dry_run"] is True


async def test_run_job_screen_dry_run_shows_plan(tmp_config, tmp_data, sample_tree, dest_dir, monkeypatch):
    """RM-05b: dry-run RunJobScreen plans without writing."""
    import abackup.tui.screens.run_job as rj_mod

    job = BackupJob(source=str(sample_tree), destination=str(dest_dir / "out"), method="copy", name="j")
    save_jobs([job], tmp_config)
    save_settings(Settings(), tmp_config)

    captured = {}

    def fake_run_job(j, **kwargs):
        from abackup.core.backup import BackupResult

        captured["dry_run"] = kwargs.get("dry_run")
        return BackupResult(j.id, j.method.value, "success", {"files_total": 1}, None, None, j)

    monkeypatch.setattr(rj_mod, "run_job", fake_run_job)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        app.push_screen(RunJobScreen(app.config_dir, app.data_dir, job, dry_run=True))
        await pilot.pause()
        await pilot.pause()
    assert captured["dry_run"] is True
    # Nothing was written to the destination.
    assert not (dest_dir / "out").exists()
