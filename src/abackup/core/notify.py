"""Desktop notifications and failure sounds (RM-08, RM-09).

Both functions are best-effort: any failure is swallowed (logged, not raised)
so a notification can never break a backup. The backends are injectable for
tests, and no heavy dependency (e.g. plyer) is required at import time.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Injectable backend signatures.
NotifyBackend = Callable[[str, str], None]
BeepBackend = Callable[[], None]


def _notify_plyer(title: str, message: str) -> None:
    try:
        from plyer import notification  # type: ignore

        notification.notify(title=title, message=message, app_name="abackup")
    except Exception as exc:  # pragma: no cover - optional dep / platform
        raise RuntimeError(f"plyer backend failed: {exc}") from exc


def _notify_windows(title: str, message: str) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)  # type: ignore[attr-defined]


def _notify_posix(title: str, message: str) -> None:
    import subprocess

    for cmd in (
        ["notify-send", title, message],
        ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
    ):
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=5)
            return
        except (OSError, subprocess.SubprocessError):
            continue
    raise RuntimeError("no posix notifier available")


def notify(title: str, message: str, *, backend: NotifyBackend | None = None) -> None:
    """Show a desktop notification. Best-effort; never raises.

    ``backend`` is injectable (tests pass a fake). When ``None``, auto-detect:
    plyer (if importable) -> Windows MessageBox -> notify-send/osascript.
    """
    if backend is not None:
        try:
            backend(title, message)
        except Exception as exc:  # pragma: no cover - test backend
            logger.warning("notify backend failed: %s", exc)
        return
    try:
        _notify_plyer(title, message)
    except Exception:
        try:
            if sys.platform == "win32":
                _notify_windows(title, message)
            else:
                _notify_posix(title, message)
        except Exception as exc:
            logger.warning("desktop notification failed: %s", exc)


def beep(*, backend: BeepBackend | None = None) -> None:
    """Emit a short failure sound. Best-effort; never raises.

    ``backend`` is injectable (tests pass a fake). When ``None``, use
    ``winsound`` on Windows, otherwise a terminal bell (no-op in CI).
    """
    if backend is not None:
        try:
            backend()
        except Exception as exc:  # pragma: no cover - test backend
            logger.warning("beep backend failed: %s", exc)
        return
    try:
        if sys.platform == "win32":
            import winsound

            winsound.Beep(440, 200)
        else:
            # Terminal bell; harmless on headless/CI.
            print("\a", end="", flush=True)
    except Exception as exc:
        logger.warning("beep failed: %s", exc)
