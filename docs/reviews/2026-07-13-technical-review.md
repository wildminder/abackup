# Technical Review: ABackup

**Date**: 2026-07-13
**Project**: ABackup — a full-featured CLI backup application with a terminal user interface (TUI)
**Stack**: Python ≥3.11, [Textual](https://textual.textualize.io/) ≥0.60 (TUI), `platformdirs`, `rich`, optional `py7zr`; `7-Zip` system binary (preferred). `src`-layout package, `pytest` + `pytest-mock` + `freezegun` + `pytest-cov` (gate `--cov-fail-under=90`).
**Reviewer**: Technical Reviewer

> Adapted from the `skill-techreview` process (frontend-oriented) to a Python/Textual codebase: "components" → modules/screens, "state management" → config/jobs JSON + in-memory state, "design system" → Textual CSS.

## Executive Summary

- **Overall rating: 8.5/10** — a clean, well-tested, production-shaped backup tool with a small, coherent surface area.
- **Strengths ✅**: strict separation of a framework-agnostic, fully unit-tested `core/` engine from the Textual presentation layer; atomic JSON + archive writes everywhere; deterministic IDs/timestamps; real-time, cancellable progress that never blocks the UI; ~95% test coverage with an enforced gate; 7-Zip binary auto-detection (incl. Windows registry) that fixed a real "falls back to slow py7zr" bug.
- **Critical gaps ⚠️**: the `FirstRunScreen` is misnamed (it is the *Add-job* wizard, not a first-run gate — the app opens directly on the main menu); no validation that destination ≠ source and no disk-space pre-check; a single failing file aborts an entire `copy_tree`; logs/manifests are not moved when the storage directory is relocated.

## 1. Core Application Concept

- **Purpose**: back up local folders using one of three methods — **Direct copy** (mirror tree), **Zip** (deterministic `.zip` via stdlib `zipfile`), or **7z** (`.7z` via the multithreaded 7-Zip binary, with a py7zr fallback).
- **Target users**: Windows-first power users who want a scriptable, TUI-driven local backup with concurrent batch runs.
- **Primary user workflows**:
  1. *Add job* — pick source, destination, method ([`first_run.py`](src/abackup/tui/screens/first_run.py:21)).
  2. *Run selected* — single job with live progress ([`run_job.py`](src/abackup/tui/screens/run_job.py:34)).
  3. *Run all* — concurrent batch with aggregate + per-job progress and a Cancel ([`run_all.py`](src/abackup/tui/screens/run_all.py:88)).
  4. *Settings* — global options ([`settings.py`](src/abackup/tui/screens/settings.py:141)).
- **Platform**: desktop terminal (Windows primary; paths/registry logic is Windows-aware but the core is cross-platform).

## 2. UI Architecture & Design System

- **Layout**: classic Textual screen-per-view stack. [`ABackupApp`](src/abackup/tui/app.py:14) mounts [`MainMenuScreen`](src/abackup/tui/screens/main_menu.py:16) on startup; navigation is `push_screen`/`pop_screen` (no router — appropriate for 5 screens).
- **"Component" inventory** (Textual widgets ≈ atoms/molecules):
  - *Atoms*: `Label`, `Input`, `Button`, `RadioButton`, `Checkbox`, `Select`, `ProgressBar`, `Static`, `RichLog`, `ListView`/`ListItem`.
  - *Organisms/screens*: `MainMenuScreen`, `FirstRunScreen` (add-job), `RunJobScreen`, `RunAllScreen`, `SettingsScreen`.
- **Design tokens** (see [`docs/design/design-system.md`](docs/design/design-system.md)): minimal inline CSS in [`app.py`](src/abackup/tui/app.py:15) (center/top, bold title, `$error`/`$text-muted` roles) and a richer block in [`settings.py`](src/abackup/tui/screens/settings.py:19) (`.field`, `.field-label`, `.field-hint`, `#body` scroll container). No external theme; relies on Textual defaults + a couple of CSS variables.
- **Reusability**: screens are thin — they load/persist via `config.py` and delegate all logic to `core/`. Good separation of concerns; screens are effectively "dumb views."

## 3. Data Flows & State Management

- **Persistence model**: two JSON files under a config dir — [`settings.json`](src/abackup/config.py:54) and [`jobs.json`](src/abackup/config.py:74) — plus a data dir with `logs/<job_id>.jsonl` and `manifests/<job_id>.json` ([`config.py`](src/abackup/config.py:111), [`logging.py`](src/abackup/utils/logging.py:10)). All writes are **atomic** (`tempfile.mkstemp` + `os.replace` + `os.fsync`) — see [`_atomic_write`](src/abackup/config.py:26) and the per-file copy/archive temp+rename pattern.
- **State ownership**:
  - *Global*: `Settings` dataclass ([`models.py`](src/abackup/models.py:36)), loaded once per screen action.
  - *Per-job*: `BackupJob` dataclass ([`models.py`](src/abackup/models.py:72)); the batch runner persists each job's `updated_job` under a lock ([`runner.py`](src/abackup/core/runner.py:112)).
  - *Ephemeral UI state*: progress snapshots (`Progress`, [`progress.py`](src/abackup/core/progress.py:30)) and the `threading.Event` cancel flag ([`run_all.py`](src/abackup/tui/screens/run_all.py:40)).
- **Data-flow patterns**:
  - *Config*: screen reads `load_*` → user edits → `save_*` (atomic). No live store; each mutation re-reads/writes the whole JSON list (fine at this scale).
  - *Backup run*: `cli.py`/`RunAllScreen` → [`run_jobs_batch`](src/abackup/core/runner.py:30) (queue + worker-thread pool) → [`run_job`](src/abackup/core/backup.py:45) (orchestrator) → `copy_tree`/`make_zip`/`make_archive` (engine). Progress flows **up** via callbacks marshalled onto the Textual event loop with `call_from_thread` ([`run_all.py`](src/abackup/tui/screens/run_all.py:86)) so the UI never blocks cancellation.
- **Determinism**: job IDs are `uuid5` over a fixed namespace + `source|destination|method|created_at` ([`models.py`](src/abackup/models.py:90)); zip output uses a fixed epoch ([`archive.py`](src/abackup/core/archive.py:20)); clocks are injectable in tests.

## 4. User Interaction Flows

- **Add job** ([`first_run.py`](src/abackup/tui/screens/first_run.py:38)): validates source is an existing dir, requires destination, builds `BackupJob` (name defaults to source basename), appends to `jobs.json`. *Gap*: no check that destination ≠ source, no trailing-slash normalization, no disk-space check.
- **Run selected** ([`run_job.py`](src/abackup/tui/screens/run_job.py:34)): runs one job in a Textual worker thread; `on_progress` updates the `ProgressBar`, current-file label, and `Files N/M · X/Y MB` counts; on completion persists `last_run_at`/`last_status` and shows the result.
- **Run all** ([`run_all.py`](src/abackup/tui/screens/run_all.py:88)): runs every job concurrently (bounded pool, `max_workers`); shows an **aggregate** byte bar + a **per-job** line (`name: NN% — current_file`); Cancel sets a shared `Event` that the engines check between (and mid-) files. Back is disabled until completion to avoid popping the screen while threads run.
- **Settings** ([`settings.py`](src/abackup/tui/screens/settings.py:141)): edits are validated ([`models.py`](src/abackup/models.py:59)) then saved; changing the storage dir atomically relocates `settings.json`+`jobs.json` ([`config.py`](src/abackup/config.py:81)). *Gap*: logs/manifests in the data dir are **not** moved.

## 5. Features Inventory

### Implemented ✅
- **3 backup methods** — copy ([`copy.py`](src/abackup/core/copy.py:68)), zip ([`archive.py`](src/abackup/core/archive.py:27)), 7z with engine auto-selection ([`compression.py`](src/abackup/core/compression.py:146)).
- **7-Zip binary auto-detection** — env override → PATH → Windows registry → common paths ([`compression.py`](src/abackup/core/compression.py:106)).
- **Atomic storage** — config, jobs, per-file copies, archives, logs ([`config.py`](src/abackup/config.py:26), [`copy.py`](src/abackup/core/copy.py:33), [`archive.py`](src/abackup/core/archive.py:62)).
- **Real-time, cancellable progress** — byte-level + per-file + aggregate ([`progress.py`](src/abackup/core/progress.py:30), [`runner.py`](src/abackup/core/runner.py:30), [`run_all.py`](src/abackup/tui/screens/run_all.py:84)).
- **Concurrent batch runner** — bounded worker pool + queue, per-job lock, cancellation ([`runner.py`](src/abackup/core/runner.py:30)).
- **CLI + TUI entry points** — `abackup` script, `--run-all`, `--show-settings`, `--config-dir`/`--data-dir` ([`cli.py`](src/abackup/cli.py:16)).
- **Settings screen** — storage relocation, compression levels, workers, log level, default destination, prefer-py7zr ([`settings.py`](src/abackup/tui/screens/settings.py:141)).
- **Job list with elided paths** — `name [method]: source -> destination` with middle-elision ([`paths.py`](src/abackup/core/paths.py:168), [`main_menu.py`](src/abackup/tui/screens/main_menu.py:44)).
- **Run manifests + JSONL logs** — [`backup.py`](src/abackup/core/backup.py:148), [`logging.py`](src/abackup/utils/logging.py:10).
- **Legacy config migration** — one-time platformdirs → home-based move ([`config.py`](src/abackup/config.py:100)).

### Missing / Placeholder ⚠️
- **First-run wizard** — the screen is named `FirstRunScreen` but is actually the *Add-job* form; there is **no** first-run gate (the app opens on the main menu). Naming debt, not a missing feature per se.
- **Destination ≠ source validation** — not enforced ([`first_run.py`](src/abackup/tui/screens/first_run.py:55)).
- **Disk-space / pre-flight check** — absent; a full destination fails mid-run.
- **Resume / incremental backup** — copy is a full mirror each run (skip-if-identical by size+mtime only).
- **Scheduled / automated runs** — only manual TUI or one-shot `--run-all`; no scheduler.
- **Encryption / integrity verification** — none (no checksum manifest, no GPG).

## 6. Technical Quality Assessment

### Code Quality
- **Typing**: `from __future__ import annotations` + explicit types throughout; frozen `Progress` dataclass for thread-safe snapshots ([`progress.py`](src/abackup/core/progress.py:30)). ✅
- **Organization**: `core/` is presentation-free and unit-tested; `tui/` is thin. Clear module boundaries. ✅
- **Error handling**: typed hierarchy ([`errors.py`](src/abackup/utils/errors.py:6)) with `SourceNotFound`/`DestinationError`/`JobCancelled`/`JobNotFound`/`ConfigError`; atomic-write `except` blocks clean up temp files. ✅
- **Smells**: `run_job.py` calls `load_settings` twice ([`run_job.py`](src/abackup/tui/screens/run_job.py:53)); `make_7z` progress estimate is a heuristic seeded at 50% of source size ([`compression.py`](src/abackup/core/compression.py:414)) — under-reports for highly-compressible data (documented limitation).

### Accessibility
- Textual provides keyboard nav + ARIA-like semantics by default; `q` is bound to quit ([`app.py`](src/abackup/tui/app.py:22)). No custom focus management beyond defaults; ListView selection relies on arrows/mouse. 🟡 Nice-to-have: explicit focus hints / visible selection styling.

### Performance
- **Concurrency**: batch uses a bounded thread pool + queue ([`runner.py`](src/abackup/core/runner.py:122)) — bounded memory, no unbounded spawning. ✅
- **Streaming**: copies/archives stream in 1 MiB chunks ([`copy.py`](src/abackup/core/copy.py:19), [`archive.py`](src/abackup/core/archive.py:24)) — smooth progress, bounded RAM. ✅
- **7-Zip CPU oversubscription** 🟢: `max_workers` caps *job* count, but each 7z subprocess uses all cores → many concurrent 7z jobs oversubscribe CPU. Consider capping threads per 7z or documenting the trade-off.
- **No virtual scrolling needed** — job lists are small.

### Testing
- **Coverage ~95%** with an enforced `--cov-fail-under=90` gate ([`pyproject.toml`](pyproject.toml:34)). ✅
- **Infrastructure**: `pytest` + `pytest-mock` + `freezegun` (deterministic time/IDs) + Textual `run_test()` pilot for TUI. ✅
- **Gaps** 🟡: `utils/logging.py` has a small test ([`test_logging.py`](tests/test_logging.py)) but manifest/log rotation is untested; no fuzz/property tests for path elision edge cases beyond the unit set in [`test_paths.py`](tests/test_paths.py).

## 7. Recommendations

### High Priority (implement first)
- [ ] **IMP-001** Rename `FirstRunScreen`→`AddJobScreen` / `first_run.py`→`add_job.py` to match its actual role (the app has no first-run gate). *Effort: low.*
- [ ] **IMP-002** Add `destination != source` + trailing-slash normalization + a basic disk-space pre-check in the add-job screen. *Effort: medium.*
- [ ] **IMP-005** Make `copy_tree` skip-and-continue (or collect per-file errors) instead of aborting the whole tree on one `DestinationError`. *Effort: medium.*

### Medium Priority
- [ ] **IMP-007** Relocate `logs/`+`manifests/` when the storage dir changes (currently only `settings.json`+`jobs.json` move). *Effort: low.*
- [ ] **IMP-006** Replace mtime-equality skip with size-only (or hash) to be robust on FAT32 (2 s mtime). *Effort: low.*
- [ ] **NTH-006** Append a time component (or version) to archive names so same-day re-runs don't `os.replace` the previous archive. *Effort: low.*

### Low Priority
- [ ] **IMP-003** Cache `load_settings` once in `RunJobScreen._run` instead of two calls. *Effort: trivial.*
- [ ] **NTH-001** Add a light/dark theme toggle or richer CSS variables. *Effort: low.*
- [ ] **NTH-002** Add visible selection/focus hints in the job ListView. *Effort: low.*
- [ ] **NTH-005** Document or cap 7-Zip CPU oversubscription under many concurrent jobs. *Effort: low.*

## 8. Conclusion

ABackup is a **well-architected, thoroughly tested** backup tool. The core/UI split, atomic writes, deterministic IDs, and real-time cancellable progress are genuine strengths. The highest-value next steps are **clarity** (rename the misnamed add-job screen), **safety** (destination≠source + disk-space checks, resilient copy), and **consistency** (move logs/manifests on relocation). None are architectural; the foundation is solid.

## Appendix
- **File structure**: `src/abackup/{cli,config,models}.py`, `core/{backup,runner,compression,copy,archive,paths,progress,jobs}.py`, `tui/{app,__init__}.py` + `tui/screens/{main_menu,first_run,run_job,run_all,settings}.py`, `utils/{errors,logging}.py`; tests mirror this in `tests/`.
- **Dependencies**: runtime `textual`, `platformdirs`, `rich`, `py7zr` (optional); dev `pytest`, `pytest-mock`, `pytest-cov`, `freezegun`.
- **Config files**: [`pyproject.toml`](pyproject.toml) (build, deps, pytest `addopts`, `pythonpath=["src"]`).
- **Storage layout**: `<config>/settings.json`, `<config>/jobs.json`, `<data>/logs/<job_id>.jsonl`, `<data>/manifests/<job_id>.json`.
