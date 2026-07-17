"""Add backup job wizard screen."""

from __future__ import annotations

from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, Static

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
        yield ScrollableContainer(
            Vertical(
                Label("Source folder (to back up):"),
                Input(placeholder="C:/Users/art/Documents", id="source"),
                Label("Destination folder:"),
                Input(placeholder="D:/Backups", id="dest"),
                Label("Method:"),
                RadioSet(
                    RadioButton("Direct copy", value=True, id="copy"),
                    RadioButton("Zip archive", id="zip"),
                    RadioButton("7z archive (better compression, slower)", id="seven_zip"),
                    id="method",
                ),
                Label("Exclude patterns (comma/space separated, e.g. *.tmp __pycache__):"),
                Input(placeholder="optional", id="exclude"),
                Label("Include patterns (optional; only matching files are backed up):"),
                Input(placeholder="optional", id="include"),
                Label("Retention: keep last N archives (optional; archive methods only):"),
                Input(placeholder="optional", id="retention"),
                Label("Tag / group (optional):"),
                Input(placeholder="optional", id="tag"),
                Label("Write each run into its own timestamped subfolder:"),
                Checkbox("Stamp destination with run timestamp", id="subfolder_stamp"),
                Static("", id="error"),
            ),
            id="form",
        )
        yield Horizontal(
            Button("Save", id="save", variant="primary"),
            Button("Cancel", id="cancel"),
            id="actions",
        )

    CSS = """
    #title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }
    #form {
        height: 1fr;
        width: 100%;
        overflow-y: auto;
        border: round $primary;
        padding: 1 2;
    }
    #form > Vertical {
        height: auto;
    }
    #form Input { width: 100%; }
    #form RadioSet { width: 100%; }
    #actions {
        width: 100%;
        height: auto;
        align: center bottom;
        padding-top: 1;
    }
    """

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

        exclude_raw = self.query_one("#exclude", Input).value.strip()
        include_raw = self.query_one("#include", Input).value.strip()
        retention_raw = self.query_one("#retention", Input).value.strip()
        tag_raw = self.query_one("#tag", Input).value.strip()

        exclude_patterns = [p for p in exclude_raw.replace(",", " ").split() if p]
        include_patterns = [p for p in include_raw.replace(",", " ").split() if p]
        retention_count = None
        if retention_raw:
            try:
                retention_count = int(retention_raw)
            except ValueError:
                err.update("Retention must be a number")
                return
        tag = tag_raw or None
        subfolder_stamp = self.query_one("#subfolder_stamp", Checkbox).value

        job = BackupJob(
            source=source,
            destination=dest,
            method=method,
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            retention_count=retention_count,
            tag=tag,
            subfolder_stamp=subfolder_stamp,
        )
        try:
            job.validate()
        except Exception as exc:  # ConfigError or similar
            err.update(str(exc))
            return
        jobs = load_jobs(self.config_dir) + [job]
        save_jobs(jobs, self.config_dir)
        from abackup.tui.screens.main_menu import MainMenuScreen

        self.app.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
