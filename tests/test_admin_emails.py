"""Tests for centralized admin email resolution and face-preflight access.

Covers the three-part revenue-blocker fix:
  1. face-preflight reachable by a normal signed-in user (not dev, not admin)
  3. admin identity resolved from NGW_ADMIN_EMAILS with a safe default
"""
from __future__ import annotations

import io
import os
import time
import uuid as uuid_mod

import pytest
from fastapi.testclient import TestClient

from db.database import init_db, get_db, get_user_by_email
from auth.security import create_access_token

from main import app  # noqa: E402

client = TestClient(app)

_PREHASHED = "$2b$12$LJ3m4ys2Z3s8R5I2R5I2R.q9w8e7r6t5y4u3i2o1p0a9s8d7f6g5h4"

#: The address hardcoded across the codebase before this fix.
LEGACY_ADMIN = "todd@toddwillisphoto.com"


def _ensure_user(email: str, username: str) -> dict:
    """Insert user directly (bypassing bcrypt) or return existing."""
    user = get_user_by_email(email)
    if user:
        return user
    uid = uuid_mod.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, username, hashed_pw, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (uid, email.lower(), username, _PREHASHED, now, now),
        )
    return {"id": uid, "email": email.lower(), "username": username}


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


# ── Part 3: NGW_ADMIN_EMAILS resolver ─────────────────────

def test_admin_emails_from_env(monkeypatch):
    """With NGW_ADMIN_EMAILS set, every listed address resolves as admin."""
    from config.admin import is_admin, get_admin_emails

    monkeypatch.setenv("NGW_ADMIN_EMAILS", "a@x.com,b@y.com")

    assert is_admin("a@x.com")
    assert is_admin("b@y.com")
    assert not is_admin("c@z.com")
    assert get_admin_emails() == frozenset({"a@x.com", "b@y.com"})


def test_admin_emails_env_parsing_matches_convention(monkeypatch):
    """Whitespace, casing, and empty segments handled like db/provenance._env_emails."""
    from config.admin import is_admin

    monkeypatch.setenv("NGW_ADMIN_EMAILS", " A@X.com , ,b@y.com,")

    assert is_admin("a@x.com")
    assert is_admin("A@X.COM")
    assert is_admin("b@y.com")


def test_admin_default_when_env_unset(monkeypatch):
    """With the var unset, the legacy hardcoded admin still resolves — no regression."""
    from config.admin import is_admin, get_admin_emails

    monkeypatch.delenv("NGW_ADMIN_EMAILS", raising=False)

    assert is_admin(LEGACY_ADMIN)
    assert get_admin_emails() == frozenset({LEGACY_ADMIN})


def test_admin_default_when_env_blank(monkeypatch):
    """A blank var falls back to the default rather than locking everyone out."""
    from config.admin import is_admin

    monkeypatch.setenv("NGW_ADMIN_EMAILS", "   ")

    assert is_admin(LEGACY_ADMIN)


def test_env_replaces_default_when_set(monkeypatch):
    """An explicit list replaces the default — the legacy address is not implicit."""
    from config.admin import is_admin

    monkeypatch.setenv("NGW_ADMIN_EMAILS", "info@noguessworksystems.com")

    assert is_admin("info@noguessworksystems.com")
    assert not is_admin(LEGACY_ADMIN)


def test_is_admin_handles_none_and_empty():
    from config.admin import is_admin

    assert not is_admin(None)
    assert not is_admin("")


# ── Part 1: face-preflight reachable by a normal user ─────

def _tiny_jpeg() -> bytes:
    """A minimal valid JPEG. Face detection will find nothing, which is fine —
    this test isolates the auth gate, not CV correctness."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (128, 128, 128)).save(buf, format="JPEG")
    return buf.getvalue()


def test_face_preflight_allows_normal_signed_in_user(monkeypatch):
    """A signed-in user who is neither dev nor admin must reach face-preflight.

    The Studio shell depends on this endpoint; a 401/403 here starves the
    light pools before the paywall is ever evaluated.
    """
    monkeypatch.setenv("NGW_DEV_EMAILS", "someone-else@ngw-test.com")
    monkeypatch.delenv("NGW_ADMIN_EMAILS", raising=False)

    user = _ensure_user("normal-user@ngw-test.com", "Normal User")
    token = create_access_token(user["id"])

    resp = client.post(
        "/api/lab/face-preflight",
        files={"image": ("photo.jpg", _tiny_jpeg(), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert "ok" in resp.json()


def test_face_preflight_allows_anonymous_caller(monkeypatch):
    """The shell issues this fetch with no Authorization header at all.

    See ui/src/screens/studio/_core/useLightingRead.js — it sends a bare
    fetch(), so anonymous callers must not be rejected.
    """
    monkeypatch.setenv("NGW_DEV_EMAILS", "someone-else@ngw-test.com")

    resp = client.post(
        "/api/lab/face-preflight",
        files={"image": ("photo.jpg", _tiny_jpeg(), "image/jpeg")},
    )

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


def test_lab_curator_routes_stay_gated(monkeypatch):
    """Opening face-preflight must not open the rest of the /lab router."""
    monkeypatch.setenv("NGW_DEV_EMAILS", "someone-else@ngw-test.com")

    user = _ensure_user("normal-user2@ngw-test.com", "Normal User 2")
    token = create_access_token(user["id"])
    auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/lab/status", headers=auth).status_code == 403
    assert client.get("/api/lab/gold-set", headers=auth).status_code == 403
    assert client.get("/api/lab/coverage-map", headers=auth).status_code == 403
