import types

from abackup.core.paths import is_inside
from abackup.core.validation import estimate_source_bytes, validate_add_job


def test_is_inside_equal(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    assert is_inside(d, d) is True


def test_is_inside_subfolder(tmp_path):
    parent = tmp_path / "src"
    child = parent / "sub"
    child.mkdir(parents=True)
    assert is_inside(child, parent) is True


def test_is_inside_sibling_false(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert is_inside(b, a) is False


def test_is_inside_unrelated_false(tmp_path):
    parent = tmp_path / "src"
    other = tmp_path / "other" / "deep"
    parent.mkdir()
    other.mkdir(parents=True)
    assert is_inside(other, parent) is False


def test_validate_add_job_rejects_missing_source(tmp_path):
    errs = validate_add_job(tmp_path / "nope", tmp_path / "dest")
    assert errs == ["Source must be an existing folder."]


def test_validate_add_job_rejects_empty_dest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    errs = validate_add_job(src, "")
    assert errs == ["Destination is required."]


def test_validate_add_job_rejects_dest_equals_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    errs = validate_add_job(src, src)
    assert errs == ["Destination must not be the source or inside it."]


def test_validate_add_job_rejects_dest_inside_source(tmp_path):
    src = tmp_path / "src"
    dest = src / "sub"
    src.mkdir()
    errs = validate_add_job(src, dest)
    assert errs == ["Destination must not be the source or inside it."]


def test_validate_add_job_rejects_insufficient_disk_space(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.bin").write_bytes(b"x" * 10_000_000)
    dest = tmp_path / "dest"
    monkeypatch.setattr(
        "abackup.core.validation.shutil.disk_usage",
        lambda p: types.SimpleNamespace(free=100),
    )
    errs = validate_add_job(src, dest)
    assert any("Not enough free space" in e for e in errs)


def test_validate_add_job_accepts_valid(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("hello")
    dest = tmp_path / "dest"
    monkeypatch.setattr(
        "abackup.core.validation.shutil.disk_usage",
        lambda p: types.SimpleNamespace(free=10**12),
    )
    errs = validate_add_job(src, dest)
    assert errs == []
    # Validation is pure: it must not create the destination directory. The
    # backup methods (copy_tree / make_zip / make_7z) create it themselves.
    assert not dest.exists()


def test_validate_add_job_margin_keeps_buffer(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.bin").write_bytes(b"x" * 100)
    dest = tmp_path / "dest"
    monkeypatch.setattr(
        "abackup.core.validation.shutil.disk_usage",
        lambda p: types.SimpleNamespace(free=200),
    )
    # needed 100 <= 200*0.9 = 180 -> accepted (10% buffer kept).
    assert validate_add_job(src, dest, margin=0.1) == []
    # needed 100 <= 200*0.5 = 100 -> accepted (exactly 50% buffer).
    assert validate_add_job(src, dest, margin=0.5) == []
    # needed 100 > 200*0.4 = 80 -> rejected (only 40% buffer requested).
    assert any(
        "Not enough free space" in e
        for e in validate_add_job(src, dest, margin=0.6)
    )


def test_estimate_source_bytes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a").mkdir()
    (src / "a" / "x.bin").write_bytes(b"x" * 100)
    (src / "y.bin").write_bytes(b"y" * 50)
    assert estimate_source_bytes(src) == 150
