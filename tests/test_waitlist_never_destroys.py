"""A waitlist signup must never destroy prior signups.

Regression test for a defect found 2026-08-30. `_load()` swallowed every
exception and returned [], so an unreadable file read as "nobody has signed
up" and the very next `_save` wrote only the new entry — wiping every prior
signup and returning HTTP 200.

On Render the file lives on a mounted persistent disk, so the loss is
everything ever collected, not merely since the last deploy. The git-tracked
copy never restores it.

Three fault modes are covered because they are the three that actually occur:
a truncated file, a file whose permissions were removed, and a zero-byte file
left by a crash between rename and fsync.
"""
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

import api.routes.waitlist as wl


SEED = [
    {"email": "one@example.com", "first_name": "One", "joined_at": "2026-01-01T00:00:00+00:00"},
    {"email": "two@example.com", "first_name": "Two", "joined_at": "2026-01-02T00:00:00+00:00"},
    {"email": "three@example.com", "first_name": "Three", "joined_at": "2026-01-03T00:00:00+00:00"},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    path = tmp_path / "waitlist.json"
    monkeypatch.setattr(wl, "WAITLIST_PATH", path)
    monkeypatch.setattr(wl, "_send_confirmation", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(wl.router)   # the router carries its own /api/waitlist prefix
    return TestClient(app, raise_server_exceptions=False), path


def _post(c):
    return c.post("/api/waitlist", json={"email": "new@example.com", "first_name": "New"})


def test_control_a_healthy_file_accepts_a_signup(client):
    c, path = client
    path.write_text(json.dumps(SEED))
    assert _post(c).status_code == 200
    assert len(json.loads(path.read_text())) == 4


def test_a_corrupt_file_is_never_overwritten(client):
    c, path = client
    broken = json.dumps(SEED)[:40]          # truncated mid-string
    path.write_text(broken)
    r = _post(c)
    assert r.status_code == 503, f"expected refusal, got {r.status_code}"
    assert path.read_text() == broken, "the corrupt file was overwritten — prior signups lost"


def test_a_zero_byte_file_is_treated_as_corrupt_not_as_empty(client):
    """What a crash between rename and fsync leaves behind. json.dumps([])
    is '[]', never '', so an empty file is always a fault."""
    c, path = client
    path.write_text("")
    r = _post(c)
    assert r.status_code == 503
    assert path.read_text() == ""


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_an_unreadable_file_is_never_overwritten(client):
    c, path = client
    path.write_text(json.dumps(SEED))
    path.chmod(0o000)
    try:
        r = _post(c)
        assert r.status_code == 503
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert len(json.loads(path.read_text())) == 3, "prior signups were lost"


def test_a_missing_file_is_still_a_normal_first_signup(client):
    """The guard must not break the legitimately-empty case."""
    c, path = client
    assert not path.exists()
    assert _post(c).status_code == 200
    assert len(json.loads(path.read_text())) == 1
