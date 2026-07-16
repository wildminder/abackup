"""Add backup job wizard screen."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input, Button, Label, RadioSet, RadioButton, Static

from abackup.config import load_jobs, save_jobs
from abackup.core.validation import validate_add_job
from abackup.models import BackupJob, BackupMethod


class AddJobScreen(Screen):
    def __init__(self, config_dir, data_dir):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir

    def compose(self):
        yield Label("Add backup job", id="title")
        yield Label("Source folder (to back up):")
        yield Input(placeholder="C:/Users/art/Documents", id="source")
        yield Label("Destination folder:")
        yield Input(placeholder="D:/Backups", id="dest")
        yield Label("Method:")
        with RadioSet(id="method"):
            yield RadioButton("Direct copy", value=True, id="copy")
            yield RadioButton("Zip archive", id="zip")
            yield RadioButton("7z archive (better compression, slower)", id="seven_zip")
        yield Static("", id="error")
        yield Horizontal(
            Button("Save", id="save", variant="primary"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
            return
        if event.button.id != "save":
            return
        source = self.query_one("#source", Input).value.strip()
        dest = self.query_one("#dest", Input).value.strip()
        method = (
            BackupMethod.SEVEN_ZIP
            if self.query_one("#seven_zip", RadioButton).value
            else BackupMethod.ZIP
            if self.query_one("#zip", RadioButton).value
            else BackupMethod.COPY
        )
        err = self.query_one("#error", Static)

        errs = validate_add_job(source, dest)
        if errs:
            err.update("; ".join(errs))
            return

        job = BackupJob(source=source, destination=dest, method=method)
        jobs = load_jobs(self.config_dir) + [job]
        save_jobs(jobs, self.config_dir)
        from abackup.tui.screens.main_menu import MainMenuScreen

        self.app.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
