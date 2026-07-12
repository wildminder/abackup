from abackup.core.discovery import is_first_run, mark_first_run_done
from abackup.models import Settings


def test_is_first_run_true_by_default():
    assert is_first_run(Settings()) is True


def test_is_first_run_false_after_mark():
    marked = mark_first_run_done(Settings())
    assert is_first_run(marked) is False


def test_mark_is_pure():
    s = Settings(default_destination="D:/x")
    marked = mark_first_run_done(s)
    assert s.first_run_completed is False
    assert marked.first_run_completed is True
    assert marked.default_destination == "D:/x"
