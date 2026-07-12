from datetime import date
from pathlib import Path

import pytest

from abackup.core import compression
from abackup.core.compression import (
    find_7z,
    make_archive,
    make_7z,
    make_7z_py7zr,
)
from abackup.utils.errors import JobCancelled


def test_find_7z_none_when_absent(monkeypatch):
    monkeypatch.setattr(compression.shutil, "which", lambda name: None)
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [])
    assert find_7z() is None


def test_find_7z_found_on_path(monkeypatch):
    monkeypatch.setattr(compression.shutil, "which", lambda name: "/usr/bin/7z")
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [])
    assert find_7z() == "/usr/bin/7z"


def test_find_7z_found_in_common_path(monkeypatch, tmp_path):
    exe = tmp_path / "7z.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(compression.shutil, "which", lambda name: None)
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [str(exe)])
    assert find_7z() == str(exe)


def test_have_py7zr_reflects_import(monkeypatch):
    monkeypatch.setattr(compression, "py7zr", None)
    assert compression._have_py7zr() is False
    monkeypatch.undo()
    assert compression._have_py7zr() is True


def test_make_archive_uses_py7zr_when_available(sample_tree, dest_dir):
    # py7zr is importable in the test env, so it is the primary engine.
    out = make_archive(sample_tree, dest_dir, when=date(2026, 7, 12), compress_level=6)
    assert out.suffix == ".7z"
    assert out.exists()
    # The archive must be a real, readable 7z produced by py7zr.
    import py7zr

    with py7zr.SevenZipFile(out, "r") as zf:
        names = {n for n in zf.getnames()}
    assert "a/f1.txt" in names
    assert "b.txt" in names


def test_make_archive_falls_back_to_system_7z_when_py7zr_missing(
    monkeypatch, sample_tree, dest_dir
):
    # Simulate py7zr being unavailable; the system binary becomes the fallback.
    monkeypatch.setattr(compression, "py7zr", None)
    monkeypatch.setattr(compression, "find_7z", lambda: "/fake/7z")

    captured = {}

    class FakeProc:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            # 7z writes the archive to the temp path (cmd[5]).
            Path(cmd[5]).write_bytes(b"7z-archive")
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(compression.subprocess, "Popen", FakeProc)
    out = make_archive(sample_tree, dest_dir, when=date(2026, 7, 12), compress_level=6)
    assert out.suffix == ".7z"
    assert out.exists()
    assert "-t7z" in captured["cmd"]
    assert "-mx6" in captured["cmd"]


def test_make_archive_falls_back_to_zip_when_no_7z(monkeypatch, sample_tree, dest_dir):
    # Neither py7zr nor a system binary -> deterministic stdlib zip.
    monkeypatch.setattr(compression, "py7zr", None)
    monkeypatch.setattr(compression, "find_7z", lambda: None)
    out = make_archive(sample_tree, dest_dir, when=date(2026, 7, 12))
    assert out.suffix == ".zip"
    assert out.exists()


def test_make_archive_forces_zip_when_prefer_7z_false(monkeypatch, sample_tree, dest_dir):
    monkeypatch.setattr(compression, "find_7z", lambda: "/fake/7z")
    out = make_archive(
        sample_tree, dest_dir, when=date(2026, 7, 12), prefer_7z=False
    )
    assert out.suffix == ".zip"


def test_make_7z_py7zr_produces_valid_archive(sample_tree, dest_dir):
    out = make_7z_py7zr(sample_tree, dest_dir, when=date(2026, 7, 12), compress_level=6)
    assert out.suffix == ".7z"
    assert out.exists()
    import py7zr

    with py7zr.SevenZipFile(out, "r") as zf:
        names = set(zf.getnames())
    assert "a/f1.txt" in names
    assert "b.txt" in names


def test_make_7z_py7zr_cancel_raises(sample_tree, dest_dir):
    cancel = __import__("threading").Event()
    cancel.set()
    with pytest.raises(JobCancelled):
        make_7z_py7zr(sample_tree, dest_dir, when=date(2026, 7, 12), cancel=cancel)
    # No archive should have been finalised.
    assert not list(dest_dir.glob("*.7z"))


def test_make_7z_cancel_raises(monkeypatch, sample_tree, dest_dir):
    monkeypatch.setattr(compression, "find_7z", lambda: "/fake/7z")
    cancel = __import__("threading").Event()
    cancel.set()

    class FakeProc:
        def __init__(self, cmd, **kw):
            pass

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(compression.subprocess, "Popen", FakeProc)
    with pytest.raises(JobCancelled):
        make_7z(sample_tree, dest_dir, when=date(2026, 7, 12), cancel=cancel)
    # No archive should have been finalised.
    assert not list(dest_dir.glob("*.7z"))
