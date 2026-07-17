import threading
from datetime import date
from zipfile import ZipFile

from abackup.core.archive import make_zip
from abackup.utils.errors import DestinationError, JobCancelled, SourceNotFound


def test_make_zip_name_and_contents(sample_tree, dest_dir):
    out = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    assert out.name == "source_2026-07-12.zip"
    with ZipFile(out) as zf:
        names = sorted(zf.namelist())
    assert "a/f1.txt" in names
    assert "b.txt" in names


def test_make_zip_no_overwrite_same_day(sample_tree, dest_dir):
    # A second run the same day must not clobber the first archive (NTH-006).
    first = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    second = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    assert first.name == "source_2026-07-12.zip"
    assert second.name == "source_2026-07-12_1.zip"
    assert first.exists() and second.exists()
    # Both archives are valid and independent.
    assert ZipFile(first).namelist()
    assert ZipFile(second).namelist()


def test_make_zip_skips_excluded(sample_tree, dest_dir):
    (sample_tree / "b.txt.tmp").write_text("junk", encoding="utf-8")
    out = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12), exclude_patterns=["*.tmp"])
    with ZipFile(out) as zf:
        names = zf.namelist()
    assert "b.txt.tmp" not in names
    assert "b.txt" in names


def test_make_zip_plan_only_no_archive(sample_tree, dest_dir):
    out = make_zip(sample_tree, dest_dir, when=date(2026, 7, 12), plan_only=True)
    # plan_only returns the would-be name but writes nothing.
    assert out.name == "source_2026-07-12.zip"
    assert not out.exists()


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
    store = make_zip(sample_tree, dest_dir / "store", when=date(2026, 7, 12), compress_level=0)
    maxed = make_zip(sample_tree, dest_dir / "max", when=date(2026, 7, 12), compress_level=9)
    assert store.stat().st_size > maxed.stat().st_size


def test_make_zip_level_is_deterministic(sample_tree, dest_dir):
    a = make_zip(sample_tree, dest_dir / "a", when=date(2026, 7, 12), compress_level=9)
    b = make_zip(sample_tree, dest_dir / "b", when=date(2026, 7, 12), compress_level=9)
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


def test_make_zip_realtime_byte_progress(sample_tree, dest_dir):
    (sample_tree / "big.txt").write_text("A" * (3 * 1024 * 1024), encoding="utf-8")
    seen = []
    make_zip(
        sample_tree,
        dest_dir,
        when=date(2026, 7, 12),
        on_progress=lambda p: seen.append(p),
    )
    assert len(seen) > 1
    bytes_seq = [p.bytes_done for p in seen]
    assert bytes_seq == sorted(bytes_seq)
    assert seen[-1].bytes_done == seen[-1].bytes_total
    assert seen[-1].phase == "zipping"


def test_make_zip_cancel_stops_progress(sample_tree, dest_dir, monkeypatch):
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
    seen = []
    try:
        make_zip(
            sample_tree,
            dest_dir,
            when=date(2026, 7, 12),
            cancel=cancel,
            on_progress=lambda p: seen.append(p),
        )
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
    assert seen
    assert seen[-1].bytes_done < seen[-1].bytes_total


def test_make_zip_streams_large_file(sample_tree, dest_dir, monkeypatch):
    """IMP-102: a large file is written to the zip in bounded CHUNK-sized
    increments (no unbounded in-RAM bytearray buffer during the read)."""
    import tempfile

    # One file of 5 MiB (5 * CHUNK).
    (sample_tree / "big.bin").write_bytes(b"X" * (5 * 1024 * 1024))

    peak_write = {"bytes": 0}

    real_spool_write = tempfile.SpooledTemporaryFile.write

    def spy_spool_write(self, data):
        if isinstance(data, (bytes, bytearray, memoryview)):
            peak_write["bytes"] = max(peak_write["bytes"], len(data))
        return real_spool_write(self, data)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "write", spy_spool_write)
    make_zip(sample_tree, dest_dir, when=date(2026, 7, 12))
    # Each incremental write to the spool must be bounded by CHUNK, proving the
    # source is streamed rather than buffered whole in memory.
    assert peak_write["bytes"] <= 1024 * 1024, f"peak spool write {peak_write['bytes']}"


def test_make_zip_byte_reproducible(sample_tree, dest_dir):
    """IMP-102: streaming rewrite must remain byte-for-byte reproducible."""
    (sample_tree / "big.txt").write_text("A" * 50_000, encoding="utf-8")
    a = make_zip(sample_tree, dest_dir / "a", when=date(2026, 7, 12), compress_level=6)
    b = make_zip(sample_tree, dest_dir / "b", when=date(2026, 7, 12), compress_level=6)
    assert a.read_bytes() == b.read_bytes()
    # And it still extracts to the original content.
    with ZipFile(a) as zf:
        assert zf.read("big.txt") == b"A" * 50_000
