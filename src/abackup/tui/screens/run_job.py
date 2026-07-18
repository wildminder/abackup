"""Run-job screen with realtime progress (bar + current file + counts)."""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Button, ProgressBar, Static

from abackup.config import load_jobs, load_settings, save_jobs
from abackup.core.backup import format_summary, run_job
from abackup.core.notify import beep, notify
from abackup.core.paths import shorten_path
from abackup.core.progress import Progress
from abackup.core.validation import check_free_space
from abackup.models import BackupJob


class RunJobScreen(Screen):
    def __init__(self, config_dir, data_dir, job: BackupJob, dry_run: bool = False):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.job = job
        self.dry_run = dry_run

    def compose(self):
        title = f"Running backup: {self.job.name}"
        if self.dry_run:
            title += " [DRY RUN]"
        yield Static(title, id="title")
        yield ProgressBar(total=100, id="progress")
        yield Static("", id="current")
        yield Static("", id="counts")
        yield Static("", id="warning")
        yield Static("", id="result")
        yield Button("Back", id="back")

    def on_mount(self) -> None:
        # Run on a *thread* worker: run_job() is a blocking call, so executing
        # it off the event loop keeps the UI responsive and lets the
        # on_progress callback marshal live updates back via call_from_thread.
        self._worker = self.run_worker(self._run, thread=True)

    def _run(self) -> None:
        def on_progress(p: Progress) -> None:
            # run_job() runs synchronously inside this worker thread, so the
            # callback fires off the event loop. Marshal UI updates back onto
            # the event loop so the progress bar/current-file update live.
            self.app.call_from_thread(self._render_progress, p)

        settings = load_settings(self.config_dir)
        # RM-11: advisory low-free-space warning before the run starts.
        warning = check_free_space(self.job)
        if warning:
            self.app.call_from_thread(
                self.query_one("#warning", Static).update, f"⚠ {warning}"
            )
        result = run_job(
            self.job,
            config_dir=self.config_dir,
            data_dir=self.data_dir,
            prefer_py7zr=settings.prefer_py7zr,
            seven_zip_compression_level=settings.seven_zip_compression_level,
            dry_run=self.dry_run,
            on_progress=on_progress,
        )
        # run_job() returns on this worker thread; marshal the final render
        # (progress=100 + result) onto the event loop so it paints correctly.
        self.app.call_from_thread(self._render_result, result, settings)

    def _render_progress(self, p: Progress) -> None:
        self.query_one("#progress", ProgressBar).update(progress=p.percent())
        self.query_one("#current", Static).update(
            f"Current: {shorten_path(p.current_file, self.job.source)}" if p.current_file else ""
        )
        mb_done = p.bytes_done / (1024 * 1024)
        mb_total = p.bytes_total / (1024 * 1024)
        self.query_one("#counts", Static).update(
            f"Files {p.files_done}/{p.files_total} · {mb_done:.1f}/{mb_total:.1f} MB"
        )

    def _render_result(self, result, settings) -> None:
        self.query_one("#progress", ProgressBar).update(progress=100)
        suffix = " (dry run — nothing written)" if self.dry_run else ""
        summary_text = format_summary(result.summary)
        detail = f"\n{summary_text}" if summary_text else ""
        self.query_one("#result", Static).update(f"Status: {result.status}{detail}{suffix}")
        # RM-08 / RM-09: notify on success, beep on failure (best-effort, toggled).
        if not self.dry_run:
            if result.status == "success" and settings.notify_on_finish:
                notify("abackup", f"Backup '{self.job.name}' finished successfully.")
            elif result.status in ("failed", "cancelled") and settings.sound_on_failure:
                beep()
        # Persist updated job status (dry-run still records last_run_at/status).
        jobs = load_jobs(self.config_dir)
        if result.updated_job is not None:
            from abackup.core.jobs import upsert_job

            save_jobs(upsert_job(jobs, result.updated_job), self.config_dir)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            from abackup.tui.screens.main_menu import MainMenuScreen

            self.app.push_screen(MainMenuScreen(self.config_dir, self.data_dir))

    CSS = """
    #title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }
    #result {
        width: 100%;
        height: auto;
        border: round $panel;
        background: $panel;
        padding: 1 2;
        margin-top: 1;
    }
    #warning { color: $warning; }
    """
