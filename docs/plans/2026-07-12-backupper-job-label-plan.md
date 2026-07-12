# Plan: improved job display label in the main menu

## Problem
The main-menu job list rendered each job as
`name [method] -> destination`, omitting the **source** path. The user
asked for `name [method]: source -> destination` and, when a path is
too long, a middle-elided form that keeps the **drive, first folder and
last component** (e.g. `C:\Users\…\abackup`).

## Decision
- Add a pure, testable helper `shorten_display_path(path, max_len=50)`
  in `src/abackup/core/paths.py` that elides the middle of a path
  while preserving the drive (or root), the first folder, and the last
  component. It keeps the original separator style (`\` vs `/`), and
  handles Windows drive paths, POSIX absolute paths, relative paths,
  and UNC (`//server/share/...`) paths. If the result is still too
  long it drops the first folder, then truncates the last component.
- Add `format_job_label(name, method, source, destination, max_len=50)`
  that returns `f"{name} [{method}]: {src} -> {dst}"` with both paths
  run through `shorten_display_path`.
- `src/abackup/tui/screens/main_menu.py` now builds each `ListItem`
  via `format_job_label(j.name, j.method.value, j.source, j.destination)`.

## Steps
1. `paths.py`: add `shorten_display_path` + `format_job_label`
   (string-based, separator-preserving; no new dependencies).
2. `main_menu.py`: import `format_job_label`; use it for the list label.
3. `tests/test_paths.py`: unit tests for short/unchanged, Windows drive
   (slash + backslash), POSIX absolute, relative, UNC, tail-truncation,
   and `format_job_label` (basic + long-path elision).
4. `tests/test_tui.py`: a pilot test that saves a job with long
   source/destination and asserts the rendered `ListView` label
   contains `name [method]:` and `->` and that the long paths are
   elided (not shown in full).

## Atomicity / safety
Display-only change; no storage-format or backup-logic impact. The
elision is cosmetic and deterministic (same input -> same output).

## Tests
- `test_shorten_display_path_*` (7 cases) + `test_format_job_label_*`
  (2 cases) in `tests/test_paths.py`.
- `test_main_menu_job_label_includes_source_and_destination` in
  `tests/test_tui.py`.
- Full suite + coverage gate (`--cov-fail-under=90`) must pass.
