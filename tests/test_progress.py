from dataclasses import FrozenInstanceError

from abackup.core.progress import (
    PHASE_DONE,
    STATUS_SUCCESS,
    Progress,
)


def test_fraction_zero_at_start():
    p = Progress(job_id="j", bytes_total=100, bytes_done=0)
    assert p.fraction() == 0.0
    assert p.percent() == 0


def test_fraction_full_at_end():
    p = Progress(job_id="j", bytes_total=100, bytes_done=100)
    assert p.fraction() == 1.0
    assert p.percent() == 100


def test_fraction_clamps_at_one():
    p = Progress(job_id="j", bytes_total=100, bytes_done=250)
    assert p.fraction() == 1.0


def test_fraction_file_ratio_fallback_when_no_bytes():
    p = Progress(job_id="j", files_total=4, files_done=2, bytes_total=0)
    assert p.fraction() == 0.5
    assert p.percent() == 50


def test_fraction_one_when_no_totals():
    p = Progress(job_id="j")
    assert p.fraction() == 1.0


def test_percent_rounding():
    assert Progress(bytes_total=3, bytes_done=1).percent() == 33
    assert Progress(bytes_total=3, bytes_done=3).percent() == 100
    assert Progress(bytes_total=1000, bytes_done=999).percent() == 99


def test_immutable():
    p = Progress(job_id="j", bytes_done=1)
    try:
        p.bytes_done = 5
    except FrozenInstanceError:
        return
    raise AssertionError("Progress should be frozen")


def test_terminal_success_status():
    p = Progress(
        job_id="j",
        bytes_total=10,
        bytes_done=10,
        phase=PHASE_DONE,
        status=STATUS_SUCCESS,
    )
    assert p.status == STATUS_SUCCESS
    assert p.phase == PHASE_DONE
    assert p.percent() == 100
