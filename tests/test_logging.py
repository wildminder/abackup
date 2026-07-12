from abackup.utils.logging import RunLogger
from abackup.utils.errors import ABackupError, ConfigError, SourceNotFound, DestinationError, JobNotFound


def test_run_logger_writes_jsonl(tmp_data):
    logger = RunLogger(tmp_data, "job1")
    logger.log("info", {"a": 1})
    logger.log("error", {"msg": "boom"})
    lines = (logger.path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith('{"level": "info"')
    assert lines[1].startswith('{"level": "error"')


def test_exception_hierarchy():
    assert issubclass(ConfigError, ABackupError)
    assert issubclass(SourceNotFound, ABackupError)
    assert issubclass(DestinationError, ABackupError)
    assert issubclass(JobNotFound, ABackupError)
