"""Tests for the notify/beep utilities (RM-08, RM-09)."""

from __future__ import annotations

from abackup.core.notify import beep, notify


def test_notify_calls_injected_backend():
    calls = []
    notify("title", "msg", backend=lambda t, m: calls.append((t, m)))
    assert calls == [("title", "msg")]


def test_notify_swallows_backend_error():
    def boom(title, message):
        raise RuntimeError("nope")

    # Should not raise.
    notify("t", "m", backend=boom)


def test_beep_calls_injected_backend():
    calls = []
    beep(backend=lambda: calls.append(True))
    assert calls == [True]


def test_beep_swallows_backend_error():
    def boom():
        raise RuntimeError("nope")

    # Should not raise.
    beep(backend=boom)
