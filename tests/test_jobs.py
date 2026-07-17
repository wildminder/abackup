from abackup.core.jobs import add_job, get_job, list_jobs, remove_job, update_job
from abackup.models import BackupJob
from abackup.utils.errors import JobNotFound


def _job(id_):
    return BackupJob(source=f"C:/{id_}", destination="D:/b", method="copy", id=id_)


def test_add_and_list():
    jobs = add_job([], _job("1"))
    jobs = add_job(jobs, _job("2"))
    assert [j.id for j in list_jobs(jobs)] == ["1", "2"]


def test_add_dedupe_by_id():
    jobs = add_job([], _job("1"))
    jobs = add_job(jobs, _job("1"))
    assert len(jobs) == 1


def test_get_job():
    jobs = add_job([], _job("1"))
    assert get_job(jobs, "1").id == "1"


def test_get_job_missing_raises():
    try:
        get_job([], "x")
    except JobNotFound:
        return
    raise AssertionError("expected JobNotFound")


def test_update_job():
    jobs = add_job([], _job("1"))
    updated = BackupJob(source="C:/1", destination="D:/b", method="copy", id="1", last_status="success")
    jobs = update_job(jobs, updated)
    assert get_job(jobs, "1").last_status == "success"


def test_update_job_missing_raises():
    try:
        update_job([], _job("1"))
    except JobNotFound:
        return
    raise AssertionError("expected JobNotFound")


def test_remove_job():
    jobs = add_job([], _job("1"))
    jobs = add_job(jobs, _job("2"))
    jobs = remove_job(jobs, "1")
    assert [j.id for j in jobs] == ["2"]


def test_remove_job_missing_raises():
    try:
        remove_job([], "x")
    except JobNotFound:
        return
    raise AssertionError("expected JobNotFound")
