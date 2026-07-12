"""Run-all-jobs screen: realtime overall + per-job progress (batched, concurrent)."""

from __future__ import annotations

import threading

from textual.screen import Screen
from textual.containers import Horizontal
from textual.widgets import ProgressBar, Static, Button, RichLog

from abackup.config import load_jobs, load_settings
from abackup.core.paths import shorten_path
from abackup.core.progress import Progress
from abackup.core.runner import run_jobs_batch


class RunAllScreen(Screen):
    """Run every configured job concurrently and show live progress.

    The batch runs inside a Textual *thread* worker (``thread=True``), so the
    blocking ``run_jobs_batch`` (which joins its own worker pool) executes off
    the event loop. Worker threads report progress through ``call_from_thread``,
    which is safe here because the event loop remains responsive -- this avoids
    the deadlock that would occur if the batch blocked the event-loop thread.

    Two live views are maintained:
      * an **overall** progress bar (aggregate bytes across all jobs), and
      * a **per-job** status block (each job's percent + current file).

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
        # Latest progress snapshot per job id (updated from worker threads).
        self._job_progress: dict[str, Progress] = {}
        # Friendly name per job id for the per-job status lines.
        self._job_names: dict[str, str] = {}

    def compose(self):
        yield Static("Running all backup jobs", id="title")
        yield ProgressBar(total=100, id="progress")
        yield Static("", id="jobs")
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

        self._job_names = {j.id: j.name for j in jobs}
        self._job_sources = {j.id: j.source for j in jobs}

        # Keep "Back" disabled until the batch finishes (or is cancelled) so the
        # screen isn't popped while worker threads are still running.
        back.disabled = True
        progress.total = 100
        progress.progress = 0

        def on_job_done(job_id: str, result) -> None:
            # Serialize UI mutations onto the event loop (race-free, no deadlock).
            self.app.call_from_thread(self._log, f"{job_id}: {result.status}")

        def on_progress(job_id: str, p: Progress) -> None:
            # Forwarded from worker threads; marshal onto the event loop.
            self.app.call_from_thread(self._update_job, job_id, p)

        def run_batch() -> None:
            settings = load_settings(self.config_dir)
            results = run_jobs_batch(
                jobs,
                config_dir=self.config_dir,
                data_dir=self.data_dir,
                max_workers=settings.max_workers,
                prefer_py7zr=settings.prefer_py7zr,
                seven_zip_compression_level=settings.seven_zip_compression_level,
                on_job_done=on_job_done,
                on_progress=on_progress,
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

    def _update_job(self, job_id: str, p: Progress) -> None:
        self._job_progress[job_id] = p
        # Rebuild the per-job status block.
        lines = []
        total_done = 0
        total_bytes = 0
        for jid, prog in self._job_progress.items():
            label = shorten_path(prog.current_file, self._job_sources.get(jid)) or prog.phase
            name = self._job_names.get(jid, jid)
            lines.append(f"{name}: {prog.percent()}% — {label}")
            total_done += prog.bytes_done
            total_bytes += prog.bytes_total
        self.query_one("#jobs", Static).update("\n".join(lines))
        # Overall bar from aggregate bytes (falls back to per-job count).
        if total_bytes > 0:
            overall = min(100, int(total_done / total_bytes * 100))
            self.query_one("#progress", ProgressBar).update(progress=overall)

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
