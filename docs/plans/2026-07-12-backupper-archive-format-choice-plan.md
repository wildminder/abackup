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

---

# Addendum 2: 7z speed — prefer the multithreaded system binary

## Problem
A real-world folder that the installed **7-Zip binary** compressed in ~30s at
~80% CPU took our app **~5 min at ~4% CPU**. Root cause: the app
defaulted to the **py7zr** library, which
1. compressed **single-threaded** (LZMA2 filter had no `threads`), and
2. is **non-solid** (one stream per file), so it can't parallelise across
   files and pays a Python `write`/stat/`relative_to`/progress cost per file.
The system 7-Zip binary uses **multithreaded, solid** LZMA2 → all cores.

## Decision
- **Flip the default** `Settings.prefer_py7zr` from `True` → `False`.
  `make_archive` now prefers the system 7-Zip binary when found
  (`find_7z()` on PATH or common install dirs), falling back to py7zr
  only when no binary is available. This is the ~5–10× speedup.
- **py7zr stays single-threaded.** Its internal compressor routes through
  CPython's `lzma.LZMACompressor`, which **rejects the LZMA2
  `"threads"` key** (`ValueError: Invalid filter specifier for LZMA
  filter`). So the only multithreaded 7z path is the system binary;
  py7zr remains a portable-but-slow fallback.

### `models.py`
- `prefer_py7zr: bool = False` (was `True`). `from_dict` legacy
  `prefer_7z` → `prefer_py7zr` mapping unchanged.

### `compression.make_7z_py7zr` (core/compression.py)
- Filter unchanged: `{"id": py7zr.FILTER_LZMA2, "preset": compress_level}`
  (no `threads` — it would raise). Single-threaded, non-solid.

### `compression.make_archive` (core/compression.py)
- Precedence unchanged in code, but with the new default the **binary branch
  (`find_7z() is not None`) is taken first** for 7z jobs.

### Settings screen (tui/screens/settings.py)
- Hint flipped: binary is used by default (faster); enabling the checkbox
  forces py7zr (portable fallback, single-threaded).

## Tests
- `test_models.py`: `test_prefer_py7zr_default_false`.
- `test_compression.py`: `test_make_archive_prefers_system_binary_by_default`
  (monkeypatch `find_7z` → binary, call without `prefer_py7zr`, assert
  `-t7z`/`-mx3` cmd); `test_make_archive_uses_py7zr_when_forced`
  (explicit `prefer_py7zr=True`); `test_make_7z_py7zr_uses_preset_and_stays_single_threaded`
  (capture filters, assert `preset` set and `threads` absent).

## Docs
- `README.md`: "Prefer py7zr" now documented as **disabled by default**
  (binary preferred, multithreaded, 5–10× faster); enabling forces the
  single-threaded py7zr fallback.

## Atomicity / safety
Only a default-value change in `Settings`. Existing `settings.json` files
load unchanged (`prefer_py7zr` already a known key).

---

# Addendum 3: `find_7z()` missed the registry-registered 7-Zip → still slow + Cancel dead

## Problem
After Addendum 2 flipped the default to prefer the system binary, the app
was **still slow (~5 min)** and **Cancel did nothing**. Root cause:
`find_7z()` only checked `PATH` + a few hardcoded paths
(`C:\Program Files\7-Zip\7z.exe`, …), so it returned `None` on
machines where 7-Zip is installed in a **custom/portable location**.
The user's install lives at `C:\WinApp\Utils\7-Zip\` — registered in
the Windows registry under `SOFTWARE\7-Zip` → `Path` — which none
of our checks covered. With `find_7z() is None`, `make_archive`
silently fell back to the slow, single-threaded **py7zr** library,
which also can't be cancelled mid-file (its `zf.write()` blocks per
file; cancel is only checked *between* files). So the Cancel button had
no effect and the Python process kept archiving.

## Decision
Make `find_7z()` **registry-aware** (Windows) plus an env-var override,
so it discovers the real install automatically:
1. `SEVEN_ZIP_PATH` / `7ZIP_PATH` env var (explicit override, first).
2. `PATH` (`7z` / `7za` / `7zr`).
3. **Windows registry** `SOFTWARE\7-Zip` → `Path` in `HKLM`, `HKCU`,
   and `WOW6432Node` (covers custom/portable installs). Within an
   install dir, prefer `7z.exe` > `7za.exe` > `7zr.exe` > `7zG.exe`
   (the GUI-less build is only a last resort to avoid popping a window).
4. The original hardcoded common paths (last resort).

This routes 7z jobs to the **multithreaded system binary** (~30 s instead
of ~5 min) and makes Cancel work, because `make_7z` already
terminates the subprocess via `proc.terminate()` when the cancel
`threading.Event` is set.

### `compression.py`
- New `import winreg` (guarded; `None` on non-Windows).
- New `_7Z_BINARIES` tuple (preference order above).
- New `_seven_zip_registry_paths()` helper: reads the `Path` value from
  the three registry roots, de-duplicates, returns `[]` when `winreg`
  is unavailable.
- `find_7z()` rewritten with the 4-step discovery order above.

### Bug fixed as a side effect
`make_7z` used `tempfile.mkstemp(..., suffix=".tmp")` which
**pre-creates an empty temp file**. 7z's `a` (add) mode then tried to
*append to* that invalid existing file and failed (non-zero exit →
`DestinationError` → job `failed`). This bug was previously **masked**
because `find_7z()` always returned `None` (py7zr path). Fix: remove
the empty placeholder (`os.remove(tmp)`, ignore `FileNotFoundError`)
right after `mkstemp` so 7z creates the archive fresh. (7z uses the
output name as-given when it already has an extension, so
`tmpXXXX.tmp` → `tmpXXXX.tmp` matches our later
`os.replace(tmp, final)`.)

## Tests
- `test_compression.py`:
  - `test_find_7z_uses_registry_when_present` (monkeypatch
    `_seven_zip_registry_paths` → temp dir with a fake `7z.exe`).
  - `test_find_7z_prefers_registry_binary_over_gui_less` (`7z.exe`
    wins over `7zG.exe` in the same dir).
  - `test_find_7z_env_override` (`SEVEN_ZIP_PATH` wins).
  - `test_seven_zip_registry_paths_reads_winreg` (fake `winreg` reading
    `Path` from all three roots, de-duplicated).
  - `test_seven_zip_registry_paths_returns_empty_off_windows`
    (`winreg is None` → `[]`).
  - The three pre-existing `find_7z` tests now also stub
    `_seven_zip_registry_paths` to `[]` so the real machine registry
    doesn't leak into them.
- `test_backup.py::test_run_job_seven_zip` now exercises the **real**
  7-Zip binary end-to-end (previously masked) and asserts `success`.

## Docs
- `README.md`: note that 7z auto-detects the system binary via the
  Windows registry (and `SEVEN_ZIP_PATH` override); the binary is
  multithreaded and ~5–10× faster than py7zr.

## Atomicity / safety
No storage-format change. `winreg` import is guarded so the code still
imports on non-Windows; `_seven_zip_registry_paths` returns `[]` there.

---

# Addendum 4: realtime progress from the external 7-Zip process

## Problem
`make_7z` previously discarded all of 7z's output
(`stdout=stderr=DEVNULL`) and only emitted a start + completion
`Progress` snapshot, so the TUI bar jumped `0%` -> `100%` with no
intermediate movement during a (potentially long) 7z run. The user
asked whether progress can be read from the external 7z process.

## First attempt (rejected): parse `-bsp2` stderr
7-Zip can emit a live compression percentage via its `-bsp2` switch
(progress percentage -> stderr, each update separated by a carriage
return `\r`, no newline). We implemented a reader thread that drained
stderr and regex-extracted the latest `NN%`. **This does not work in
practice**: when stderr is a *pipe* (non-TTY), 7-Zip fully *buffers*
that stream and only flushes it at process exit. Empirically verified
with a 150 MB incompressible run: the entire `0%..100%` stream
arrived in a single chunk at EOF (5.18 s), so the bar still sat at
`0%` until the process finished. A pseudo-TTY (conpty) would force
unbuffered output but adds heavy platform-specific code/dependencies.

## Decision: poll the growing temp archive file
Instead of parsing 7z's output, `make_7z` derives realtime progress
from the **temp archive file's size**, which grows monotonically as 7z
compresses:
- the command no longer needs `-bsp2`; both stdout and stderr go to
  `DEVNULL` (the file listing / progress text is irrelevant now);
- in the poll loop it reads `os.path.getsize(tmp)` and derives a
  percentage against an **adaptive estimate** of the final compressed
  size: `est = max(bytes_total // 2, cur)` (seeded at 50% of the
  source bytes, grown if the archive exceeds it). `pct = min(99,
  cur/est*100)`. This works on every platform with no extra
  dependencies and gives a smoothly moving bar;
- `bytes_done = bytes_total * pct / 100` (and an estimated
  `files_done`) are forwarded via `Progress(PHASE_ZIPPING)` whenever
  the percentage changes; on completion the final `PHASE_DONE`
  snapshot forces `bytes_done == bytes_total` (100%);
- cancellation is unchanged: the poll loop still `proc.terminate()`s
  the subprocess when the cancel `Event` is set.

### `compression.py`
- `make_7z`: command is `[exe, "a", "-y", "-t7z", "-mxN", tmp, "."]`
  (no `-bsp2`); `stdout=stderr=DEVNULL`; poll loop reads
  `os.path.getsize(tmp)`, computes `pct` from the adaptive estimate,
  and emits intermediate `Progress` when it changes.

## Tests
- `test_make_7z_emits_realtime_progress`: fake `Popen` whose
  `poll()` *grows the temp archive file* (`cmd[5]`) across calls;
  asserts the start snapshot, multiple distinct intermediate
  `Progress` values with `0 < bytes_done < bytes_total` (the bar
  moved), and a final `PHASE_DONE` with `bytes_done == bytes_total`.
- The three `find_7z` tests and `test_make_archive_*` already cover
  the binary path; `test_run_job_seven_zip` exercises the real 7z
  end-to-end.

## Docs
- `README.md` / plan: note 7z jobs now show live progress derived
  from the growing archive file (not the buffered `-bsp2` stream).

## Atomicity / safety
No storage-format change. The percentage is a UI hint only —
`bytes_done` is derived from the archive size, not authoritative, so a
slightly off bar during 7z runs is cosmetic, not a correctness
issue. The temp file is still `os.replace`d into the final name only
on success, so a cancelled/failed run leaves no partial archive.
