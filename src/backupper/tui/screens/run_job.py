"""Run-job screen with progress bar."""

from __future__ import annotations

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import ProgressBar, Static, Button

from abackup.config import load_jobs, save_jobs
from abackup.core.backup import run_job
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
        yield Static("", id="result")
        yield Button("Back", id="back")

    def on_mount(self) -> None:
        self._worker = self.run_worker(self._run())

    async def _run(self) -> None:
        def on_progress(done, total, _path):
            pct = int(done / total * 100) if total else 100
            self.query_one("#progress", ProgressBar).update(progress=pct)

        result = run_job(
            self.job,
            config_dir=self.config_dir,
            data_dir=self.data_dir,
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
