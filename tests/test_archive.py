import threading
from datetime import date
from pathlib import Path
from zipfile import ZipFile

from abackup.core.archive import make_zip
from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled


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


def test_make_zip_level_store_larger_than_max(sample_tree, dest_dir):
    # Highly compressible content isolates the effect of the level.
    (sample_tree / "big.txt").write_text("A" * 100_000, encoding="utf-8")
    store = make_zip(
        sample_tree, dest_dir / "store", when=date(2026, 7, 12), compress_level=0
    )
    maxed = make_zip(
        sample_tree, dest_dir / "max", when=date(2026, 7, 12), compress_level=9
    )
    assert store.stat().st_size > maxed.stat().st_size


def test_make_zip_level_is_deterministic(sample_tree, dest_dir):
    a = make_zip(
        sample_tree, dest_dir / "a", when=date(2026, 7, 12), compress_level=9
    )
    b = make_zip(
        sample_tree, dest_dir / "b", when=date(2026, 7, 12), compress_level=9
    )
    assert a.read_bytes() == b.read_bytes()


def test_make_zip_cancel_before_start(sample_tree, dest_dir):
    cancel = threading.Event()
    cancel.set()
    try:
        make_zip(sample_tree, dest_dir, when=date(2026, 7, 12), cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
    # No archive should have been created.
    assert not list(dest_dir.glob("*.zip"))


def test_make_zip_cancel_mid_archive(sample_tree, dest_dir, monkeypatch):
    # Many files so the cancellation check is hit between entries. We flip the
    # cancel flag after the first file is read (a timer would be racy because the
    # just-written files are OS-cached and zip finishes instantly).
    import builtins

    import abackup.core.archive as archive_mod

    for i in range(20):
        (sample_tree / f"f{i:02d}.txt").write_text(f"content-{i}", encoding="utf-8")
    cancel = threading.Event()
    real_open = builtins.open
    first = {}

    def fake_open(path, *args, **kwargs):
        f = real_open(path, *args, **kwargs)
        if not first.get("done") and str(path).endswith(".txt"):
            orig_read = f.read

            def read(n=-1):
                data = orig_read(n)
                cancel.set()
                first["done"] = True
                return data

            f.read = read
        return f

    monkeypatch.setattr(archive_mod, "open", fake_open, raising=False)
    try:
        make_zip(sample_tree, dest_dir, when=date(2026, 7, 12), cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
