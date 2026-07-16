"""Settings screen: edit storage location, zip level, workers, log, default dest."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Input, Select, Static, Button, Header, Footer, Label, Checkbox

from abackup.config import (
    load_settings,
    save_settings,
    relocate_storage,
    relocate_data,
)
from abackup.models import Settings
from abackup.utils.errors import ConfigError

_LOG_LEVELS = [("DEBUG", "DEBUG"), ("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR")]


class SettingsScreen(Screen):
    CSS = """
    #title {
        padding: 1 2 0 2;
        text-style: bold;
        width: 100%;
    }
    .field {
        padding: 0 2;
        height: auto;
    }
    .field-label {
        text-style: bold;
        padding: 1 0 0 0;
    }
    .field-hint {
        color: $text-muted;
        padding: 0 0 1 0;
    }
    #error {
        padding: 0 2;
        color: $error;
        height: 1;
    }
    #body {
        height: 1fr;
    }
    #actions {
        height: auto;
        padding: 1 2;
    }
    """

    def __init__(self, config_dir, data_dir):
        super().__init__()
        self.config_dir = config_dir
        self.data_dir = data_dir
        self._existing: Settings | None = None

    def compose(self):
        yield Header()
        yield Label("Settings", id="title")
        yield ScrollableContainer(
            Vertical(
                Label("Storage directory", classes="field-label"),
                Input(id="config_dir", placeholder="e.g. C:\\Users\\me\\abackup"),
                Static("Where jobs, settings and logs are stored. Changing it moves all data.", classes="field-hint"),
                classes="field",
            ),
            Vertical(
                Label("Zip compression level (0-9)", classes="field-label"),
                Input(id="zip_level", placeholder="0 = store, 9 = max, default 6"),
                Static("Used by the 'zip' backup method.", classes="field-hint"),
                classes="field",
            ),
            Vertical(
                Label("7z compression level (0-9)", classes="field-label"),
                Input(id="sz_level", placeholder="0 = copy, 3 = fast, 5 = normal, 9 = ultra, default 3"),
                Static(
                    "LZMA2 preset for the '7z' method. 0 stores (no compression), "
                    "3 is fast, 9 is ultra (slowest). Default 3.",
                    classes="field-hint",
                ),
                classes="field",
            ),
            Vertical(
                Label("Max concurrent workers", classes="field-label"),
                Input(id="workers", placeholder="default 4"),
                Static("How many jobs run at once with 'Run all jobs'.", classes="field-hint"),
                classes="field",
            ),
            Vertical(
                Label("Log level", classes="field-label"),
                Select(_LOG_LEVELS, id="log_level", prompt="Log level"),
                classes="field",
            ),
            Vertical(
                Label("Theme", classes="field-label"),
                Select(
                    [("Dark", "dark"), ("Light", "light")],
                    id="theme",
                    prompt="Theme",
                ),
                classes="field",
            ),
            Vertical(
                Label("Default destination (optional)", classes="field-label"),
                Input(id="default_dest", placeholder="pre-filled for new jobs"),
                Static("Used as the destination when creating a new job.", classes="field-hint"),
                classes="field",
            ),
            Vertical(
                Checkbox(
                    "Prefer py7zr library for 7z (else system 7-Zip binary)",
                    id="prefer_py7zr",
                ),
            Static(
                "By default 7z jobs use the (multithreaded, much faster) system "
                "7-Zip binary when installed. Enable this to force the pure-Python "
                "py7zr library instead (portable fallback, slower). The 'zip' "
                "method is unaffected and always uses Python's zipfile.",
                classes="field-hint",
            ),
                classes="field",
            ),
            Static("", id="error"),
            id="body",
        )
        yield Horizontal(
            Button("Save", id="save", variant="primary"),
            Button("Cancel", id="cancel"),
            id="actions",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._existing = load_settings(self.config_dir)
        self.query_one("#config_dir", Input).value = str(self.config_dir)
        self.query_one("#zip_level", Input).value = str(self._existing.zip_compression_level)
        self.query_one("#sz_level", Input).value = str(self._existing.seven_zip_compression_level)
        self.query_one("#workers", Input).value = str(self._existing.max_workers)
        self.query_one("#log_level", Select).value = self._existing.log_level
        self.query_one("#theme", Select).value = self._existing.theme
        self.query_one("#default_dest", Input).value = self._existing.default_destination or ""
        self.query_one("#prefer_py7zr", Checkbox).value = self._existing.prefer_py7zr

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
            sz_level = int(self.query_one("#sz_level", Input).value)
            workers = int(self.query_one("#workers", Input).value)
            log_level = self.query_one("#log_level", Select).value
            theme = self.query_one("#theme", Select).value
            default_dest = self.query_one("#default_dest", Input).value.strip() or None
            prefer_py7zr = self.query_one("#prefer_py7zr", Checkbox).value
        except ValueError as exc:
            error.update(f"Invalid number: {exc}")
            return

        updated = Settings(
            schema_version=self._existing.schema_version,
            default_destination=default_dest,
            log_level=log_level,
            max_workers=workers,
            zip_compression_level=zip_level,
            seven_zip_compression_level=sz_level,
            prefer_py7zr=prefer_py7zr,
            theme=theme,
            created_at=self._existing.created_at,
        )
        try:
            updated.validate()
        except ConfigError as exc:
            error.update(str(exc))
            return

        old = Path(self.config_dir or self.app.config_dir).resolve()
        new = Path(config_dir).resolve()
        if new != old:
            relocate_storage(old, new)
            # The storage directory is the single storage root, so move the
            # run history (logs + manifests) too.
            relocate_data(old, new)
            self.app.config_dir = str(new)
            self.config_dir = str(new)
            self.app.data_dir = str(new)
            self.data_dir = str(new)

        save_settings(updated, self.config_dir)
        # Apply the chosen theme live (light/dark).
        self.app.apply_theme(theme)

        # Return to the main menu, refreshing it with the (possibly new) location.
        self.app.pop_screen()
        under = self.app.screen
        from abackup.tui.screens.main_menu import MainMenuScreen

        if isinstance(under, MainMenuScreen):
            under.config_dir = self.config_dir
            under.refresh_jobs()
