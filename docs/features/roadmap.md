# Roadmap — ABackup

**Date**: 2026-07-13
**Source**: [issues-improvements.md](../reviews/issues-improvements.md) + review gaps.

> Phases are ordered by value. No time estimates (per project rules).

## Phase 1 — Safety & Clarity (do first)
- **IMP-001** Rename `FirstRunScreen`→`AddJobScreen` (it is the add-job wizard, not a first-run gate). *low effort*
- **IMP-002** Add-job validation: reject `destination == source` (or inside source); pre-flight disk-space check via `shutil.disk_usage`. *medium*
- **IMP-005** `copy_tree` should skip-and-continue on a single file error, collecting `failed_files` instead of aborting the whole tree. *medium*

## Phase 2 — Robustness & Consistency
- **IMP-006** Replace mtime-equality skip with size-only (or optional hash) to be FAT32-safe. *low*
- **IMP-007** `relocate_storage` should also move `logs/`+`manifests/` (currently only `settings.json`+`jobs.json`). *low*
- **NTH-006** Append a time/run-counter to archive names so same-day re-runs don't `os.replace` the prior archive. *low*
- **Schema versioning** Add `schema_version` to `Settings`/`BackupJob` for forward-compatible migrations. *low*

## Phase 3 — Polish & DX
- **IMP-003** Cache `load_settings` once in `RunJobScreen._run` (currently called twice). *trivial*
- **NTH-001** Light/dark theme toggle + small CSS-variable palette. *low*
- **NTH-002** Visible selection/focus styling for the job `ListView` + key-help footer. *low*
- **NTH-005** Document or cap 7-Zip CPU oversubscription under many concurrent jobs (e.g., `-mmt=N` when `max_workers>1`). *low*

## Phase 4 — New Capabilities (backlog)
- **Incremental / rsync-style copy** — copy only changed files (hash or mtime+size), with a `--dry-run` preview.
- **Exclude patterns** — glob/ignore-file support per job (skip temp/cache dirs).
- **Encryption** — optional GPG/age wrapper for archives; or 7z `-p` with a stored keyring.
- **Integrity verification** — post-copy checksum manifest; verify mode that re-checks destinations.
- **Scheduler** — one-shot `--run-all` exists; add a `abackup schedule` (Task Scheduler / cron) helper or an in-app timer.
- **Retention policy** — keep-last-N or prune by age for archives in a `backups/` history folder.
- **Cross-platform data-dir parity** — ensure `get_data_dir` is overridable consistently with `default_config_dir` injection.
- **CI/lint** — add `ruff` config + GitHub Actions running `pytest --cov` on PRs.

## Suggested Sequencing
```mermaid
graph LR
    P1[Phase 1: Safety] --> P2[Phase 2: Robustness]
    P2 --> P3[Phase 3: Polish]
    P3 --> P4[Phase 4: Capabilities]
```
