# ABackup — Run-All-Jobs & Multithreaded Batch Queue

**Plan date:** 2026-07-12
**Status:** Draft for review
**Builds on:** [`2026-07-12-abackup-cli-plan.md`](2026-07-12-abackup-cli-plan.md)
**Mode:** Architect (plan only — no implementation in this document)

---

## 1. Goals

Extend the existing ABackup CLI/TUI with two capabilities:

1. **Run all jobs** — a single action (TUI button + CLI flag) that executes every configured backup job.
2. **Multithreaded batch with a queue** — when there are many jobs, they are processed concurrently by a bounded pool of worker threads fed from a `queue.Queue`, so memory is bounded and throughput scales with `max_workers`.

Constraints carried over from the base plan: **deterministic** (injectable clock/executor, results returned in input order), **atomic** (per-file atomic copy/zip already exists; batch must not corrupt `jobs.json` under concurrency), and **every step covered by tests**.

---

## 2. Architecture Decisions (with rationale)

| Decision | Choice | Rationale | Fallback |
|---|---|---|---|
| Concurrency primitive | `threading` + `queue.Queue` + `ThreadPoolExecutor`-style worker pool | Backups are I/O bound; threads are simple and avoid async rewrites. Queue gives explicit backpressure for "a lot of jobs". | `asyncio` task pool (bigger refactor) |
| Worker count | `Settings.max_workers` (default 4), overridable via `--workers` | Tunable per machine; safe default | fixed constant |
| Result ordering | Results returned in **input order** (keyed by job id) | Deterministic output regardless of completion order | completion order |
| Per-job persistence | Each worker persists its own `updated_job` under a `threading.Lock` | Isolates failures; no lost status if batch aborts | persist once at end (loses mid-batch status) |
| Failure isolation | One job error never stops others | Robust batch | abort whole batch on first error |
| TUI batch screen | New `RunAllScreen` reusing progress + result widgets | Consistent UX | inline in main menu |

**Why a queue and not just `executor.map`:** the requirement explicitly says "queue (if a lot of jobs)". A `queue.Queue` with N consumer threads bounds in-flight work and makes backpressure explicit and testable, while `executor.map` eagerly submits all tasks.

---

## 3. Data Model Change

Add to `Settings` (`src/abackup/models.py`):

```python
max_workers: int = 4
```

`from_dict` already ignores unknown keys and keeps known ones, so existing `settings.json` files remain compatible (new field defaults to 4).

---

## 4. New Module: `src/abackup/core/runner.py`

```python
def run_jobs_batch(
    jobs: List[BackupJob],
    *,
    config_dir=None,
    data_dir=None,
    max_workers: int = 4,
    on_job_done: Optional[Callable[[str, BackupResult], None]] = None,
    clock=None,
) -> List[BackupResult]:
    ...
```

Behavior:
- Empty list -> `[]` (no-op, deterministic).
- Build `queue.Queue`, enqueue all jobs; record input `order = [j.id for j in jobs]`.
- Spawn `min(max_workers, len(jobs))` worker threads (at least 1).
- Each worker loops: `q.get_nowait()`; on `queue.Empty` -> exit; else `run_job(...)`, persist `updated_job` under `lock`, store `results[job.id]`, invoke `on_job_done(job.id, result)`, `q.task_done()`.
- `join()` all threads, return `[results[i] for i in order]`.

Determinism hooks: `clock` injected into `run_job`; `max_workers=1` yields fully sequential, order-stable execution; output order is always input order.

---

## 5. TUI Changes

- `MainMenuScreen` (`src/abackup/tui/screens/main_menu.py`): add a **Run all** button (id `run_all`). Handler pushes `RunAllScreen`.
- New `src/abackup/tui/screens/run_all.py` (`RunAllScreen`):
  - Shows `ProgressBar` (total = number of jobs) + a `Rich` log of per-job outcomes.
  - On mount, `run_worker` calls `run_jobs_batch(..., max_workers=settings.max_workers, on_job_done=cb)`.
  - `on_job_done` uses `self.app.call_from_thread` to bump progress and append a result line (thread-safe).
  - On completion, shows summary and a **Back** button returning to `MainMenuScreen`.

## 6. CLI Changes (`src/abackup/cli.py`)

- New flag `--run-all`: load all jobs, call `run_jobs_batch`, print a summary table, then `return` (do NOT launch TUI).
- New flag `--workers N` (int, default from `Settings.max_workers`): passed to `run_jobs_batch`.
- `--run-all` without jobs prints a friendly message and returns.

---

## 7. Workflow (Mermaid)

```mermaid
flowchart TD
    A[User triggers Run all] --> B{Context}
    B -- TUI --> C[RunAllScreen]
    B -- CLI --run-all --> D[cli runs batch]
    C --> E[run_jobs_batch]
    D --> E
    E --> F[Queue filled with jobs]
    F --> G{Worker pool N threads}
    G --> H[Dequeue job]
    H --> I[run_job copy or zip]
    I --> J[Persist updated_job under lock]
    J --> K[on_job_done callback]
    K --> L{More in queue?}
    L -- Yes --> H
    L -- No --> M[Join threads]
    M --> N[Return results in input order]
    N --> O[TUI summary / CLI table]
```

---

## 8. Detailed Atomic Steps (each with tests)

> **Determinism rules:** `clock` injected; `max_workers` injectable; results keyed by id and returned in input order; `jobs.json` writes serialized by a lock. Tests use `max_workers=1` for ordering and `max_workers>1` for concurrency correctness (order-independent assertions).

### Step 1 — Add `max_workers` to `Settings` (`models.py`)
- Extend dataclass; verify round-trip and that old `settings.json` (without field) still loads with default 4.
- **Tests:** `test_settings_max_workers_default`, `test_settings_from_dict_ignores_and_defaults` (old dict), round-trip keeps value.

### Step 2 — Implement `run_jobs_batch` (`core/runner.py`)
- Queue + worker-thread pool; per-job persist under lock; ordered results; empty-list short-circuit.
- **Tests:** `test_empty_returns_empty`; `test_sequential_order_max_workers_1` (results match input order); `test_concurrent_all_complete` (max_workers=3, all succeed, set of ids equals input); `test_failure_isolation` (one bad source -> that result `failed`, others `success`, batch still returns all); `test_on_job_done_called_per_job` (count == len); `test_per_job_status_persisted` (jobs.json reflects each `last_status`); `test_queue_backpressure` (e.g. 20 jobs, max_workers=2, all complete).

### Step 3 — Thread-safety of `jobs.json` writes
- Verify no corruption / lost updates when many workers write concurrently (lock).
- **Tests:** `test_concurrent_writes_no_corruption` (load jobs after batch, count == N, all valid JSON, no `.tmp` leftovers); `test_no_tmp_leftovers_after_batch`.

### Step 4 — TUI: add **Run all** button (`main_menu.py`)
- New button; handler pushes `RunAllScreen`.
- **Tests (pilot):** `test_main_menu_run_all_button` -> screen becomes `RunAllScreen`.

### Step 5 — TUI: `RunAllScreen` (`tui/screens/run_all.py`)
- Progress bar + result log; runs batch in worker; thread-safe updates; summary + Back.
- **Tests (pilot):** `test_run_all_screen_completes_all` (pre-create 3 jobs; after batch, all `last_status == success`; progress reaches 100%); `test_run_all_screen_shows_failure` (one bad job -> summary notes failure, others succeed).

### Step 6 — CLI: `--run-all` and `--workers` (`cli.py`)
- Non-interactive batch run + summary; returns without launching TUI.
- **Tests:** `test_cli_run_all_runs_every_job` (creates 2 jobs via config, `--run-all` -> both succeed, exit 0, prints summary); `test_cli_run_all_empty` (no jobs -> friendly message, exit 0); `test_cli_workers_flag` (passes `max_workers` through; verify via a spy/monkeypatch on `run_jobs_batch`).

### Step 7 — README + consistency (`README.md`, `test_readme.py`)
- Document **Run all** (TUI button + `--run-all`), `--workers`, and `max_workers` setting.
- **Tests:** README mentions `Run all`, `--run-all`, `--workers`; `Settings` default `max_workers` referenced.

### Step 8 — Coverage gate
- Re-run `pytest --cov=src/abackup --cov-fail-under=90`; keep >=90%. Add CI step already covers it.

---

## 9. Testing Strategy

- **Unit (runner):** pure logic with injected `max_workers`/`clock`; use `tmp_config`/`tmp_data` fixtures; assert ordering with `max_workers=1`, correctness with `>1`.
- **Failure isolation:** craft one job with a non-existent source; assert others succeed and the bad one is `failed`.
- **Thread-safety:** assert `jobs.json` integrity and no `.tmp` leftovers after a high-concurrency batch.
- **TUI (pilot):** drive **Run all** button and `RunAllScreen`; assert completion + persisted statuses.
- **CLI:** capture stdout; assert summary and exit codes.

---

## 10. Acceptance Criteria

1. Main menu has a **Run all** action that backs up every job.
2. `abackup --run-all` runs all jobs and prints a summary without opening the TUI.
3. Jobs run concurrently via a bounded worker pool fed by a queue; `max_workers` is configurable (setting + `--workers`).
4. A failing job does not prevent others from completing; each job's status is persisted.
5. Results are returned/displayed in input order (deterministic).
6. All 8 steps have passing tests; coverage stays >=90%.

---

## 11. Open Decisions (documented, not blocking)

- **Threading model = `queue.Queue` + worker threads** chosen for I/O-bound work and explicit backpressure; `asyncio` is the fallback if event-loop integration is later required.
- **Default `max_workers = 4`**; conservative and safe on most machines.
- **Per-job persistence under lock** chosen over end-of-batch persistence to survive mid-batch interruption.
