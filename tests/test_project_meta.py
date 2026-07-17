"""Project metadata / config sanity checks (IMP-103)."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_parses() -> None:
    p = Path("pyproject.toml")
    assert p.exists()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["project"]["name"] == "abackup"


def test_pyproject_has_ruff_config() -> None:
    p = Path("pyproject.toml")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "tool" in data
    assert "ruff" in data["tool"]
    assert "lint" in data["tool"]["ruff"]


def test_ruff_dev_dependency_present() -> None:
    p = Path("pyproject.toml")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    dev = data["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("ruff") for dep in dev)


def test_ci_workflow_present() -> None:
    ci = Path(".github/workflows/ci.yml")
    assert ci.exists()
    text = ci.read_text(encoding="utf-8")
    assert "ruff check" in text
    assert "cov-fail-under=90" in text


def test_precommit_config_present() -> None:
    pc = Path(".pre-commit-config.yaml")
    assert pc.exists()
    assert "ruff" in pc.read_text(encoding="utf-8")
