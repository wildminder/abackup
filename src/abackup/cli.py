"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from abackup import __version__
from abackup.config import (
    export_config,
    import_config,
    load_jobs,
    load_settings,
)
from abackup.core.backup import BackupResult, format_summary, run_job
from abackup.core.jobs import find_job_by_name
from abackup.core.paths import get_config_dir, is_inside
from abackup.core.progress import Progress
from abackup.core.runner import run_jobs_batch
from abackup.models import BackupJob, BackupMethod
from abackup.tui.app import ABackupApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abackup", description="Backup local files via a terminal UI.")
    parser.add_argument("--version", action="version", version=f"abackup {__version__}")
    parser.add_argument("--config-dir", default=None, help="Override config directory")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run every configured job (non-interactive) and print a summary",
    )
    parser.add_argument(
        "--run-due",
        action="store_true",
        help="Run only jobs whose schedule is due (requires --config-dir)",
    )
    parser.add_argument(
        "--run",
        metavar="NAME",
        default=None,
        help="Run a single job by name (non-interactive); exit code reflects result",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="List configured jobs (name | method | source -> destination) and exit",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="Run only jobs with the given tag (with --run-all/--run-due)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of concurrent backup workers (default: settings.max_workers)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the backup without writing anything (with --run-all/--run-due/--run)",
    )
    parser.add_argument(
        "--export",
        metavar="PATH",
        default=None,
        help="Export all jobs + settings to a portable JSON file at PATH",
    )
    parser.add_argument(
        "--import",
        metavar="PATH",
        dest="import_path",
        default=None,
        help="Import jobs + settings from a portable JSON file at PATH",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="With --import, merge imported jobs into existing ones (by id) instead of overwriting",
    )
    parser.add_argument(
        "--show-settings",
        action="store_true",
        help="Print the resolved config directory and current settings as JSON, then exit",
    )
    # Portable, config-free one-shot backup. Supplying any of these triggers
    # portable mode (no jobs.json / settings.json are read or written).
    parser.add_argument("--source", default=None, help="Portable mode: source folder to back up")
    parser.add_argument("--destination", default=None, help="Portable mode: destination folder")
    parser.add_argument(
        "--method",
        default=None,
        choices=["copy", "zip", "7z"],
        help="Portable mode: backup method (copy, zip, 7z)",
    )
    parser.add_argument("--name", default=None, help="Portable mode: display name (not persisted)")
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Portable mode: exclude glob pattern (repeatable)",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help="Portable mode: include glob pattern (repeatable)",
    )
    parser.add_argument(
        "--stamp",
        action="store_true",
        help="Portable mode: write into a timestamped subfolder of the destination",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Portable mode: suppress progress/summary output (exit code still set)",
    )
    return parser


def _print_batch_summary(results: list[BackupResult]) -> None:
    success = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failed")
    cancelled = sum(1 for r in results if r.status == "cancelled")
    for r in results:
        print(f"  {r.job_id}: {r.status}")
    print(f"Completed {len(results)} jobs: {success} success, {failed} failed, {cancelled} cancelled.")


def _exit_code_for(results: list[BackupResult]) -> int:
    """Map batch results to a process exit code.

    0 = all success, 1 = at least one failure, 2 = at least one cancellation
    (cancellation takes precedence over success but not over failure).
    """
    if any(r.status == "failed" for r in results):
        return 1
    if any(r.status == "cancelled" for r in results):
        return 2
    return 0


def _run_batch(jobs, args, settings) -> list[BackupResult]:
    max_workers = args.workers or settings.max_workers
    return run_jobs_batch(
        jobs,
        config_dir=args.config_dir,
        data_dir=args.data_dir or args.config_dir,
        max_workers=max_workers,
        prefer_py7zr=settings.prefer_py7zr,
        prefer_robocopy=settings.prefer_robocopy,
        seven_zip_compression_level=settings.seven_zip_compression_level,
        run_mode=settings.run_mode,
        dry_run=args.dry_run,
        notify_on_finish=settings.notify_on_finish,
        sound_on_failure=settings.sound_on_failure,
    )


def _make_console_progress(job) -> Callable[[Progress], None]:
    """Build an ``on_progress`` callback that renders a live console bar.

    The bar is drawn in place (carriage return) so the user sees smooth
    progress instead of only the final result. Updates are throttled to whole
    percent changes to avoid flooding the terminal.
    """

    last_percent = -1

    def on_progress(p: Progress) -> None:
        nonlocal last_percent
        percent = p.percent()
        if percent == last_percent:
            return
        last_percent = percent
        mb_done = p.bytes_done / (1024 * 1024)
        mb_total = p.bytes_total / (1024 * 1024)
        line = (
            f"\r[{job.method.value}] {percent:3d}% "
            f"({p.files_done}/{p.files_total} files, {mb_done:.1f}/{mb_total:.1f} MB)"
        )
        # Carriage return + pad with spaces so a shorter line doesn't leave
        # stale characters from the previous (longer) render.
        print(line.ljust(80), end="", flush=True)

    return on_progress


def _run_portable(args) -> None:
    """Config-free one-shot backup from CLI args (portable mode).

    Builds a ``BackupJob`` in memory, validates the source/destination, runs a
    single atomic backup via ``run_job(portable=True)``, and exits with a code
    reflecting the result. No jobs.json / settings.json are read or written.
    """
    # Step 1: the portable group requires all three core args together.
    portable_args = (("--source", args.source), ("--destination", args.destination), ("--method", args.method))
    missing = [n for n, v in portable_args if v is None]
    if missing:
        print(f"Portable mode requires {', '.join(missing)} (all three).", file=sys.stderr)
        raise SystemExit(2)

    # Step 2: build the job in memory (no config load/save).
    try:
        method = BackupMethod.from_str(args.method)
    except Exception as exc:  # ConfigError from invalid method
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    job = BackupJob(
        source=args.source,
        destination=args.destination,
        method=method,
        name=args.name or "",
        exclude_patterns=list(args.exclude or []),
        include_patterns=list(args.include or []),
        subfolder_stamp=bool(args.stamp),
    )

    # Source must exist and be a directory.
    from pathlib import Path

    if not Path(args.source).is_dir():
        print(f"Source not found or not a directory: {args.source}", file=sys.stderr)
        raise SystemExit(2)
    # Destination must not live inside the source (would recurse / overwrite).
    if is_inside(args.destination, args.source):
        print(f"Destination must not be inside the source: {args.destination}", file=sys.stderr)
        raise SystemExit(2)

    # Step 4: run atomically, config-free. Use a temp data dir unless the user
    # opts in with --data-dir (best-effort logs only; nothing is required).
    import tempfile

    data_dir = args.data_dir or tempfile.mkdtemp(prefix="abackup-portable-")

    # Live console progress: render an in-place bar unless --quiet was given.
    on_progress = _make_console_progress(job) if not args.quiet else None
    result = run_job(
        job,
        data_dir=data_dir,
        portable=True,
        dry_run=args.dry_run,
        prefer_robocopy=True,
        on_progress=on_progress,
    )

    if not args.quiet:
        # Clear the in-place progress line, then print the final summary.
        print(f"\r{job.source} -> {job.destination} [{job.method.value}]")
        print(f"  {result.status}: {format_summary(result.summary)}")
    if result.status == "failed":
        print(result.error or "Backup failed.", file=sys.stderr)
        raise SystemExit(1)
    if result.status == "cancelled":
        print("Backup cancelled.", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(0)


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    # Portable mode: any of the portable group triggers a config-free one-shot
    # backup. All three core args are required together.
    if args.source is not None or args.destination is not None or args.method is not None:
        _run_portable(args)
        return

    if args.show_settings:
        config_dir = get_config_dir(args.config_dir)
        settings = load_settings(args.config_dir)
        print(json.dumps({"config_dir": str(config_dir), **settings.to_dict()}, indent=2))
        return

    if args.list_jobs:
        if args.config_dir is None:
            raise SystemExit("--list-jobs requires --config-dir")
        jobs = load_jobs(args.config_dir)
        if not jobs:
            print("No jobs configured.")
            return
        for j in jobs:
            print(f"{j.name} | {j.method.value} | {j.source} -> {j.destination}")
        return

    if args.export:
        if args.config_dir is None:
            raise SystemExit("--export requires --config-dir")
        path = export_config(args.config_dir, args.export)
        print(f"Exported {len(load_jobs(args.config_dir))} jobs to {path}")
        return

    if args.import_path:
        if args.config_dir is None:
            raise SystemExit("--import requires --config-dir")
        try:
            import_config(args.import_path, args.config_dir, merge=args.merge)
        except Exception as exc:  # ConfigError or OSError -> clean CLI error
            raise SystemExit(1, f"Import failed: {exc}") from exc
        print(f"Imported config into {args.config_dir} (merge={args.merge}).")
        return

    if args.run:
        if args.config_dir is None:
            raise SystemExit("--run requires --config-dir")
        jobs = load_jobs(args.config_dir)
        if not jobs:
            raise SystemExit("No jobs configured. Add a job first.")
        job = find_job_by_name(jobs, args.run)
        if job is None:
            raise SystemExit(f"Job '{args.run}' not found.")
        settings = load_settings(args.config_dir)
        results = _run_batch([job], args, settings)
        _print_batch_summary(results)
        raise SystemExit(_exit_code_for(results))

    if args.run_all or args.run_due:
        if args.config_dir is None:
            raise SystemExit("--run-all/--run-due requires --config-dir")
        jobs = load_jobs(args.config_dir)
        if not jobs:
            print("No jobs configured. Add a job first.")
            return
        settings = load_settings(args.config_dir)
        # Filter by tag when requested.
        if args.tag is not None:
            from abackup.core.jobs import filter_by_tag

            jobs = filter_by_tag(jobs, args.tag)
        # Filter to due jobs when --run-due is set.
        if args.run_due:
            from abackup.core.scheduler import due_jobs

            jobs = due_jobs(jobs)
        if not jobs:
            print("No matching jobs to run.")
            return
        results = _run_batch(jobs, args, settings)
        _print_batch_summary(results)
        raise SystemExit(_exit_code_for(results))

    app = ABackupApp(config_dir=args.config_dir, data_dir=args.data_dir)
    app.run()


if __name__ == "__main__":
    main(sys.argv[1:])
