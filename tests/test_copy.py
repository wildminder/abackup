import threading
from pathlib import Path

from abackup.core.copy import copy_tree
from abackup.utils.errors import DestinationError, JobCancelled, SourceNotFound


def test_copy_tree_preserves_structure(sample_tree, dest_dir):
    summary = copy_tree(sample_tree, dest_dir / "out")
    assert summary["files_total"] == 2
    assert summary["files_copied"] == 2
    assert (dest_dir / "out" / "a" / "f1.txt").read_text() == "hello"
    assert (dest_dir / "out" / "b.txt").read_text() == "world"


def test_copy_tree_skips_existing_when_no_overwrite(sample_tree, dest_dir):
    copy_tree(sample_tree, dest_dir / "out")
    summary = copy_tree(sample_tree, dest_dir / "out", overwrite=False)
    assert summary["files_skipped"] == 2
    assert summary["files_copied"] == 0


def test_copy_tree_overwrites_changed(sample_tree, dest_dir):
    copy_tree(sample_tree, dest_dir / "out")
    (sample_tree / "b.txt").write_text("changed", encoding="utf-8")
    summary = copy_tree(sample_tree, dest_dir / "out", overwrite=True)
    assert summary["files_copied"] == 1
    assert (dest_dir / "out" / "b.txt").read_text() == "changed"


def test_copy_tree_skips_excluded(sample_tree, dest_dir):
    # Add a file that matches the exclude pattern.
    (sample_tree / "b.txt.tmp").write_text("junk", encoding="utf-8")
    summary = copy_tree(sample_tree, dest_dir / "out", exclude_patterns=["*.tmp"])
    assert summary["files_excluded"] == 1
    assert not (dest_dir / "out" / "b.txt.tmp").exists()
    assert (dest_dir / "out" / "b.txt").exists()


def test_copy_tree_plan_only_no_files_written(sample_tree, dest_dir):
    summary = copy_tree(sample_tree, dest_dir / "out", plan_only=True)
    assert summary["planned"] is True
    assert summary["files_copied"] == 0
    assert not (dest_dir / "out").exists()


def test_copy_tree_progress_callback(sample_tree, dest_dir):
    seen = []
    copy_tree(sample_tree, dest_dir / "out", on_progress=lambda p: seen.append(p))
    # Last snapshot reports full completion.
    assert seen[-1].files_done == 2
    assert seen[-1].files_total == 2
    assert seen[-1].bytes_done == seen[-1].bytes_total
    assert seen[-1].percent() == 100
    # Bytes progress is monotonic.
    bytes_seen = [p.bytes_done for p in seen]
    assert bytes_seen == sorted(bytes_seen)
    assert bytes_seen[-1] > 0


def test_copy_tree_missing_source_raises(dest_dir):
    try:
        copy_tree(dest_dir / "nope", dest_dir / "out")
    except SourceNotFound:
        return
    raise AssertionError("expected SourceNotFound")


def test_copy_tree_bad_destination_raises(sample_tree, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    try:
        copy_tree(sample_tree, blocker / "sub")
    except DestinationError:
        return
    raise AssertionError("expected DestinationError")


def test_copy_tree_cancel_before_start(sample_tree, dest_dir):
    cancel = threading.Event()
    cancel.set()
    try:
        copy_tree(sample_tree, dest_dir / "out", cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
    # Nothing should have been written.
    assert not (dest_dir / "out").exists()


def test_copy_tree_cancel_mid_copy(sample_tree, dest_dir):
    cancel = threading.Event()
    seen = []

    def on_progress(p):
        seen.append(p)
        # Cancel as soon as the first file starts copying.
        if p.current_file:
            cancel.set()

    try:
        copy_tree(sample_tree, dest_dir / "out", on_progress=on_progress, cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
    # At least one file was copied before cancellation.
    assert (dest_dir / "out").exists()


def test_copy_tree_cancel_during_large_file(tmp_path, monkeypatch):
    # A single large file: cancellation must be honoured mid-copy (between chunks),
    # not only between files. We deterministically flip the cancel flag after the
    # first 1 MiB chunk is read (OS caching would otherwise make a timer racy).
    import builtins

    import abackup.core.copy as copy_mod

    src = tmp_path / "big"
    src.mkdir()
    big = src / "big.bin"
    big.write_bytes(b"x" * (64 * 1024 * 1024))  # 64 MiB
    dst = tmp_path / "dst"

    cancel = threading.Event()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        f = real_open(path, *args, **kwargs)
        if str(path) == str(big):
            orig_read = f.read

            def read(n=-1):
                data = orig_read(n)
                cancel.set()
                return data

            f.read = read
        return f

    monkeypatch.setattr(copy_mod, "open", fake_open, raising=False)
    try:
        copy_tree(src, dst, cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")


def test_copy_tree_realtime_byte_progress(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.bin").write_bytes(b"x" * (3 * 1024 * 1024))
    (src / "b.bin").write_bytes(b"y" * (2 * 1024 * 1024))
    seen = []
    copy_tree(src, tmp_path / "out", on_progress=lambda p: seen.append(p))
    # Multiple chunk-level emits happened (each file is > 1 MiB).
    assert len(seen) > 2
    # Bytes progress is monotonic and ends at the total.
    bytes_seq = [p.bytes_done for p in seen]
    assert bytes_seq == sorted(bytes_seq)
    assert seen[-1].bytes_done == seen[-1].bytes_total
    assert seen[-1].files_done == 2
    assert seen[-1].phase == "copying"


def test_copy_tree_cancel_stops_progress(tmp_path, monkeypatch):
    import builtins

    import abackup.core.copy as copy_mod

    src = tmp_path / "src"
    src.mkdir()
    big = src / "big.bin"
    big.write_bytes(b"x" * (64 * 1024 * 1024))  # 64 MiB
    cancel = threading.Event()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        f = real_open(path, *args, **kwargs)
        if str(path) == str(big):
            orig_read = f.read

            def read(n=-1):
                data = orig_read(n)
                cancel.set()
                return data

            f.read = read
        return f

    monkeypatch.setattr(copy_mod, "open", fake_open, raising=False)
    seen = []
    try:
        copy_tree(src, tmp_path / "out", on_progress=lambda p: seen.append(p), cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
    assert seen
    # Cancellation mid-chunk means we never reached the full byte total.
    assert seen[-1].bytes_done < seen[-1].bytes_total


def test_copy_tree_no_failed_when_clean(sample_tree, dest_dir):
    summary = copy_tree(sample_tree, dest_dir / "out")
    assert summary["files_failed"] == 0
    assert summary["failed_files"] == []


def test_copy_tree_collects_failed_files_and_continues(tmp_path, monkeypatch):
    import abackup.core.copy as copy_mod
    from abackup.utils.errors import DestinationError

    src = tmp_path / "src"
    src.mkdir()
    (src / "a").mkdir()
    (src / "a" / "ok.txt").write_text("ok")
    (src / "bad.txt").write_text("bad")
    dst = tmp_path / "dst"

    real_copy = copy_mod._atomic_copy_file

    def fake_copy(src_file, target, **kwargs):
        if Path(src_file).name == "bad.txt":
            raise DestinationError("simulated lock")
        return real_copy(src_file, target, **kwargs)

    monkeypatch.setattr(copy_mod, "_atomic_copy_file", fake_copy)
    summary = copy_mod.copy_tree(src, dst)
    # The good file copied; the bad one is recorded, not fatal.
    assert summary["files_copied"] == 1
    assert summary["files_failed"] == 1
    assert (dst / "a" / "ok.txt").read_text() == "ok"
    assert summary["failed_files"][0]["file"] == "bad.txt"
    assert "simulated lock" in summary["failed_files"][0]["error"]


def test_copy_tree_failed_files_shape(tmp_path, monkeypatch):
    import abackup.core.copy as copy_mod
    from abackup.utils.errors import DestinationError

    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.txt").write_text("bad")
    dst = tmp_path / "dst"

    def fake_copy(src_file, target, **kwargs):
        raise DestinationError("boom")

    monkeypatch.setattr(copy_mod, "_atomic_copy_file", fake_copy)
    summary = copy_mod.copy_tree(src, dst)
    assert summary["files_failed"] == 1
    entry = summary["failed_files"][0]
    assert set(entry.keys()) == {"file", "error"}
    assert entry["file"] == "bad.txt"
    assert entry["error"] == "boom"


def test_copy_tree_oserror_collected(tmp_path, monkeypatch):
    import abackup.core.copy as copy_mod

    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.txt").write_text("bad")
    dst = tmp_path / "dst"

    def fake_copy(src_file, target, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(copy_mod, "_atomic_copy_file", fake_copy)
    summary = copy_mod.copy_tree(src, dst)
    assert summary["files_failed"] == 1
    assert "disk full" in summary["failed_files"][0]["error"]


def test_copy_tree_job_cancelled_not_swallowed(tmp_path, monkeypatch):
    import threading

    import abackup.core.copy as copy_mod
    from abackup.utils.errors import JobCancelled

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a")
    (src / "b.txt").write_text("b")
    dst = tmp_path / "dst"
    cancel = threading.Event()

    real_copy = copy_mod._atomic_copy_file

    def fake_copy(src_file, target, **kwargs):
        if Path(src_file).name == "a.txt":
            # First file copies fine, then we cancel before the next.
            cancel.set()
            return real_copy(src_file, target, **kwargs)
        raise AssertionError("should not reach second file")

    monkeypatch.setattr(copy_mod, "_atomic_copy_file", fake_copy)
    try:
        copy_mod.copy_tree(src, dst, cancel=cancel)
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")


def test_copy_tree_skips_on_size_only(sample_tree, dest_dir):
    copy_tree(sample_tree, dest_dir / "out")
    # Change only mtime on the source files (FAT32 truncates mtime to 2s).
    for p in sample_tree.rglob("*"):
        if p.is_file():
            p.touch()
    summary = copy_tree(sample_tree, dest_dir / "out", overwrite=True)
    # Size-only equality means the mtime change does NOT trigger a recopy.
    assert summary["files_skipped"] == 2
    assert summary["files_copied"] == 0


def test_copy_tree_recopies_on_size_change(sample_tree, dest_dir):
    copy_tree(sample_tree, dest_dir / "out")
    (sample_tree / "b.txt").write_text("changed content")
    summary = copy_tree(sample_tree, dest_dir / "out", overwrite=True)
    assert summary["files_copied"] == 1
    assert (dest_dir / "out" / "b.txt").read_text() == "changed content"


def test_copy_tree_use_hash_detects_content_change(sample_tree, dest_dir):
    copy_tree(sample_tree, dest_dir / "out")
    # Same size, different content.
    (sample_tree / "b.txt").write_text("WORLD")  # "world" -> "WORLD", same length
    # Without hash: size-only equality skips it.
    skip_summary = copy_tree(sample_tree, dest_dir / "out", overwrite=True, use_hash=False)
    assert skip_summary["files_skipped"] == 2
    # With hash: content differs -> recopied.
    hash_summary = copy_tree(sample_tree, dest_dir / "out", overwrite=True, use_hash=True)
    assert hash_summary["files_copied"] == 1
    assert (dest_dir / "out" / "b.txt").read_text() == "WORLD"


def test_copy_tree_use_hash_skips_identical(sample_tree, dest_dir):
    copy_tree(sample_tree, dest_dir / "out")
    # No changes: identical content -> skipped in both modes.
    skip_summary = copy_tree(sample_tree, dest_dir / "out", overwrite=True, use_hash=True)
    assert skip_summary["files_skipped"] == 2
    assert skip_summary["files_copied"] == 0


def test_files_equal_helper_unit(tmp_path):
    import abackup.core.copy as copy_mod

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello")
    b.write_text("hello")
    sa = a.stat()
    sb = b.stat()
    # Same size, no hash -> equal.
    assert copy_mod._files_equal(sa, sb, a, b, use_hash=False) is True
    # Different size -> not equal.
    b.write_text("hello world")
    sb2 = b.stat()
    assert copy_mod._files_equal(sa, sb2, a, b, use_hash=False) is False
    # Same size, different content, hash on -> not equal.
    c = tmp_path / "c.txt"
    c.write_text("HELLO")  # same length as "hello"
    sc = c.stat()
    assert copy_mod._files_equal(sa, sc, a, c, use_hash=True) is False
    # Same content, hash on -> equal.
    d = tmp_path / "d.txt"
    d.write_text("hello")
    sd = d.stat()
    assert copy_mod._files_equal(sa, sd, a, d, use_hash=True) is True
