# Implemented Features — ABackup

**Date**: 2026-07-13
**Status**: ✅ shipped in the current codebase.

## Backup Methods
- **Direct copy** — mirror source tree to destination, atomic per-file (temp+rename), 1 MiB chunks, skip-if-identical by size+mtime. [`copy.py`](../../src/abackup/core/copy.py:68)
- **Zip** — deterministic `.zip` via stdlib `zipfile` with a fixed epoch (byte-identical output for identical trees). [`archive.py`](../../src/abackup/core/archive.py:27)
- **7z** — `.7z` via the 7-Zip system binary (multithreaded), with a py7zr fallback. Engine auto-selected by `make_archive`. [`compression.py`](../../src/abackup/core/compression.py:146)

## 7-Zip Integration
- **Binary auto-detection** — `SEVEN_ZIP_PATH` env → PATH → Windows registry (`SOFTWARE\7-Zip`) → common install paths. [`compression.py`](../../src/abackup/core/compression.py:106)
- **Realtime 7z progress** — polls the growing temp archive file size (avoids pipe-buffering stalls). [`compression.py`](../../src/abackup/core/compression.py:414)
- **Engine toggle** — `prefer_py7zr` setting forces the py7zr fallback. [`models.py`](../../src/abackup/models.py:36)

## TUI (Textual)
- **Main menu** — job list with elided `name [method]: source -> destination` labels, Run / Run-all / Delete / Settings / Quit. [`main_menu.py`](../../src/abackup/tui/screens/main_menu.py:16), [`paths.py`](../../src/abackup/core/paths.py:168)
- **Add-job wizard** — source (validated as existing dir), destination, method radio. [`first_run.py`](../../src/abackup/tui/screens/first_run.py:21)
- **Run selected** — single job with live `ProgressBar`, current-file label, `Files N/M · X/Y MB` counts, result status. [`run_job.py`](../../src/abackup/tui/screens/run_job.py:34)
- **Run all** — concurrent batch (bounded worker pool), aggregate byte bar + per-job lines, Cancel via shared `threading.Event`. [`run_all.py`](../../src/abackup/tui/screens/run_all.py:88)
- **Settings** — storage relocation, compression levels, workers, log level, default destination, prefer-py7zr. [`settings.py`](../../src/abackup/tui/screens/settings.py:141)

## Storage & State
- **Atomic JSON** — `settings.json` + `jobs.json` via temp+`os.replace`+`fsync`. [`config.py`](../../src/abackup/config.py:26)
- **Deterministic IDs** — `uuid5` over content + `created_at`. [`models.py`](../../src/abackup/models.py:90)
- **Run manifests + JSONL logs** — per-job `manifests/<id>.json` and `logs/<id>.jsonl`. [`backup.py`](../../src/abackup/core/backup.py:148), [`logging.py`](../../src/abackup/utils/logging.py:10)
- **Storage relocation** — atomically moves `settings.json`+`jobs.json` to a new dir. [`config.py`](../../src/abackup/config.py:81)
- **Legacy migration** — one-time move from old platformdirs path. [`config.py`](../../src/abackup/config.py:100)

## CLI
- **`abackup` script** — `python -m abackup` or the installed entry point. [`cli.py`](../../src/abackup/cli.py:16), [`__main__.py`](../../src/abackup/__main__.py)
- **Flags** — `--version`, `--config-dir`, `--data-dir`, `--run-all`, `--workers`, `--show-settings`. [`cli.py`](../../src/abackup/cli.py:16)

## Engineering
- **Typed models** — `Settings`/`BackupJob`/`BackupMethod` with `validate()`. [`models.py`](../../src/abackup/models.py:36)
- **Typed errors** — `SourceNotFound`/`DestinationError`/`JobCancelled`/`JobNotFound`/`ConfigError`. [`errors.py`](../../src/abackup/utils/errors.py:6)
- **~95% test coverage** with an enforced `--cov-fail-under=90` gate; `pytest`+`pytest-mock`+`freezegun`+Textual `run_test()`. [`pyproject.toml`](../../pyproject.toml:34)
- **Cancellation throughout** — engines check a `threading.Event` between/within file chunks. [`runner.py`](../../src/abackup/core/runner.py:30), [`copy.py`](../../src/abackup/core/copy.py:19)
