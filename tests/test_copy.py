from abackup.core.copy import copy_tree
from abackup.utils.errors import SourceNotFound, DestinationError


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
    copy_tree(sample_tree, dest_dir / "out", on_progress=lambda d, t, p: seen.append((d, t, p)))
    assert seen[-1][0] == 2 and seen[-1][1] == 2


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
