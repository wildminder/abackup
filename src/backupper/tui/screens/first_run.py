"""First-run setup wizard screen."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Input, Button, Label, RadioSet, RadioButton, Static

from abackup.config import load_jobs, save_jobs, load_settings, save_settings
from abackup.core.discovery import mark_first_run_done
from abackup.models import BackupJob, BackupMethod


class FirstRunScreen(Screen):
    def __init__(self, config_dir, data_dir):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir

    def compose(self):
        yield Label("First run setup", id="title")
        yield Label("Source folder (to back up):")
        yield Input(placeholder="C:/Users/art/Documents", id="source")
        yield Label("Destination folder:")
        yield Input(placeholder="D:/Backups", id="dest")
        yield Label("Method:")
        with RadioSet(id="method"):
            yield RadioButton("Direct copy", value=True, id="copy")
            yield RadioButton("Zip archive", id="zip")
        yield Static("", id="error")
        yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            return
        source = self.query_one("#source", Input).value.strip()
        dest = self.query_one("#dest", Input).value.strip()
        method = (
            BackupMethod.ZIP
            if self.query_one("#zip", RadioButton).value
            else BackupMethod.COPY
        )
        err = self.query_one("#error", Static)

        if not source or not Path(source).is_dir():
            err.update("Source must be an existing folder.")
            return
        if not dest:
            err.update("Destination is required.")
            return

        Path(dest).mkdir(parents=True, exist_ok=True)
        job = BackupJob(source=source, destination=dest, method=method)
        jobs = load_jobs(self.config_dir) + [job]
        save_jobs(jobs, self.config_dir)
        settings = mark_first_run_done(load_settings(self.config_dir))
        save_settings(settings, self.config_dir)
        from abackup.tui.screens.main_menu import MainMenuScreen

        self.app.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
