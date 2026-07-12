import threading

from abackup.core.copy import copy_tree
from abackup.utils.errors import SourceNotFound, DestinationError, JobCancelled


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
        copy_tree(
            src, tmp_path / "out", on_progress=lambda p: seen.append(p), cancel=cancel
        )
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled")
    assert seen
    # Cancellation mid-chunk means we never reached the full byte total.
    assert seen[-1].bytes_done < seen[-1].bytes_total
