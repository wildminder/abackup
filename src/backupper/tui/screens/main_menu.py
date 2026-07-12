"""Main menu screen: list, run, add, delete jobs."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import ListView, ListItem, Label, Button, Header, Footer, Static

from abackup.config import load_jobs, save_jobs
from abackup.core.jobs import remove_job


class MainMenuScreen(Screen):
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
            Button("Delete selected", id="delete", variant="error"),
            Button("Settings", id="settings"),
            Button("Quit", id="quit"),
        )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_jobs()

    def refresh_jobs(self) -> None:
        jobs = load_jobs(self.config_dir)
        list_view = self.query_one("#jobs", ListView)
        list_view.clear()
        for j in jobs:
            list_view.append(
                ListItem(Label(f"{j.name} [{j.method.value}] -> {j.destination}"))
            )
        status = self.query_one("#status", Static)
        status.update("No jobs yet. Add one." if not jobs else "")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        jobs = load_jobs(self.config_dir)
        list_view = self.query_one("#jobs", ListView)
        if event.button.id == "add":
            from abackup.tui.screens.first_run import FirstRunScreen

            self.app.push_screen(FirstRunScreen(self.config_dir, self.data_dir))
            return
        if event.button.id == "run_all":
            from abackup.tui.screens.run_all import RunAllScreen

            self.app.push_screen(RunAllScreen(self.config_dir, self.data_dir))
            return
        if event.button.id == "settings":
            from abackup.tui.screens.settings import SettingsScreen

            self.app.push_screen(SettingsScreen(self.config_dir, self.data_dir))
            return
        if event.button.id == "quit":
            self.app.exit()
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
            save_jobs(remove_job(jobs, job.id), self.config_dir)
            self.refresh_jobs()
