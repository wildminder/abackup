"""Run-job screen with realtime progress (bar + current file + counts)."""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import ProgressBar, Static, Button

from abackup.config import load_jobs, save_jobs, load_settings
from abackup.core.backup import run_job
from abackup.core.paths import shorten_path
from abackup.core.progress import Progress
from abackup.models import BackupJob


class RunJobScreen(Screen):
    def __init__(self, config_dir, data_dir, job: BackupJob):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.job = job

    def compose(self):
        yield Static(f"Running backup: {self.job.name}", id="title")
        yield ProgressBar(total=100, id="progress")
        yield Static("", id="current")
        yield Static("", id="counts")
        yield Static("", id="result")
        yield Button("Back", id="back")

    def on_mount(self) -> None:
        self._worker = self.run_worker(self._run())

    async def _run(self) -> None:
        def on_progress(p: Progress) -> None:
            self.query_one("#progress", ProgressBar).update(progress=p.percent())
            self.query_one("#current", Static).update(
                f"Current: {shorten_path(p.current_file, self.job.source)}"
                if p.current_file
                else ""
            )
            mb_done = p.bytes_done / (1024 * 1024)
            mb_total = p.bytes_total / (1024 * 1024)
            self.query_one("#counts", Static).update(
                f"Files {p.files_done}/{p.files_total} · "
                f"{mb_done:.1f}/{mb_total:.1f} MB"
            )

        settings = load_settings(self.config_dir)
        result = run_job(
            self.job,
            config_dir=self.config_dir,
            data_dir=self.data_dir,
            prefer_py7zr=settings.prefer_py7zr,
            seven_zip_compression_level=settings.seven_zip_compression_level,
            on_progress=on_progress,
        )
        self.query_one("#progress", ProgressBar).update(progress=100)
        self.query_one("#result", Static).update(
            f"Status: {result.status}\n{result.summary}"
        )
        # Persist updated job status.
        jobs = load_jobs(self.config_dir)
        if result.updated_job is not None:
            from abackup.core.jobs import upsert_job

            save_jobs(upsert_job(jobs, result.updated_job), self.config_dir)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            from abackup.tui.screens.main_menu import MainMenuScreen

            self.app.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
