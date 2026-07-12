# Plan: Explicit archive format choice (zip vs 7z) per job

## Problem
- 7z compression (via py7zr) is slow, and the previous design *auto-preferred* 7z
  whenever available, so users could not easily choose the faster `.zip` output.
- There was no explicit, per-job way to say "I want a zip" vs "I want a 7z".

## Decision
Make the archive **format an explicit per-job choice** by adding a third backup
method, and turn the old global "prefer 7z over zip" toggle into an engine-choice
toggle for 7z jobs (py7zr library vs the faster system 7-Zip binary).

### `BackupMethod` (models.py)
- `COPY = "copy"` (unchanged)
- `ZIP = "zip"` (unchanged — stdlib `zipfile`, fast, deterministic)
- `SEVEN_ZIP = "7z"` (NEW — LZMA2 via py7zr or system 7-Zip)

### `Settings` (models.py)
- Rename `prefer_7z: bool` → `prefer_py7zr: bool = True`.
  - `True` (default): 7z jobs use the **py7zr** pure-Python library.
  - `False`: 7z jobs prefer the **system 7-Zip binary** (usually faster) when
    present, falling back to py7zr if the binary is missing.
- `from_dict` maps a legacy `prefer_7z` key to `prefer_py7zr` for backward compat.

### `compression.make_archive` (core/compression.py)
New signature adds `prefer_py7zr: bool = True` alongside `prefer_7z: bool = True`:
- `prefer_7z=False` → `make_zip` (deterministic `.zip`).
- `prefer_7z=True` (want 7z):
  - `prefer_py7zr and _have_py7zr()` → `make_7z_py7zr`
  - `find_7z() is not None` → `make_7z` (system binary)
  - `_have_py7zr()` → `make_7z_py7zr` (binary missing but lib present)
  - else → `make_zip` (safety net: no 7z engine at all)

### `backup.run_job` (core/backup.py)
Replace `prefer_7z` param with `prefer_py7zr: bool = True` and dispatch on method:
- `COPY` → `copy_tree`
- `ZIP` → `make_zip(compress_level=...)`
- `SEVEN_ZIP` → `make_archive(prefer_7z=True, prefer_py7zr=prefer_py7zr, compress_level=...)`

### `runner.run_jobs_batch` (core/runner.py)
Rename `prefer_7z` → `prefer_py7zr` (default from `settings.prefer_py7zr`), pass to `run_job`.

### CLI / TUI threading
- `cli.py --run-all`: pass `prefer_py7zr=settings.prefer_py7zr`.
- `tui/screens/run_job.py`: pass `prefer_py7zr=load_settings(...).prefer_py7zr`.
- `tui/screens/run_all.py`: pass `prefer_py7zr=settings.prefer_py7zr`.

### Add-job form (tui/screens/first_run.py)
Add a third `RadioButton("7z archive", id="seven_zip")` to the method `RadioSet`
and resolve: `seven_zip` → `SEVEN_ZIP`, `zip` → `ZIP`, else `COPY`.

### Settings screen (tui/screens/settings.py)
Rename the checkbox to `prefer_py7zr` with label
"Prefer py7zr library for 7z (else system 7-Zip binary)" and a hint explaining
the system binary is usually faster.

## Tests
- `test_models.py`: `SEVEN_ZIP` coercion + `from_str` + legacy `prefer_7z` mapping.
- `test_backup.py`: zip job now calls `make_zip` (update the compression-level
  spy to patch `make_zip`); add `test_run_job_seven_zip` asserting a `.7z` is
  produced; rename `prefer_7z=` → `prefer_py7zr=` in zip/cancel tests.
- `test_compression.py`: add `prefer_py7zr=False` → system-binary path test.
- `test_runner.py` / `test_cli.py` / `test_tui.py`: rename `prefer_7z` → `prefer_py7zr`
  in mock signatures and calls.
- `test_tui.py`: add an add-job test selecting the `7z` radio → `method == "7z"`.

## Docs
- `README.md`: method list (copy / zip / 7z); settings describes `prefer_py7zr`
  engine choice; note 7z is slower but compresses better, zip is fast/deterministic.

## Atomicity / safety
No change to storage format beyond the `Settings` key rename (handled by
`from_dict` mapping). Job `method` values are explicit strings persisted as-is.

---

# Addendum: separate 7z compression level (LZMA2 preset)

## Problem
The previous design shared a single `zip_compression_level` (0–9, default 6) for
both the `zip` and `7z` methods. 7z at level 6/9 is slow, and users could not tune
the 7z LZMA2 `preset` independently of the zip level.

## Decision
Add a **separate** `seven_zip_compression_level` (0–9, default **3 = fast**) to
`Settings`, independent of `zip_compression_level`. The value is passed straight
through to the 7z engine as the LZMA2 `preset` (py7zr) or `-mx` flag (system 7z).

### `Settings` (models.py)
- `seven_zip_compression_level: int = 3` (NEW).
- `validate()` rejects values outside `0..9` (mirrors `zip_compression_level`).
- `from_dict` keeps the default `3` when the key is absent (backward compatible).

### `compression.make_archive` (core/compression.py)
Unchanged: already forwards `compress_level` to both `make_7z_py7zr`
(`filters=[{"id": py7zr.FILTER_LZMA2, "preset": compress_level}]`) and `make_7z`
(`-mx{compress_level}`).

### `backup.run_job` (core/backup.py)
- New param `seven_zip_compression_level: int = 3`.
- `ZIP` branch → `make_zip(compress_level=zip_compression_level, ...)`.
- `SEVEN_ZIP` branch → `make_archive(compress_level=seven_zip_compression_level, ...)`.
- The two levels are fully independent (verified by `test_run_job_zip_level_independent_from_seven_zip_level`).

### `runner.run_jobs_batch` (core/runner.py)
- New param `seven_zip_compression_level: int | None = None`; defaults to
  `load_settings(config_dir).seven_zip_compression_level`; passed to `run_job`.

### CLI / TUI threading
- `cli.py --run-all`: `seven_zip_compression_level=settings.seven_zip_compression_level`.
- `tui/screens/run_job.py`: `seven_zip_compression_level=load_settings(...).seven_zip_compression_level`.
- `tui/screens/run_all.py`: `seven_zip_compression_level=settings.seven_zip_compression_level`.

### Settings screen (tui/screens/settings.py)
- New `Input(id="sz_level")` with hint describing the LZMA2 preset scale
  (`0` copy … `3` fast … `9` ultra, default 3). Parsed as int, validated by
  `Settings.validate()`, persisted via `Settings(...)`.

## Tests
- `test_models.py`: default `3`, round-trip, `from_dict` default, `validate` rejects `10`/`-1`.
- `test_backup.py`: `test_run_job_uses_seven_zip_compression_level` (spy on
  `make_archive` captures `compress_level`); `test_run_job_zip_level_independent_from_seven_zip_level`.
- `test_runner.py`: `test_run_jobs_batch_passes_seven_zip_level_from_settings` and
  `test_run_jobs_batch_explicit_seven_zip_level_overrides_settings` (spy on `run_job`).
- `test_cli.py`: `test_cli_run_all_passes_seven_zip_level` (spy on `run_jobs_batch`).
- `test_tui.py`: `test_settings_change_seven_zip_level` + validation-error test;
  updated `run_job`/`run_jobs_batch` mock signatures to accept `seven_zip_compression_level`.
- `test_readme.py`: README must mention `seven_zip_compression_level`.

## Docs
- `README.md`: Settings lists "7z compression level" (0 copy … 9 ultra, default 3)
  and notes it is independent of the Zip level; `--show-settings` example includes it.

## Atomicity / safety
No storage-format change; `seven_zip_compression_level` is a new optional key with
a safe default, so existing `settings.json` files load unchanged.
