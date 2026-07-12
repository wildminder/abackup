"""Settings screen: edit storage location, zip level, workers, log, default dest."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Input, Select, Static, Button, Header, Footer, Label

from abackup.config import load_settings, save_settings, relocate_storage
from abackup.models import Settings
from abackup.utils.errors import ConfigError

_LOG_LEVELS = [("DEBUG", "DEBUG"), ("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR")]


class SettingsScreen(Screen):
    def __init__(self, config_dir, data_dir):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir
        self._existing: Settings | None = None

    def compose(self):
        yield Header()
        yield Label("Settings", id="title")
        yield Input(id="config_dir", placeholder="Storage directory")
        yield Input(id="zip_level", placeholder="Zip compression level (0-9)")
        yield Input(id="workers", placeholder="Max concurrent workers")
        yield Select(_LOG_LEVELS, id="log_level", prompt="Log level")
        yield Input(id="default_dest", placeholder="Default destination (optional)")
        yield Static("", id="error")
        yield Horizontal(
            Button("Save", id="save", variant="primary"),
            Button("Cancel", id="cancel"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._existing = load_settings(self.config_dir)
        self.query_one("#config_dir", Input).value = str(self.config_dir)
        self.query_one("#zip_level", Input).value = str(self._existing.zip_compression_level)
        self.query_one("#workers", Input).value = str(self._existing.max_workers)
        self.query_one("#log_level", Select).value = self._existing.log_level
        self.query_one("#default_dest", Input).value = self._existing.default_destination or ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
            return
        if event.button.id == "save":
            self._save()

    def _save(self) -> None:
        error = self.query_one("#error", Static)
        try:
            config_dir = self.query_one("#config_dir", Input).value.strip()
            zip_level = int(self.query_one("#zip_level", Input).value)
            workers = int(self.query_one("#workers", Input).value)
            log_level = self.query_one("#log_level", Select).value
            default_dest = self.query_one("#default_dest", Input).value.strip() or None
        except ValueError as exc:
            error.update(f"Invalid number: {exc}")
            return

        updated = Settings(
            schema_version=self._existing.schema_version,
            first_run_completed=self._existing.first_run_completed,
            default_destination=default_dest,
            log_level=log_level,
            max_workers=workers,
            zip_compression_level=zip_level,
            created_at=self._existing.created_at,
        )
        try:
            updated.validate()
        except ConfigError as exc:
            error.update(str(exc))
            return

        old = Path(self.config_dir).resolve()
        new = Path(config_dir).resolve()
        if new != old:
            relocate_storage(old, new)
            self.app.config_dir = str(new)
            self.config_dir = str(new)

        save_settings(updated, self.config_dir)

        # Return to the main menu, refreshing it with the (possibly new) location.
        self.app.pop_screen()
        under = self.app.screen
        from abackup.tui.screens.main_menu import MainMenuScreen

        if isinstance(under, MainMenuScreen):
            under.config_dir = self.config_dir
            under.refresh_jobs()
