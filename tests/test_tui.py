import pytest
from pathlib import Path
from textual.widgets import Input, RadioButton, Static, Button

from abackup.cli import ABackupApp
from abackup.config import load_jobs, load_settings, save_jobs, save_settings
from abackup.models import BackupJob, Settings
from abackup.tui.screens.first_run import FirstRunScreen
from abackup.tui.screens.main_menu import MainMenuScreen
from abackup.tui.screens.run_job import RunJobScreen
from abackup.tui.screens.run_all import RunAllScreen
from abackup.tui.screens.settings import SettingsScreen


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


async def test_main_menu_run_all_button(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(
        source=str(sample_tree), destination=str(dest_dir), method="copy"
    )
    save_jobs([job], tmp_config)
    save_settings(Settings(first_run_completed=True), tmp_config)
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
    save_settings(Settings(first_run_completed=True), tmp_config)
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
    save_settings(Settings(first_run_completed=True), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await _wait_run_all(pilot, app)
        stored = {j.id: j for j in load_jobs(tmp_config)}
        assert stored[good.id].last_status == "success"
        assert stored[bad.id].last_status == "failed"


async def test_run_all_screen_empty(tmp_config, tmp_data):
    save_settings(Settings(first_run_completed=True), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await pilot.pause()
        # No jobs -> completes immediately, no worker started.
        assert app.screen._completed is True
        assert app.screen._worker is None


async def test_run_all_screen_back_button(tmp_config, tmp_data, sample_tree, dest_dir):
    job = BackupJob(
        source=str(sample_tree), destination=str(dest_dir / "out"), method="copy"
    )
    save_jobs([job], tmp_config)
    save_settings(Settings(first_run_completed=True), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        app.push_screen(RunAllScreen(tmp_config, tmp_data))
        await _wait_run_all(pilot, app)
        await pilot.click("#back")
        await pilot.pause()
        assert isinstance(app.screen, MainMenuScreen)


async def test_main_menu_settings_button(tmp_config, tmp_data):
    save_settings(Settings(first_run_completed=True), tmp_config)
    app = ABackupApp(config_dir=tmp_config, data_dir=tmp_data)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MainMenuScreen)
        await pilot.click("#settings")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


async def test_settings_change_compression_level(tmp_config, tmp_data):
    save_settings(Settings(first_run_completed=True), tmp_config)
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


async def test_settings_validation_error_stays(tmp_config, tmp_data):
    save_settings(Settings(first_run_completed=True, zip_compression_level=6), tmp_config)
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
    save_settings(Settings(first_run_completed=True), tmp_config)
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


async def test_settings_cancel_no_change(tmp_config, tmp_data):
    save_settings(Settings(first_run_completed=True, zip_compression_level=6), tmp_config)
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
    save_settings(Settings(first_run_completed=True), tmp_config)
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
    from textual.containers import ScrollableContainer, Horizontal
    from textual.widgets import Footer

    save_settings(Settings(first_run_completed=True), tmp_config)
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
        # The resolved dir is propagated to whichever screen is shown
        # (FirstRunScreen on a fresh install, MainMenuScreen otherwise).
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
