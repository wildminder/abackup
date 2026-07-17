"""Per-job run history screen (RM-06)."""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from abackup.core.history import load_history


def _fmt_size(num: int | None) -> str:
    if num is None:
        return "-"
    mb = num / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f} MB"
    return f"{num / 1024:.1f} KB"


class HistoryScreen(Screen):
    """List past runs for a single job, newest first."""

    def __init__(self, config_dir, data_dir, job):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.job = job

    def compose(self):
        yield Header()
        yield Static(f"History: {self.job.name}", id="title")
        yield DataTable(id="table", cursor_type="none")
        yield Static("", id="empty")
        yield Button("Back", id="back", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("Started", "Duration", "Files", "Size", "Status")
        entries = load_history(self.data_dir, self.job.id)
        if not entries:
            self.query_one("#empty", Static).update("No runs yet for this job.")
            table.display = False
            return
        # Newest first.
        for e in reversed(entries):
            table.add_row(
                e.started_at.replace("T", " ").replace("+00:00", "Z"),
                f"{e.duration_seconds:.0f}s",
                f"{e.files_done}/{e.files_total}",
                _fmt_size(e.archive_size),
                e.status,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
