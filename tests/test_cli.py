import pytest

from abackup.cli import build_parser, main
from abackup.config import init_storage, load_settings, save_settings
from abackup.models import Settings


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "abackup" in capsys.readouterr().out


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.config_dir is None
    assert args.reset is False


def test_reset_flips_first_run(tmp_config):
    init_storage(tmp_config)
    save_settings(Settings(first_run_completed=True), tmp_config)
    main(["--reset", "--config-dir", tmp_config])
    assert load_settings(tmp_config).first_run_completed is False


def test_reset_requires_config_dir():
    with pytest.raises(SystemExit):
        main(["--reset"])
