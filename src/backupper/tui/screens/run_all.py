"""Run-all-jobs screen: progress bar + per-job result log (batched, concurrent)."""

from __future__ import annotations

import threading

from textual.screen import Screen
from textual.containers import Horizontal
from textual.widgets import ProgressBar, Static, Button, RichLog

from abackup.config import load_jobs, load_settings
from abackup.core.runner import run_jobs_batch


class RunAllScreen(Screen):
    """Run every configured job concurrently and show live progress.

    The batch runs inside a Textual *thread* worker (``thread=True``), so the
    blocking ``run_jobs_batch`` (which joins its own worker pool) executes off
    the event loop. Worker threads report progress through ``call_from_thread``,
    which is safe here because the event loop remains responsive -- this avoids
    the deadlock that would occur if the batch blocked the event-loop thread.

    A **Cancel** button sets a shared ``threading.Event`` that the runner checks
    between (and, for copies, during) files, aborting all jobs promptly.
    """

    def __init__(self, config_dir, data_dir):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir
        self._completed = False
        self._worker = None
        self._cancel = threading.Event()

    def compose(self):
        yield Static("Running all backup jobs", id="title")
        yield ProgressBar(total=1, id="progress")
        yield RichLog(id="log")
        yield Static("", id="summary")
        yield Horizontal(
            Button("Cancel", id="cancel", variant="error"),
            Button("Back", id="back"),
        )

    def on_mount(self) -> None:
        jobs = load_jobs(self.config_dir)
        progress = self.query_one("#progress", ProgressBar)
        log = self.query_one("#log", RichLog)
        summary = self.query_one("#summary", Static)
        back = self.query_one("#back", Button)

        if not jobs:
            log.write("No jobs to run.")
            summary.update("Nothing to do.")
            self._completed = True
            back.disabled = False
            return

        # Keep "Back" disabled until the batch finishes (or is cancelled) so the
        # screen isn't popped while worker threads are still running.
        back.disabled = True
        progress.total = len(jobs)
        progress.progress = 0

        def on_job_done(job_id: str, result) -> None:
            # Serialize UI mutations onto the event loop (race-free, no deadlock).
            self.app.call_from_thread(self._bump_progress)
            self.app.call_from_thread(self._log, f"{job_id}: {result.status}")

        def run_batch() -> None:
            results = run_jobs_batch(
                jobs,
                config_dir=self.config_dir,
                data_dir=self.data_dir,
                max_workers=load_settings(self.config_dir).max_workers,
                on_job_done=on_job_done,
                cancel=self._cancel,
            )
            success = sum(1 for r in results if r.status == "success")
            failed = sum(1 for r in results if r.status == "failed")
            cancelled = sum(1 for r in results if r.status == "cancelled")
            self.app.call_from_thread(
                self._finish,
                f"Completed {len(results)} jobs: {success} success, "
                f"{failed} failed, {cancelled} cancelled.",
            )

        self._worker = self.run_worker(run_batch, thread=True)

    def _bump_progress(self) -> None:
        self.query_one("#progress", ProgressBar).progress += 1

    def _log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def _finish(self, text: str) -> None:
        self.query_one("#summary", Static).update(text)
        self._completed = True
        self.query_one("#back", Button).disabled = False
        self.query_one("#cancel", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            # Signal all worker threads to abort at the next cancellation check.
            self._cancel.set()
            self.query_one("#cancel", Button).disabled = True
            self.query_one("#summary", Static).update("Cancelling…")
            return
        if event.button.id == "back":
            from abackup.tui.screens.main_menu import MainMenuScreen

            self.app.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
