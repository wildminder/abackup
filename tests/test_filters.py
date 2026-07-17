"""Tests for include/exclude glob filtering (RM-02)."""

from pathlib import Path

from abackup.core.filters import should_skip


def test_filter_no_patterns_keeps_all():
    assert should_skip(Path("a/b.txt"), [], []) is False
    assert should_skip(Path("node_modules/x.js"), [], []) is False


def test_filter_excludes_glob():
    assert should_skip(Path("a/tmp.log"), ["*.log"], []) is True
    assert should_skip(Path("a/b.txt"), ["*.log"], []) is False


def test_filter_excludes_directory():
    # A directory-style pattern excludes everything beneath it.
    assert should_skip(Path("node_modules/x/y.js"), ["node_modules"], []) is True
    assert should_skip(Path("__pycache__/mod.cpython-311.pyc"), ["__pycache__"], []) is True
    assert should_skip(Path("src/main.py"), ["__pycache__"], []) is False


def test_filter_include_only():
    # With a non-empty include list, only matching files are kept.
    assert should_skip(Path("a/keep.txt"), [], ["*.txt"]) is False
    assert should_skip(Path("a/skip.md"), [], ["*.txt"]) is True


def test_filter_include_and_exclude():
    # Exclude wins after include: include *.txt but exclude secret.txt.
    assert should_skip(Path("a/secret.txt"), ["secret.txt"], ["*.txt"]) is True
    assert should_skip(Path("a/notes.txt"), ["secret.txt"], ["*.txt"]) is False
