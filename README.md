<div align="center">

# 「 ABackup 」

A terminal-based backup utility featuring an interactive console user interface and CLI automation.

<img width="90%" alt="ABackup TUI main job list" src="https://github.com/user-attachments/assets/4121a211-7ca6-4090-870a-e35c59a0ab2d" />

<p>
    
[![Python](https://img.shields.io/badge/Python-3.11+-3670A0?style=flat-square&logo=python&logoColor=ffdd54)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-6c757d?style=flat-square)](#)
[![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)](#)

</p>
</div>


## ❯ Overview

ABackup is a local backup manager designed to be self-contained and flexible. It provides a Terminal User Interface (TUI) for interactive configuration, run management, and active progress monitoring, alongside a headless Command Line Interface (CLI) tailored for automation, custom scripting, and task scheduling.

### Supported Engines
‣ **Direct Copy**: Mirrors folder hierarchies locally (uses native Windows `robocopy` when available, falling back to Python-based filesystem utilities).  
‣ **Zip Archive**: Compresses data structures to standard `.zip` files using Python’s built-in, deterministic `zipfile` module.  
‣ **7z Archive**: Compresses data structures to `.7z` archives. It prioritizes the multithreaded system-installed 7-Zip binary (automatically resolved via system `PATH` or registry) and falls back to the pure-Python `py7zr` library.

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Features & Safeguards

### Transfer Reporting
‣ **Byte-Level Progression**: Scans directory sizing prior to transmission, driving progress bars by relative data volume rather than file count steps.  
‣ **TUI Counters**: Live display monitors active targets, aggregate transfer progress, relative paths, and size footprints.  
‣ **Thread Control**: Cancellation requests are captured immediately between block read loops to terminate jobs and minimize lingering artifacts.

### Adjustments & Engines
‣ **Zip Tuning**: Compression ratios range from `0` (no compression) to `9` (maximum).  
‣ **7z Customizations**: Configurable LZMA2 compression parameters (`0-9`) coupled with py7zr engine overrides.  
‣ **Path Relativization**: Stores source paths relative to configuration targets when enabled, allowing configs to remain portable across fluctuating external storage drive letters.  
‣ **Native Delegation**: Uses standard Windows `robocopy` utilities if available for expedited direct copy executions.

### System Safety
‣ **Per-Job Auditing**: Retains historical metrics covering execution times, durations, block counts, and exceptions inside structured logs.  
‣ **Storage Capacity Estimation**: Verifies source size against destination capacity prior to launching transfers to prevent write failures.

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Install

Requires Python 3.11+.

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or .venv\Scripts\activate on Windows

# Install package
uv pip install -e .
```

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Usage

Launch the terminal interface:

```bash
abackup
# or
python -m abackup
```

### CLI Command Flags

| Flag | Description |
| :--- | :--- |
| `--version` | Display application version and exit. |
| `--config-dir DIR` | Override default configuration directory location. |
| `--data-dir DIR` | Override directory where logs and manifests are written. |
| `--run-all` | Execute all saved jobs in headless mode (requires `--config-dir`). |
| `--run-due` | Execute only scheduled, due jobs (requires `--config-dir`). |
| `--run NAME` | Execute a single target job by name. |
| `--list-jobs` | List configured jobs and targets without execution. |
| `--tag TAG` | Filter target execution tasks by tag. |
| `--workers N` | Set the max concurrent worker thread pool. |
| `--dry-run` | Compute jobs and schedules without performing disk writes. |
| `--export PATH` | Export all jobs and settings to a JSON file. |
| `--import PATH` | Import configurations from a backup JSON. |
| `--merge` | Prevent overwriting existing configurations during import. |
| `--show-settings` | Output currently loaded settings configurations as JSON. |

*Examples:*
```bash
# Execute single named job
abackup --run "Documents" --config-dir ./my-config

# Execute all due tasks with 4 concurrent threads
abackup --run-due --config-dir ./my-config --workers 4

# Export portable settings
abackup --export ./portable.json --config-dir ./my-config
```

### Headless / scheduled runs

* `--run NAME --config-dir DIR` — run one job and exit.
* `--run-all --config-dir DIR` — run every job; `--run-due` restricts to due jobs.
* `--tag TAG` — limit a batch to jobs carrying that tag.
* `--list-jobs` — enumerate jobs for wrapper scripts.

A missing job name or malformed import file exits non-zero with a message on stderr/stdout.

### Portable config (export / import)

* **Export:** `abackup --export portable.json --config-dir DIR` writes jobs + settings to one JSON file. Also in the TUI: **Main menu → Export config / Import config**.
* **Import:** `abackup --import portable.json --config-dir DIR` replaces the target config. Add `--merge` to combine by id instead of overwriting.

With **Store paths relative to config directory** enabled, source/destination paths are saved relative to the config dir and re-expanded on load — so a config copied across drives or mount points still resolves. Paths outside the config dir are always stored absolute.

### Concurrency & cancellation

Jobs run on a bounded worker thread pool fed from a queue. Worker count: `max_workers` (default `4`) or `--workers`. A failing job doesn't stop the others; each job's status is persisted.

**Cancel** aborts all jobs via a shared event that copy/zip routines check between (and for copies, during) files. In-flight jobs stop promptly; queued jobs are marked `cancelled`. The summary reports succeeded / failed / cancelled counts.

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Portable one-shot backup

Skip config files entirely — supply source, destination and method on the command line. The job is built in memory; no `jobs.json` or `settings.json` is created or read.

```bash
abackup --source C:\Users\me\Documents --destination D:\Backups\docs   --method copy
abackup --source C:\Users\me\Photos  --destination D:\Backups\photos --method zip
abackup --source C:\Users\me\Data    --destination D:\Backups\data   --method 7z
```

| Flag | Meaning |
|------|---------|
| `--source DIR` | Source folder (required). |
| `--destination DIR` | Destination folder (required). |
| `--method {copy,zip,7z}` | Backup method (required). |
| `--name NAME` | Display name only (not persisted). |
| `--exclude PATTERN` | Exclude glob; repeatable. |
| `--include PATTERN` | Include glob; repeatable. |
| `--stamp` | Write into a timestamped subfolder of the destination. |
| `--dry-run` | Plan only; write nothing. |
| `--quiet` | Suppress progress/summary output (exit code still set). |
| `--data-dir DIR` | Optional best-effort log location (defaults to a temp dir). |

| Exit | Meaning |
|----:|---------|
| `0` | Backup succeeded. |
| `1` | Backup failed (e.g. destination is an existing file). |
| `2` | Invalid usage (missing args, source missing, destination inside source). |

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Run history & safety

* **Per-job history** — each run records timestamp, duration, file count, size, success/failure. Browse via the **History** screen.
* **Persistent log** — append-only human-readable log next to the config, for diagnosing failures outside the TUI.
* **Subfolder stamping** — write each backup into `destination/<YYYY-MM-DD_HHMMSS>/` so runs coexist without overwriting.
* **Free-space check** — warns before a run if the destination has insufficient space (never blocks).

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Storage layout

Configuration parameters resolve defaults to `Documents\abackup` on Windows systems, and `~/abackup` on POSIX systems.

```text
<config-dir>/
├── settings.json              # Global program defaults
├── jobs.json                  # Defined execution jobs
├── logs/
│   ├── abackup.log            # Aggregated activity log
│   └── <job_id>.jsonl         # Individual job terminal logs
├── history/
│   └── <job_id>.jsonl         # Append-only run histories
└── manifests/
    └── <job_id>.json          # Files manifest indexing
```

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Settings

* **Storage location** — config directory. Changing it moves all data (jobs, settings, logs) atomically.
* **Zip compression level** — `0`–`9`, default `6`. Zip method only.
* **7z compression level** — `0`–`9`, default `3`. Sets LZMA2 `preset`: `0`=copy, `1`=fastest, `3`=fast, `5`=normal, `7`=max, `9`=ultra. Independent of Zip level.
* **Prefer py7zr** — forces the pure-Python `py7zr` engine for 7z jobs (single-threaded, non-solid, slower). Default off → uses the multithreaded system 7-Zip binary (auto-detected; `SEVEN_ZIP_PATH` override). Zip method is unaffected.
* **Max workers** — default concurrent jobs for *Run all*.
* **Default destination** — pre-filled destination for new jobs.
* **Log level** — `DEBUG` · `INFO` · `WARNING` · `ERROR` · `CRITICAL`.
* **Notify on finish** — desktop notification on batch completion (`plyer`, best-effort).
* **Sound on failure** — system beep if any job in a run fails.
* **Prefer robocopy (Windows)** — default on: copy method delegates to `robocopy.exe` when present. Fallback to the Python engine otherwise. Disable to force Python.

```bash
python -m abackup --show-settings
# => {"config_dir": "...", "zip_compression_level": 6,
#     "seven_zip_compression_level": 3, "max_workers": 4, ...}
```

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Development & tests

Execute tests inside an active virtual environment:

```bash
# Install testing dependencies
uv pip install -e ".[dev]"

# Execute unit-tests
pytest

# Execute coverage threshold verification
pytest --cov=src/abackup --cov-fail-under=90
```

<p align="center">┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈</p>

## ❯ Architecture

The system is split into distinct modules:

```text
abackup/
├── core/          # Main backup, archive, and transfer implementations
├── tui/           # Console UI layouts, widgets, and user prompts
├── cli.py         # Argument translation and automation flow logic
├── config.py      # Core input validation and disk persistency controllers
└── models.py      # Structured system configuration objects
```
