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
    monkeypatch.setattr(compression, "_seven_zip_registry_paths", lambda: [])
    assert find_7z() is None


def test_find_7z_found_on_path(monkeypatch):
    monkeypatch.setattr(compression.shutil, "which", lambda name: "/usr/bin/7z")
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [])
    monkeypatch.setattr(compression, "_seven_zip_registry_paths", lambda: [])
    assert find_7z() == "/usr/bin/7z"


def test_find_7z_found_in_common_path(monkeypatch, tmp_path):
    exe = tmp_path / "7z.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(compression.shutil, "which", lambda name: None)
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [str(exe)])
    monkeypatch.setattr(compression, "_seven_zip_registry_paths", lambda: [])
    assert find_7z() == str(exe)


def test_find_7z_uses_registry_when_present(monkeypatch, tmp_path):
    # 7-Zip is often installed in a custom/portable location that is only
    # discoverable via the Windows registry (e.g. C:\WinApp\Utils\7-Zip).
    # find_7z must consult the registry and return that binary.
    exe = tmp_path / "7z.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(compression.shutil, "which", lambda name: None)
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [])
    monkeypatch.setattr(
        compression, "_seven_zip_registry_paths", lambda: [str(tmp_path)]
    )
    assert find_7z() == str(exe)


def test_find_7z_prefers_registry_binary_over_gui_less(monkeypatch, tmp_path):
    # Within a registry install dir, the full CLI binary (7z.exe) must win over
    # the GUI-less 7zG.exe when both exist.
    cli = tmp_path / "7z.exe"
    gui = tmp_path / "7zG.exe"
    cli.write_text("", encoding="utf-8")
    gui.write_text("", encoding="utf-8")
    monkeypatch.setattr(compression.shutil, "which", lambda name: None)
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [])
    monkeypatch.setattr(
        compression, "_seven_zip_registry_paths", lambda: [str(tmp_path)]
    )
    assert find_7z() == str(cli)


def test_find_7z_env_override(monkeypatch, tmp_path):
    # An explicit SEVEN_ZIP_PATH / 7ZIP_PATH env var takes top priority.
    exe = tmp_path / "7z.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("SEVEN_ZIP_PATH", str(tmp_path))
    monkeypatch.setattr(compression.shutil, "which", lambda name: None)
    monkeypatch.setattr(compression, "_COMMON_7Z_PATHS", [])
    monkeypatch.setattr(compression, "_seven_zip_registry_paths", lambda: [])
    assert find_7z() == str(exe)


def test_seven_zip_registry_paths_reads_winreg(monkeypatch):
    # The helper must read the "Path" value from HKLM/HKCU/WOW6432Node and
    # de-duplicate. We swap in a fake `winreg` so the test is hermetic.
    class _Key:
        def __init__(self, value):
            self._value = value

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _FakeWinreg:
        HKEY_LOCAL_MACHINE = "HKLM"
        HKEY_CURRENT_USER = "HKCU"
        HKEY_WOW64 = "WOW"

        def __init__(self, table):
            self._table = table

        def OpenKey(self, hive, subkey):
            key = (hive, subkey)
            if key not in self._table:
                raise OSError("missing")
            return _Key(self._table[key])

        def QueryValueEx(self, key, name):
            return (key._value, 1)

    fake = _FakeWinreg(
        {
            ("HKLM", r"SOFTWARE\7-Zip"): r"C:\WinApp\Utils\7-Zip",
            ("HKCU", r"SOFTWARE\7-Zip"): r"C:\WinApp\Utils\7-Zip",
            ("HKLM", r"SOFTWARE\WOW6432Node\7-Zip"): r"C:\Other\7-Zip",
        }
    )
    monkeypatch.setattr(compression, "winreg", fake)
    assert compression._seven_zip_registry_paths() == [
        r"C:\WinApp\Utils\7-Zip",
        r"C:\Other\7-Zip",
    ]


def test_seven_zip_registry_paths_returns_empty_off_windows(monkeypatch):
    # On non-Windows (no winreg module) the helper must safely return [].
    monkeypatch.setattr(compression, "winreg", None)
    assert compression._seven_zip_registry_paths() == []


def test_have_py7zr_reflects_import(monkeypatch):
    monkeypatch.setattr(compression, "py7zr", None)
    assert compression._have_py7zr() is False
    monkeypatch.undo()
    assert compression._have_py7zr() is True


def test_make_archive_uses_py7zr_when_forced(sample_tree, dest_dir):
    # When the user forces py7zr (prefer_py7zr=True), the library is used
    # even though a system binary would otherwise be preferred by default.
    out = make_archive(
        sample_tree, dest_dir, when=date(2026, 7, 12), compress_level=6, prefer_py7zr=True
    )
    assert out.suffix == ".7z"
    assert out.exists()
    # The archive must be a real, readable 7z produced by py7zr.
    import py7zr

    with py7zr.SevenZipFile(out, "r") as zf:
        names = {n for n in zf.getnames()}
    assert "a/f1.txt" in names
    assert "b.txt" in names


def test_make_archive_prefers_system_binary_by_default(
    monkeypatch, sample_tree, dest_dir
):
    # New default: prefer the (multithreaded, much faster) system 7-Zip binary
    # when present, without the user having to toggle anything.
    monkeypatch.setattr(compression, "find_7z", lambda: "/fake/7z")
    captured = {}

    class FakeProc:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            Path(cmd[5]).write_bytes(b"7z-archive")
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(compression.subprocess, "Popen", FakeProc)
    out = make_archive(sample_tree, dest_dir, when=date(2026, 7, 12))
    assert out.suffix == ".7z"
    assert out.exists()
    assert "-t7z" in captured["cmd"]
    # compress_level defaults to 6 -> the binary gets -mx6.
    assert "-mx6" in captured["cmd"]


def test_make_archive_prefers_system_binary_when_prefer_py7zr_false(
    monkeypatch, sample_tree, dest_dir
):
    # py7zr is importable, but the user opted to prefer the (faster) system
    # 7-Zip binary, so make_archive must shell out rather than use py7zr.
    monkeypatch.setattr(compression, "find_7z", lambda: "/fake/7z")

    captured = {}

    class FakeProc:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            Path(cmd[5]).write_bytes(b"7z-archive")
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(compression.subprocess, "Popen", FakeProc)
    out = make_archive(
        sample_tree, dest_dir, when=date(2026, 7, 12), prefer_py7zr=False
    )
    assert out.suffix == ".7z"
    assert out.exists()
    assert "-t7z" in captured["cmd"]
    assert "-mx6" in captured["cmd"]


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


def test_make_7z_py7zr_uses_preset_and_stays_single_threaded(
    monkeypatch, sample_tree, dest_dir
):
    # py7zr honours the LZMA2 "preset" but must NOT pass "threads"
    # (its internal compressor rejects it), so it stays single-threaded -- which
    # is why the multithreaded system binary is preferred by default.
    captured = {}

    class FakeZip:
        def __init__(self, path, mode, filters=None):
            captured["filters"] = filters

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, f, arcname=None):
            pass

    monkeypatch.setattr(compression.py7zr, "SevenZipFile", FakeZip)
    make_7z_py7zr(sample_tree, dest_dir, when=date(2026, 7, 12), compress_level=3)
    filt = captured["filters"][0]
    assert filt["id"] == compression.py7zr.FILTER_LZMA2
    assert filt["preset"] == 3
    assert "threads" not in filt


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


def test_make_7z_emits_realtime_progress(monkeypatch, sample_tree, dest_dir):
    # 7-Zip buffers its -bsp2 stderr when piped, so make_7z derives
    # realtime progress from the *growing temp archive file size* instead.
    # The fake process grows that file across polls; make_7z must forward
    # intermediate progress (not just start -> done).
    monkeypatch.setattr(compression, "find_7z", lambda: "/fake/7z")

    src_bytes = sum(
        f.stat().st_size for f in Path(sample_tree).rglob("*") if f.is_file()
    )
    seed = max(1, src_bytes // 2)

    class FakeProc:
        def __init__(self, cmd, **kw):
            self.returncode = 0
            self._polls = 0
            self._tmp = Path(cmd[5])
            self._tmp.write_bytes(b"")

        def poll(self):
            self._polls += 1
            # Grow the temp archive so the poll loop sees live progress.
            if self._polls <= 3:
                frac = self._polls / 3.0
                self._tmp.write_bytes(b"x" * max(1, int(seed * frac)))
                return None
            # Final archive size, written once before the process exits.
            self._tmp.write_bytes(b"x" * max(1, int(seed * 1.0)))
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(compression.subprocess, "Popen", FakeProc)
    seen = []
    out = make_7z(
        sample_tree, dest_dir, when=date(2026, 7, 12), on_progress=seen.append
    )
    assert out.suffix == ".7z"
    assert out.exists()
    # Start snapshot (PHASE_ZIPPING) + intermediates + final DONE.
    assert seen[0].phase == compression.PHASE_ZIPPING
    assert seen[-1].phase == compression.PHASE_DONE
    assert seen[-1].bytes_done == seen[-1].bytes_total
    # Intermediate progress with 0 < bytes_done < bytes_total (the bar moved).
    inter = [
        p
        for p in seen
        if p.phase == compression.PHASE_ZIPPING
        and 0 < p.bytes_done < p.bytes_total
    ]
    assert inter
    # Multiple distinct intermediate values -> smooth movement, not a jump.
    assert len({p.bytes_done for p in inter}) > 1
