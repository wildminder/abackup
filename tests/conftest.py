"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path: Path) -> str:
    d = tmp_path / "config"
    d.mkdir()
    return str(d)


@pytest.fixture
def tmp_data(tmp_path: Path) -> str:
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


@pytest.fixture
def sample_tree(tmp_path: Path) -> Path:
    src = tmp_path / "source"
    (src / "a").mkdir(parents=True)
    (src / "a" / "f1.txt").write_text("hello", encoding="utf-8")
    (src / "b.txt").write_text("world", encoding="utf-8")
    return src


@pytest.fixture
def dest_dir(tmp_path: Path) -> Path:
    d = tmp_path / "dest"
    d.mkdir()
    return d
