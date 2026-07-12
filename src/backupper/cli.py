"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from abackup import __version__
from abackup.config import load_settings, save_settings
from abackup.tui.app import ABackupApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="abackup", description="Backup local files via a terminal UI."
    )
    parser.add_argument("--version", action="version", version=f"abackup {__version__}")
    parser.add_argument("--config-dir", default=None, help="Override config directory")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset first-run flag so the setup wizard shows again",
    )
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.reset:
        if args.config_dir is None:
            raise SystemExit("--reset requires --config-dir")
        settings = load_settings(args.config_dir)
        settings.first_run_completed = False
        save_settings(settings, args.config_dir)
        return
    app = ABackupApp(config_dir=args.config_dir, data_dir=args.data_dir)
    app.run()
