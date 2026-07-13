# Issues & Improvements — ABackup

**Date**: 2026-07-13
**Source review**: [technical-review.md](2026-07-13-technical-review.md)

## Legend
- 🔴 **High** — correctness/safety/clarity; fix before next release
- 🟡 **Medium** — robustness/consistency; schedule soon
- 🟢 **Low** — polish/nicety; backlog

## Summary
- 🔴 High: 3
- 🟡 Medium: 3
- 🟢 Low: 4
- **Total: 10**

---

## 🔴 High Priority

### IMP-001 — Misnamed `FirstRunScreen` (clarity)
- **Where**: [`first_run.py`](../../src/abackup/tui/screens/first_run.py:21), [`app.py`](../../src/abackup/tui/app.py:14)
- **Problem**: The screen is the *Add-job* wizard, but its name implies a first-run gate. The app actually opens directly on `MainMenuScreen` — there is no first-run flow. This misleads contributors and users.
- **Fix**: Rename `FirstRunScreen`→`AddJobScreen`, `first_run.py`→`add_job.py`, and update `app.py` import + any references. No behavior change.
- **Effort**: low

### IMP-002 — No destination≠source / disk-space validation (safety)
- **Where**: [`first_run.py`](../../src/abackup/tui/screens/first_run.py:55)
- **Problem**: A user can set destination = source (or a subfolder of source), and there is no pre-flight disk-space check. Both cause confusing mid-run failures or infinite copies.
- **Fix**: In the add-job submit handler, (a) reject `destination` that is equal to or inside `source`; (b) compute `bytes_total` and compare against `shutil.disk_usage(destination).free` (with a margin); show a clear error before saving.
- **Effort**: medium

### IMP-005 — `copy_tree` aborts whole tree on one file error (robustness)
- **Where**: [`copy.py`](../../src/abackup/core/copy.py:68)
- **Problem**: A single `DestinationError` (e.g., one locked file) raises and aborts the entire job, leaving a partial mirror with no record of what failed.
- **Fix**: Collect per-file errors into a list; continue copying the rest; return a result that includes `failed_files`. Surface the count in the run summary and manifest.
- **Effort**: medium

---

## 🟡 Medium Priority

### IMP-006 — mtime-equality skip is fragile on FAT32 (robustness)
- **Where**: [`copy.py`](../../src/abackup/core/copy.py:33)
- **Problem**: Skip-if-identical uses `size` + `mtime`. FAT32 truncates mtime to 2 s, so identical files may be re-copied.
- **Fix**: Use size-only equality (or add an optional hash mode) for the skip decision; document the trade-off.
- **Effort**: low

### IMP-007 — Storage relocation drops logs/manifests (consistency)
- **Where**: [`config.py`](../../src/abackup/config.py:81)
- **Problem**: `relocate_storage` moves only `settings.json` + `jobs.json`. The `logs/` and `manifests/` in the data dir are left behind, breaking history after a move.
- **Fix**: Also move/relink the data dir (or copy `logs/`+`manifests/` to the new data dir) atomically during relocation.
- **Effort**: low

### NTH-006 — Same-day archive re-runs overwrite prior archive (data loss)
- **Where**: [`compression.py`](../../src/abackup/core/compression.py:146), [`archive.py`](../../src/abackup/core/archive.py:27)
- **Problem**: Archive names are `<source_basename>_<YYYY-MM-DD>.<ext>`. A second run the same day `os.replace`s the previous archive, silently losing it.
- **Fix**: Append a time component (e.g., `_HHMMSS`) or a run counter; or keep a `backups/` history folder.
- **Effort**: low

---

## 🟢 Low Priority

### IMP-003 — Redundant `load_settings` call (cleanup)
- **Where**: [`run_job.py`](../../src/abackup/tui/screens/run_job.py:53)
- **Problem**: `load_settings` is called twice in `_run`. Minor waste; could drift if settings change between calls.
- **Fix**: Load once, reuse.
- **Effort**: trivial

### NTH-001 — Theme/visual polish (design)
- **Where**: [`app.py`](../../src/abackup/tui/app.py:15), [`settings.py`](../../src/abackup/tui/screens/settings.py:19)
- **Problem**: Only minimal inline CSS; relies on Textual defaults. No light/dark toggle.
- **Fix**: Add a small CSS-variable theme and a light/dark toggle in Settings.
- **Effort**: low

### NTH-002 — Visible selection/focus hints (accessibility)
- **Where**: [`main_menu.py`](../../src/abackup/tui/screens/main_menu.py:44)
- **Problem**: ListView selection styling is default; no explicit focus hint for keyboard users.
- **Fix**: Add a highlighted border/background for the selected `ListItem` and a one-line key-help footer.
- **Effort**: low

### NTH-005 — 7-Zip CPU oversubscription under many jobs (performance)
- **Where**: [`runner.py`](../../src/abackup/core/runner.py:122), [`compression.py`](../../src/abackup/core/compression.py:414)
- **Problem**: `max_workers` caps *job* concurrency, but each 7z subprocess uses all cores. Many concurrent 7z jobs oversubscribe CPU and slow everything.
- **Fix**: Document the trade-off, or cap 7z threads (`-mmt=N`) when `max_workers>1`, or serialize 7z jobs while parallelizing copies.
- **Effort**: low

---

## Roadmap Phasing (suggested)
1. **Phase 1 (safety + clarity)**: IMP-001, IMP-002, IMP-005.
2. **Phase 2 (robustness + consistency)**: IMP-006, IMP-007, NTH-006.
3. **Phase 3 (polish)**: IMP-003, NTH-001, NTH-002, NTH-005.
