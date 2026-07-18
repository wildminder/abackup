"""ABackup Textual application."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from textual.app import App

from abackup.config import init_storage, load_jobs, load_settings
from abackup.core.runner import run_jobs_batch
from abackup.core.scheduler import due_jobs
from abackup.tui.screens.main_menu import MainMenuScreen

_VALID_THEMES = ("light", "dark")

# How often the background scheduler polls for due jobs (seconds).
SCHEDULER_POLL_SECONDS = 60


class ABackupApp(App):
    CSS = """
    Screen { align: center top; padding: 1; }
    #title { text-style: bold; width: 100%; content-align: center middle; }
    #error { color: $error; }
    #status { color: $text-muted; }

    /* Theme is driven by Textual's built-in dark/light palette (NTH-001). */
    Screen { background: $panel; color: $text; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        config_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.title = "ABackup"
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.theme_name = "dark"
        self._scheduler_thread: threading.Thread | None = None
        self._scheduler_stop = threading.Event()

    def on_mount(self) -> None:
        self.config_dir = init_storage(self.config_dir)
        # The config directory is the single storage root for settings + jobs.
        # When a separate --data-dir was provided it overrides where logs and
        # manifests are written; otherwise data co-locates with config so a
        # storage relocation (Settings screen) moves everything atomically.
        if self.data_dir is None:
            self.data_dir = self.config_dir
        # Apply the persisted theme (defaults to dark).
        self.apply_theme(load_settings(self.config_dir).theme)
        self.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
        # Start the background scheduler that runs due jobs automatically.
        self._start_scheduler()

    def _start_scheduler(self) -> None:
        """Launch a daemon thread that periodically runs due scheduled jobs."""
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, name="abackup-scheduler", daemon=True
        )
        self._scheduler_thread.start()

    def _scheduler_loop(self) -> None:
        """Poll for due jobs every ``SCHEDULER_POLL_SECONDS`` and run them."""
        while not self._scheduler_stop.is_set():
            if self._scheduler_stop.wait(SCHEDULER_POLL_SECONDS):
                break
            try:
                settings = load_settings(self.config_dir)
                jobs = load_jobs(self.config_dir)
                due = due_jobs(jobs, datetime.now())
                if due:
                    run_jobs_batch(
                        due,
                        config_dir=self.config_dir,
                        data_dir=self.data_dir,
                        max_workers=settings.max_workers,
                        prefer_py7zr=settings.prefer_py7zr,
                        seven_zip_compression_level=settings.seven_zip_compression_level,
                        run_mode=settings.run_mode,
                    )
            except Exception:
                # Scheduler must never crash the app.
                continue

    def on_unmount(self) -> None:
        self._scheduler_stop.set()

    def apply_theme(self, name: str) -> None:
        """Switch between the ``light`` and ``dark`` themes.

        Textual's built-in dark/light palette is used, so we only need to
        flip ``self.dark``; the default styles adapt automatically.
        """
        self.theme_name = name if name in _VALID_THEMES else "dark"
        self.dark = self.theme_name == "dark"
