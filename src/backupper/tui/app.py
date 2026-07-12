"""ABackup Textual application."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from abackup.config import init_storage, load_settings
from abackup.core.discovery import is_first_run
from abackup.tui.screens.first_run import FirstRunScreen
from abackup.tui.screens.main_menu import MainMenuScreen


class ABackupApp(App):
    CSS = """
    Screen { align: center top; padding: 1; }
    #title { text-style: bold; width: 100%; content-align: center middle; }
    #error { color: $error; }
    #status { color: $text-muted; }
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

    def on_mount(self) -> None:
        init_storage(self.config_dir)
        settings = load_settings(self.config_dir)
        if is_first_run(settings):
            self.push_screen(FirstRunScreen(self.config_dir, self.data_dir))
        else:
            self.push_screen(MainMenuScreen(self.config_dir, self.data_dir))
