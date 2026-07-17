"""Portability screen: export/import the full config to a portable JSON file."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from abackup.config import export_config, import_config
from abackup.utils.errors import ConfigError


class PortabilityScreen(ModalScreen):
    """Modal for exporting or importing the config.

    ``mode`` is either ``"export"`` (write current config to a path) or
    ``"import"`` (load config from a path). On success the screen pops and the
    main menu is refreshed; on error a message is shown in-place.
    """

    def __init__(self, config_dir, mode: str = "export"):
        super().__init__()
        self.config_dir = config_dir
        self.mode = mode

    def compose(self):
        title = "Export config" if self.mode == "export" else "Import config"
        label = "Destination file path:" if self.mode == "export" else "Source file path:"
        yield Label(title, id="title")
        yield Input(id="path", placeholder="e.g. C:\\Users\\me\\abackup-config.json")
        yield Label(label, classes="hint")
        yield Static("", id="error")
        yield Horizontal(
            Button("OK", id="ok", variant="primary"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
            return
        if event.button.id == "ok":
            self._do_action()

    def _do_action(self) -> None:
        path = self.query_one("#path", Input).value.strip()
        error = self.query_one("#error", Static)
        if not path:
            error.update("Please enter a file path.")
            return
        try:
            if self.mode == "export":
                export_config(self.config_dir, path)
                msg = f"Exported config to {path}"
            else:
                import_config(path, self.config_dir)
                msg = f"Imported config from {path}"
        except (ConfigError, OSError) as exc:
            error.update(f"Failed: {exc}")
            return
        # Refresh the main menu (job list) after an import.
        self.app.pop_screen()
        under = self.app.screen
        from abackup.tui.screens.main_menu import MainMenuScreen

        if isinstance(under, MainMenuScreen):
            under.refresh_jobs()
        else:
            self.app.notify(msg)
