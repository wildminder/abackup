"""ABackup Textual application."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from abackup.config import init_storage, load_settings
from abackup.tui.screens.main_menu import MainMenuScreen

_VALID_THEMES = ("light", "dark")


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
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.theme_name = "dark"

    def on_mount(self) -> None:
        self.config_dir = init_storage(self.config_dir)
        # The storage directory is the single storage root: config (settings +
        # jobs) and data (logs + manifests) live together so a relocation
        # moves everything atomically.
        self.data_dir = self.config_dir
        # Apply the persisted theme (defaults to dark).
        self.apply_theme(load_settings(self.config_dir).theme)
        self.push_screen(MainMenuScreen(self.config_dir, self.data_dir))

    def apply_theme(self, name: str) -> None:
        """Switch between the ``light`` and ``dark`` themes.

        Textual's built-in dark/light palette is used, so we only need to
        flip ``self.dark``; the default styles adapt automatically.
        """
        self.theme_name = name if name in _VALID_THEMES else "dark"
        self.dark = self.theme_name == "dark"
