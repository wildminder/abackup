"""Tests for OS startup-task registration (RM-01b)."""

import sys
from unittest.mock import MagicMock

import pytest

import abackup.core.platform_task as pt


def test_register_startup_windows_calls_schtasks(monkeypatch):
    if not sys.platform.startswith("win"):
        pytest.skip("Windows-only path")
    calls = []
    monkeypatch.setattr(pt.subprocess, "run", lambda *a, **k: calls.append(a) or MagicMock())
    pt.register_startup(command="python -m abackup")
    assert calls, "subprocess.run was not called"
    assert calls[0][0][0] == "schtasks"


def test_register_startup_posix_systemd(monkeypatch):
    if sys.platform.startswith("win"):
        pytest.skip("POSIX-only path")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(pt.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    calls = []
    monkeypatch.setattr(pt.subprocess, "run", lambda *a, **k: calls.append(a) or MagicMock())
    pt.register_startup(command="python -m abackup")
    assert calls, "subprocess.run was not called"
    assert "systemctl" in calls[0][0]


def test_register_startup_posix_autostart_fallback(monkeypatch, tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("POSIX-only path")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(pt.shutil, "which", lambda name: None)
    monkeypatch.setattr(pt.os, "environ", {**pt.os.environ, "XDG_CONFIG_HOME": str(tmp_path)})
    pt.register_startup(command="python -m abackup")
    desktop = tmp_path / "autostart" / f"{pt.TASK_NAME}.desktop"
    assert desktop.exists()
    assert "python -m abackup" in desktop.read_text()


def test_unregister_startup_posix_autostart(monkeypatch, tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("POSIX-only path")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(pt.shutil, "which", lambda name: None)
    monkeypatch.setattr(pt.os, "environ", {**pt.os.environ, "XDG_CONFIG_HOME": str(tmp_path)})
    pt.register_startup(command="python -m abackup")
    desktop = tmp_path / "autostart" / f"{pt.TASK_NAME}.desktop"
    assert desktop.exists()
    pt.unregister_startup()
    assert not desktop.exists()
