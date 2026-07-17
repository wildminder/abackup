import json
from pathlib import Path

from abackup.utils.errors import (
    ABackupError,
    ConfigError,
    DestinationError,
    JobNotFound,
    SourceNotFound,
)
from abackup.utils.logging import RunLogger


def test_run_logger_writes_jsonl(tmp_data):
    logger = RunLogger(tmp_data, "job1")
    logger.log("info", {"a": 1})
    logger.log("error", {"msg": "boom"})
    lines = (logger.path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith('{"level": "info"')
    assert lines[1].startswith('{"level": "error"')


def test_run_logger_writes_shared_persistent_log(tmp_data):
    # RM-07: events also land in a single shared <data>/logs/abackup.log.
    logger = RunLogger(tmp_data, "job1")
    logger.log("info", {"a": 1})
    shared = logger.shared_path
    assert shared.exists()
    assert shared.parent.name == "logs"
    shared_lines = shared.read_text(encoding="utf-8").strip().splitlines()
    assert len(shared_lines) == 1
    assert shared_lines[0].startswith('{"level": "info"')


def test_run_logger_shared_log_aggregates_multiple_jobs(tmp_data):
    RunLogger(tmp_data, "job1").log("info", {"n": 1})
    RunLogger(tmp_data, "job2").log("info", {"n": 2})
    shared = Path(tmp_data) / "logs" / "abackup.log"
    lines = shared.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["level"] == "info" for line in lines)


def test_exception_hierarchy():
    assert issubclass(ConfigError, ABackupError)
    assert issubclass(SourceNotFound, ABackupError)
    assert issubclass(DestinationError, ABackupError)
    assert issubclass(JobNotFound, ABackupError)
