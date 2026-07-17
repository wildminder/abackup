"""Main menu screen: list, run, add, delete jobs."""

from __future__ import annotations

from collections.abc import Callable

from textual.containers import Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static

from abackup.config import load_jobs, save_jobs
from abackup.core.jobs import remove_job
from abackup.core.paths import format_job_label


class _ConfirmScreen(ModalScreen[bool]):
    """Small yes/no confirmation dialog (keeps destructive actions safe)."""

    def __init__(self, message: str, on_result: Callable[[bool], None]) -> None:
        super().__init__()
        self._message = message
        self._on_result = on_result

    def compose(self):
        yield Static(self._message, id="confirm_msg")
        yield Horizontal(
            Button("Yes", id="yes", variant="error"),
            Button("No", id="no", variant="primary"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        confirmed = event.button.id == "yes"
        self._on_result(confirmed)
        self.dismiss(confirmed)


class MainMenuScreen(Screen):
    CSS = """
    #key_help {
        padding: 0 1;
        color: $text-muted;
        height: 1;
    }
    ListItem {
        padding: 0 1;
    }
    /* Highlight the keyboard-selected job (NTH-002). */
    ListItem:focus {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    /* Compact secondary-action row: small, dense, single line. */
    #secondary {
        height: 3;
        padding: 0 1;
    }
    #secondary Button {
        min-width: 12;
        padding: 0 1;
    }
    /* Disabled buttons must not react to hover (no false "active" affordance). */
    Button:disabled {
        color: $text-muted;
        background: $panel;
        text-style: none;
    }
    Button:disabled:hover {
        background: $panel;
        color: $text-muted;
    }
    #confirm_msg {
        padding: 1 2;
        width: 60%;
        background: $panel;
        border: round $accent;
    }
    """

    def __init__(self, config_dir, data_dir):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir

    def compose(self):
        yield Header()
        yield Label("Backup jobs", id="title")
        yield ListView(id="jobs")
        yield Horizontal(
            Button("Add job", id="add", variant="primary"),
            Button("Run selected", id="run"),
            Button("Run all", id="run_all", variant="success"),
            Button("History", id="history"),
        )
        yield Horizontal(
            Button("Settings", id="settings"),
            Button("Export", id="export"),
            Button("Import", id="import"),
            Button("Delete", id="delete", variant="error"),
            Button("Quit", id="quit"),
            id="secondary",
        )
        yield Static("", id="status")
        yield Static(
            "↑/↓ select · Enter run · A add · D delete · H history · R run all · S settings",
            id="key_help",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_jobs()

    def _update_button_states(self, jobs: list) -> None:
        """Enable job-dependent buttons only when at least one job exists.

        Export is disabled with no jobs (nothing to export); Import stays
        available since it bootstraps an empty config.
        """
        has_jobs = bool(jobs)
        for button_id in ("run", "history", "delete", "export"):
            self.query_one(f"#{button_id}", Button).disabled = not has_jobs

    def refresh_jobs(self) -> None:
        jobs = load_jobs(self.config_dir)
        list_view = self.query_one("#jobs", ListView)
        list_view.clear()
        for j in jobs:
            list_view.append(ListItem(Label(format_job_label(j.name, j.method.value, j.source, j.destination))))
        status = self.query_one("#status", Static)
        status.update("No jobs yet. Add one." if not jobs else "")
        self._update_button_states(jobs)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        jobs = load_jobs(self.config_dir)
        list_view = self.query_one("#jobs", ListView)
        if event.button.id == "add":
            from abackup.tui.screens.add_job import AddJobScreen

            self.app.push_screen(AddJobScreen(self.config_dir, self.data_dir))
            return
        if event.button.id == "run_all":
            from abackup.tui.screens.run_all import RunAllScreen

            self.app.push_screen(RunAllScreen(self.config_dir, self.data_dir))
            return
        if event.button.id == "history":
            self._open_history(jobs, list_view.index or 0)
            return
        if event.button.id == "settings":
            from abackup.tui.screens.settings import SettingsScreen

            self.app.push_screen(SettingsScreen(self.config_dir, self.data_dir))
            return
        if event.button.id == "quit":
            self.app.exit()
            return
        if event.button.id == "export":
            from abackup.tui.screens.portability import PortabilityScreen

            self.app.push_screen(PortabilityScreen(self.config_dir, mode="export"))
            return
        if event.button.id == "import":
            # Import overwrites the current config: confirm first (non-destructive UI).
            msg = "Import will replace your current jobs and settings. Continue?"

            def _do_import(confirmed: bool) -> None:
                if not confirmed:
                    return
                from abackup.tui.screens.portability import PortabilityScreen

                # Defer the push until after the confirm modal has fully dismissed,
                # so the new screen isn't lost during the transition.
                self.app.call_later(
                    lambda: self.app.push_screen(
                        PortabilityScreen(self.config_dir, mode="import")
                    )
                )

            self.app.push_screen(_ConfirmScreen(msg, _do_import))
            return
        if not jobs:
            self.query_one("#status", Static).update("No jobs to act on.")
            return
        index = list_view.index or 0
        if index >= len(jobs):
            index = len(jobs) - 1
        job = jobs[index]
        if event.button.id == "run":
            from abackup.tui.screens.run_job import RunJobScreen

            self.app.push_screen(RunJobScreen(self.config_dir, self.data_dir, job))
        elif event.button.id == "delete":
            # Destructive: require explicit confirmation before removing the job.
            def _do_delete(confirmed: bool) -> None:
                if not confirmed:
                    return
                save_jobs(remove_job(jobs, job.id), self.config_dir)
                self.refresh_jobs()

            self.app.push_screen(
                _ConfirmScreen(f"Delete job '{job.name}'? This cannot be undone.", _do_delete)
            )

    def _open_history(self, jobs: list, index: int) -> None:
        if not jobs:
            self.query_one("#status", Static).update("No job selected.")
            return
        if index >= len(jobs):
            index = len(jobs) - 1
        job = jobs[index]
        from abackup.tui.screens.history import HistoryScreen

        self.app.push_screen(HistoryScreen(self.config_dir, self.data_dir, job))

    def on_key(self, event) -> None:
        # H opens history for the selected job (RM-06).
        if event.key == "h":
            jobs = load_jobs(self.config_dir)
            list_view = self.query_one("#jobs", ListView)
            self._open_history(jobs, list_view.index or 0)
