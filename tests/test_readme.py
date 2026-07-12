from pathlib import Path

import abackup
from abackup.cli import build_parser


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert f'version = "{abackup.__version__}"' in text


def test_readme_mentions_commands():
    readme = Path(__file__).resolve().parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    for token in [
        "abackup",
        "--config-dir",
        "Direct copy",
        "Zip archive",
        "Run all",
        "--run-all",
        "--workers",
        "max_workers",
        "Settings",
        "compression level",
        "Documents",
        "home",
        "--show-settings",
        "zip_compression_level",
        "Cancel",
        "Realtime progress",
        "Byte-level",
        "current file",
    ]:
        assert token in text


def test_parser_exposes_all_flags():
    args = build_parser().parse_args(
        ["--config-dir", "x", "--data-dir", "y"]
    )
    assert args.config_dir == "x"
    assert args.data_dir == "y"
