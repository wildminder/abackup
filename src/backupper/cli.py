"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from abackup import __version__
from abackup.config import load_jobs, load_settings
from abackup.core.paths import get_config_dir
from abackup.core.runner import run_jobs_batch
from abackup.tui.app import ABackupApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="abackup", description="Backup local files via a terminal UI."
    )
    parser.add_argument("--version", action="version", version=f"abackup {__version__}")
    parser.add_argument("--config-dir", default=None, help="Override config directory")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run every configured job (non-interactive) and print a summary",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of concurrent backup workers (default: settings.max_workers)",
    )
    parser.add_argument(
        "--show-settings",
        action="store_true",
        help="Print the resolved config directory and current settings as JSON, then exit",
    )
    return parser


def _print_batch_summary(results) -> None:
    success = sum(1 for r in results if r.status == "success")
    failed = len(results) - success
    for r in results:
        print(f"  {r.job_id}: {r.status}")
    print(f"Completed {len(results)} jobs: {success} success, {failed} failed.")


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.show_settings:
        config_dir = get_config_dir(args.config_dir)
        settings = load_settings(args.config_dir)
        print(json.dumps({"config_dir": str(config_dir), **settings.to_dict()}, indent=2))
        return
    if args.run_all:
        if args.config_dir is None:
            raise SystemExit("--run-all requires --config-dir")
        jobs = load_jobs(args.config_dir)
        if not jobs:
            print("No jobs configured. Add a job first.")
            return
        settings = load_settings(args.config_dir)
        max_workers = args.workers or settings.max_workers
        results = run_jobs_batch(
            jobs,
            config_dir=args.config_dir,
            data_dir=args.data_dir,
            max_workers=max_workers,
            prefer_py7zr=settings.prefer_py7zr,
        )
        _print_batch_summary(results)
        return
    app = ABackupApp(config_dir=args.config_dir, data_dir=args.data_dir)
    app.run()
