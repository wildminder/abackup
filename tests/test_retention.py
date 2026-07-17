"""Tests for the retention enforcer (RM-03)."""


from abackup.core.retention import enforce_retention


def test_retention_keep_all_when_none(tmp_path):
    archives = [tmp_path / f"b_{i}.zip" for i in range(5)]
    for a in archives:
        a.write_text("x")
    deleted = enforce_retention(archives, None)
    assert deleted == []
    assert len(list(tmp_path.glob("*.zip"))) == 5


def test_retention_keeps_last_n(tmp_path):
    archives = [tmp_path / f"b_{i}.zip" for i in range(5)]
    for i, a in enumerate(archives):
        a.write_text("x")
        # Stagger mtimes so ordering is deterministic.
        import os

        os.utime(a, (1000 + i, 1000 + i))
    deleted = enforce_retention(archives, 2)
    assert len(deleted) == 3
    # Only the 2 newest remain.
    remaining = sorted(p.name for p in tmp_path.glob("*.zip"))
    assert remaining == ["b_3.zip", "b_4.zip"]


def test_retention_deletes_oldest_first(tmp_path):
    archives = [tmp_path / f"b_{i}.zip" for i in range(3)]
    for i, a in enumerate(archives):
        a.write_text("x")
        import os

        os.utime(a, (1000 + i, 1000 + i))
    deleted = enforce_retention(archives, 1)
    assert len(deleted) == 2
    remaining = sorted(p.name for p in tmp_path.glob("*.zip"))
    assert remaining == ["b_2.zip"]
