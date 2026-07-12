from datetime import date
from pathlib import Path
from zipfile import ZipFile

from abackup.core.archive import make_zip
from abackup.utils.errors import SourceNotFound, DestinationError


def test_make_zip_name_and_contents(sample_tree, dest_dir):
    out = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    assert out.name == "source_2026-07-12.zip"
    with ZipFile(out) as zf:
        names = sorted(zf.namelist())
    assert "a/f1.txt" in names
    assert "b.txt" in names


def test_make_zip_deterministic(sample_tree, dest_dir):
    a = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    b = make_zip(sample_tree, dest_dir / "x", when=date(2026, 7, 12))
    assert a.read_bytes() == b.read_bytes()


def test_make_zip_source_unchanged(sample_tree, dest_dir):
    make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    assert (sample_tree / "b.txt").read_text() == "world"


def test_make_zip_missing_source_raises(dest_dir):
    try:
        make_zip(dest_dir / "nope", dest_dir)
    except SourceNotFound:
        return
    raise AssertionError("expected SourceNotFound")


def test_make_zip_bad_destination_raises(sample_tree, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    try:
        make_zip(sample_tree, blocker / "sub")
    except DestinationError:
        return
    raise AssertionError("expected DestinationError")
