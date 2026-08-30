"""Creating a reference entry must never destroy the existing library.

Regression test for a defect found 2026-08-30, the same shape as the waitlist
one: `_load_reference_library` swallowed every exception and returned [], so a
create read "no entries", appended one, and wrote the file back — destroying
all 16 gold-tier entries and returning HTTP 200.

Two fixes are asserted here. The loader now refuses on a present-but-unusable
file, and the saver is atomic (temp file + rename + fsync) so a crash mid-write
can no longer produce the corrupt state the loader has to refuse.
"""
import json
import os
import stat

import pytest

import api.routes.lab as lab


SEED = [{"reference_id": f"gold_{i}", "lighting_pattern": "loop"} for i in range(16)]


@pytest.fixture
def libpath(tmp_path, monkeypatch):
    p = tmp_path / "reference_library.json"
    monkeypatch.setattr(lab, "_REFERENCE_LIBRARY_PATH", str(p))
    return p


def test_control_a_healthy_library_loads(libpath):
    libpath.write_text(json.dumps(SEED))
    assert len(lab._load_reference_library()) == 16


def test_a_missing_library_is_still_empty_not_an_error(libpath):
    assert lab._load_reference_library() == []


def test_a_corrupt_library_refuses_rather_than_reporting_empty(libpath):
    from fastapi import HTTPException
    libpath.write_text(json.dumps(SEED)[:50])
    with pytest.raises(HTTPException) as e:
        lab._load_reference_library()
    assert e.value.status_code == 503
    assert len(libpath.read_text()) == 50, "the corrupt file was touched"


def test_a_zero_byte_library_is_corrupt_not_empty(libpath):
    from fastapi import HTTPException
    libpath.write_text("")
    with pytest.raises(HTTPException) as e:
        lab._load_reference_library()
    assert e.value.status_code == 503


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_an_unreadable_library_refuses(libpath):
    from fastapi import HTTPException
    libpath.write_text(json.dumps(SEED))
    libpath.chmod(0o000)
    try:
        with pytest.raises(HTTPException) as e:
            lab._load_reference_library()
        assert e.value.status_code == 503
    finally:
        libpath.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert len(json.loads(libpath.read_text())) == 16


def test_save_is_atomic_and_leaves_no_temp_behind(libpath):
    lab._save_reference_library(SEED)
    assert len(json.loads(libpath.read_text())) == 16
    assert not os.path.exists(f"{libpath}.tmp"), "temp file survived the save"


def test_a_round_trip_preserves_every_entry(libpath):
    lab._save_reference_library(SEED)
    assert lab._load_reference_library() == SEED
