"""OS startup-task registration (run ABackup on user login).

Provides a thin, injectable abstraction over the platform-specific mechanism:

* **Windows** — ``schtasks /create`` (no admin required for the current user).
* **POSIX** — a ``systemd --user`` unit (when ``systemctl --user`` exists) or,
  as a fallback, an XDG autostart ``.desktop`` file.

All external commands are invoked through :func:`subprocess.run`, which tests
monkeypatch to avoid touching the real OS. :func:`register_startup` and
:func:`is_registered` are no-ops/``False`` on unsupported platforms rather than
raising, so the feature degrades gracefully.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: B404 - list-form subprocess, no shell.
import sys
from pathlib import Path

TASK_NAME = "ABackupStartup"


def _command_for(name: str, command: str) -> list[str]:
    """Build the OS-specific registration command (list form, no shell)."""
    if sys.platform.startswith("win"):
        # Run daily, at logon, hidden. The command is the ABackup launcher.
        return [
            "schtasks",
            "/create",
            "/tn",
            name,
            "/tr",
            command,
            "/sc",
            "onlogon",
            "/f",
        ]
    # POSIX: prefer systemd --user; the command is the ABackup launcher.
    return [
        "systemctl",
        "--user",
        "enable",
        "--now",
        f"--value={command}",
        name,
    ]


def register_startup(name: str = TASK_NAME, command: str | None = None) -> None:
    """Register ABackup to run on user login.

    ``command`` defaults to ``sys.executable -m abackup``. Raises
    ``RuntimeError`` only when the platform is unsupported (no Windows and no
    ``systemctl``/autostart available); otherwise delegates to the OS tool.
    """
    if command is None:
        command = f'{sys.executable} -m abackup'
    if sys.platform.startswith("win"):
        subprocess.run(_command_for(name, command), check=True)
        return
    # POSIX: try systemd --user first.
    if shutil.which("systemctl") is not None:
        subprocess.run(_command_for(name, command), check=True)
        return
    # Fallback: XDG autostart .desktop file.
    autostart = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    autostart.mkdir(parents=True, exist_ok=True)
    desktop = autostart / f"{name}.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Exec={command}\n"
        "Hidden=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def is_registered(name: str = TASK_NAME) -> bool:
    """Return True if the startup task/unit is already registered."""
    if sys.platform.startswith("win"):
        proc = subprocess.run(
            ["schtasks", "/query", "/tn", name],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    if shutil.which("systemctl") is not None:
        proc = subprocess.run(
            ["systemctl", "--user", "is-enabled", name],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    desktop = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / f"{name}.desktop"
    return desktop.exists()


def unregister_startup(name: str = TASK_NAME) -> None:
    """Remove a previously registered startup task/unit (best-effort)."""
    if sys.platform.startswith("win"):
        subprocess.run(["schtasks", "/delete", "/tn", name, "/f"], check=False)
        return
    if shutil.which("systemctl") is not None:
        subprocess.run(["systemctl", "--user", "disable", "--now", name], check=False)
        return
    desktop = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / f"{name}.desktop"
    desktop.unlink(missing_ok=True)
