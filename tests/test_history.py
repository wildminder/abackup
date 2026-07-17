"""Tests for the append-only run history store (RM-06)."""

from __future__ import annotations

from pathlib import Path

from abackup.core.history import (
    RunHistoryEntry,
    append_run,
    load_all_history,
    load_history,
)


def _entry(job_id="job1", status="success", started="2026-01-01T00:00:00+00:00"):
    return RunHistoryEntry(
        job_id=job_id,
        run_id=f"run-{job_id}-{started}",
        started_at=started,
        finished_at="2026-01-01T00:05:00+00:00",
        duration_seconds=300.0,
        files_total=10,
        files_done=10,
        bytes_total=1000,
        bytes_done=1000,
        archive_size=500,
        status=status,
        method="copy",
        error=None,
        summary={"x": 1},
    )


def test_append_then_load(tmp_path):
    p = append_run(tmp_path, _entry())
    assert Path(p).exists()
    entries = load_history(tmp_path, "job1")
    assert len(entries) == 1
    assert entries[0].status == "success"
    assert entries[0].duration_seconds == 300.0
    assert entries[0].summary == {"x": 1}


def test_append_preserves_order(tmp_path):
    append_run(tmp_path, _entry(started="2026-01-01T00:00:00+00:00"))
    append_run(tmp_path, _entry(started="2026-01-01T01:00:00+00:00"))
    entries = load_history(tmp_path, "job1")
    assert [e.started_at for e in entries] == [
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T01:00:00+00:00",
    ]


def test_load_missing_returns_empty(tmp_path):
    assert load_history(tmp_path, "nope") == []


def test_load_skips_malformed_line(tmp_path):
    hist_dir = tmp_path / "history"
    hist_dir.mkdir()
    path = hist_dir / "job1.jsonl"
    path.write_text(
        '{"job_id":"job1","status":"success"}\n'  # missing required fields
        '{"job_id":"job1","run_id":"r","started_at":"s","finished_at":"f",'
        '"duration_seconds":1,"files_total":1,"files_done":1,"bytes_total":1,'
        '"bytes_done":1,"archive_size":null,"status":"success","method":"copy"}\n'
        "not-json\n",
        encoding="utf-8",
    )
    entries = load_history(tmp_path, "job1")
    assert len(entries) == 1
    assert entries[0].status == "success"


def test_load_all_history_aggregates(tmp_path):
    append_run(tmp_path, _entry(job_id="a"))
    append_run(tmp_path, _entry(job_id="b"))
    all_hist = load_all_history(tmp_path)
    assert set(all_hist.keys()) == {"a", "b"}
    assert len(all_hist["a"]) == 1
    assert len(all_hist["b"]) == 1


def test_load_all_history_empty(tmp_path):
    assert load_all_history(tmp_path) == {}


def test_run_id_deterministic():
    from abackup.core.history import _make_run_id

    rid = _make_run_id("job1", "2026-01-01T00:00:00+00:00")
    assert _make_run_id("job1", "2026-01-01T00:00:00+00:00") == rid
    assert _make_run_id("job1", "2026-01-01T00:00:01+00:00") != rid
