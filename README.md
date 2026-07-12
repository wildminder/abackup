# ABackup

A full-featured CLI backup application with a proper **terminal user interface (TUI)**
built with [Textual](https://textual.textualize.io/).

On first run, ABackup interactively asks for:

1. **Source folder** — the local folder to back up.
2. **Destination folder** — where backups are written.
3. **Method** — how to back up:
   - **Direct copy** — mirrors the source tree into the destination.
   - **Zip archive** — creates `<source_name>_<YYYY-MM-DD>.zip` in the destination.

Jobs and settings are stored as JSON under a config directory in your home folder
(`Documents\abackup` on Windows, `~/abackup` elsewhere) and survive restarts.

## Install

```bash
# from the project root (requires Python 3.11+)
call source .venv/bin/activate
uv pip install -e .
```

## Usage

Launch the app (opens the TUI):

```bash
abackup
# or
python -m abackup
```

### Command-line flags

| Flag | Description |
|------|-------------|
| `--version` | Print version and exit. |
| `--config-dir DIR` | Override the config directory (useful for portable / automated use). |
| `--data-dir DIR` | Override the data directory (logs, manifests). |
| `--reset` | Reset the first-run flag so the setup wizard shows again (requires `--config-dir`). |
| `--run-all` | Run every configured job non-interactively and print a summary (requires `--config-dir`). |
| `--workers N` | Number of concurrent backup workers for `--run-all` (default: `max_workers` setting). |
| `--show-settings` | Print the resolved config directory and current settings as JSON, then exit. |

Example (portable / automated):

```bash
abackup --config-dir ./my-config --data-dir ./my-data
abackup --reset --config-dir ./my-config
abackup --run-all --config-dir ./my-config --workers 4
```

### Running all jobs

- In the TUI, use the **Run all** button on the main menu to back up every job
  concurrently (progress + per-job results are shown on the run-all screen).
- From the CLI, `abackup --run-all --config-dir DIR` runs all jobs and prints a
  summary without opening the terminal UI.

Jobs run concurrently via a bounded pool of worker threads fed from a queue, so a
large number of jobs is processed with bounded memory. The worker count is
controlled by the `max_workers` setting (default `4`) or the `--workers` flag. A
failing job never stops the others, and each job's status is persisted.

While a batch runs you can press **Cancel** to abort *all* jobs. The request is
signalled through a shared event that the copy/zip routines check between (and,
for copies, during) files, so in-flight jobs stop promptly and any queued jobs
are marked `cancelled` without running. The summary reports how many jobs
succeeded, failed, and were cancelled.

### Realtime progress

Both backup methods report progress **in real time** so you can watch a job as
it runs:

- **Byte-level progress** — the source tree is pre-scanned to compute the total
  size, then each 1 MiB chunk updates the progress bar smoothly (no more
  "0% → 100%" jumps on large files).
- **Current file + counts** — the run-job screen shows the file being copied or
  zipped plus `Files N/M · X/Y MB`.
- **Per-job + overall** — the run-all screen shows an aggregate overall bar
  (summed bytes across all concurrent jobs) and a live line per job with its
  percentage and current file.

Progress is emitted from the worker threads and marshalled onto the UI thread,
so it never blocks cancellation: pressing **Cancel** still aborts all jobs
promptly.

### Settings

Open the **Settings** screen from the main menu to tune global options:

- **Storage location** — the config directory. Changing it moves all existing data
  (jobs, settings, logs) to the new location atomically.
- **Zip compression level** — `0` (store, no compression) to `9` (max). Default `6`.
  Applies to the `zip` backup method.
- **Max workers** — default number of concurrent jobs for *Run all jobs*.
- **Default destination** — pre-filled destination for new jobs.
- **Log level** — `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

You can also inspect the resolved config directory and current settings non-interactively:

```bash
python -m abackup --show-settings
# => {"config_dir": "...", "zip_compression_level": 6, "max_workers": 4, ...}
```

## Storage

`<config>` defaults to `Documents\abackup` on Windows and `~/abackup` elsewhere
(overridable with `--config-dir` or the Settings screen). `<data>` defaults to
`<config>` unless `--data-dir` is given.

- **Settings:** `<config>/settings.json` (first-run flag, defaults).
- **Jobs:** `<config>/jobs.json` (array of backup jobs).
- **Run logs:** `<data>/logs/<job_id>.jsonl`.
- **Manifests:** `<data>/manifests/<job_id>.json`.

All writes are atomic (temp file + `os.replace`).

## Development & tests

```bash
call source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
# with coverage gate
pytest --cov=src/abackup --cov-fail-under=90
```

## Architecture

- `abackup/core/*` — framework-agnostic, fully unit-tested backup logic.
- `abackup/models.py` — `Settings` / `BackupJob` / `BackupMethod`.
- `abackup/config.py` — atomic JSON persistence.
- `abackup/tui/*` — Textual screens (first-run wizard, main menu, run-job).
- `abackup/cli.py` — entry point and flags.

Determinism: timestamps are injectable, IDs use `uuid5` (not random), and zip
output is byte-reproducible.
