"""The customer journal image route, pinned by ownership.

Written 2026-09-14 after a click-sweep of the demo path found every Journal
thumbnail returning 403. They were fetched from `/api/lab/analysis/{id}/image`,
a Lab route guarded by `assert_lab_access`, which fails closed: with
NGW_DEV_EMAILS unset nobody is authorized. So a customer-facing screen was
sourcing its images from a developer-only endpoint and rendered blank cards for
every user — including the account that created the analyses.

The repair was a customer route that asks the question a customer screen should
ask — *is this analysis yours* — rather than putting demo accounts on the dev
allowlist, which would have hidden the failure instead of fixing it.

These tests exist because that is an authorization rule on an image URL that
carries its token in a query parameter, which is exactly the shape of thing
that silently becomes wrong. The Lab route's own docstring records a previous
version of this same mistake.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

OWNER = f"owner-{uuid.uuid4().hex[:8]}@example.test"
OTHER = f"other-{uuid.uuid4().hex[:8]}@example.test"
PASSWORD = "TestPass!2026x"


def _register(email: str) -> str:
    """Create an account and return its bearer token."""
    r = client.post("/api/auth/register",
                    json={"email": email, "password": PASSWORD, "username": email[:12]})
    if r.status_code == 201:
        return r.json()["token"]
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def owned_analysis():
    """An analysis row owned by OWNER, with a real image file on disk."""
    from db.database import DATA_DIR, get_db

    # Must sit inside an approved base or _is_safe_image_path rejects it.
    uploads = DATA_DIR / "uploads" / "lab"
    uploads.mkdir(parents=True, exist_ok=True)
    img = uploads / f"test-journal-{uuid.uuid4().hex[:8]}.jpg"
    # 1x1 JPEG — enough to be served; content is irrelevant to authorization.
    img.write_bytes(bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300"
        + "08" * 64
        + "ffc9000b080001000101011100ffcc000600101005ffda0008010100003f00d2cf20ffd9"
    ))
    analysis_id = uuid.uuid4().hex
    with get_db() as conn:
        conn.execute(
            "INSERT INTO analysis_results (analysis_id, image_path, result_json,"
            " created_at, user_email) VALUES (?,?,?,?,?)",
            (analysis_id, str(img), "{}", 0.0, OWNER),
        )
        conn.commit()
    yield analysis_id, img
    with get_db() as conn:
        conn.execute("DELETE FROM analysis_results WHERE analysis_id = ?", (analysis_id,))
        conn.commit()
    img.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _no_dev_mode(monkeypatch):
    """Dev mode short-circuits authentication; these tests are about the rule."""
    monkeypatch.delenv("NGW_DEV_MODE", raising=False)


class TestOwnershipDecidesAccess:
    def test_the_owner_can_fetch_their_own_analysis_image(self, owned_analysis):
        analysis_id, _ = owned_analysis
        token = _register(OWNER)
        r = client.get(f"/api/analysis/{analysis_id}/image", params={"token": token})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/")

    def test_another_account_gets_404_not_403(self, owned_analysis):
        """404, not 403 — a 403 would confirm the id exists."""
        analysis_id, _ = owned_analysis
        token = _register(OTHER)
        r = client.get(f"/api/analysis/{analysis_id}/image", params={"token": token})
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"

    def test_no_token_is_rejected(self, owned_analysis):
        analysis_id, _ = owned_analysis
        r = client.get(f"/api/analysis/{analysis_id}/image")
        assert r.status_code == 401

    def test_a_garbage_token_is_rejected(self, owned_analysis):
        analysis_id, _ = owned_analysis
        r = client.get(f"/api/analysis/{analysis_id}/image", params={"token": "not-a-jwt"})
        assert r.status_code == 401

    def test_an_unowned_row_is_served_to_nobody(self):
        """Older rows carry no user_email. Absence of an owner is not a grant."""
        from db.database import DATA_DIR, get_db

        uploads = DATA_DIR / "uploads" / "lab"
        uploads.mkdir(parents=True, exist_ok=True)
        img = uploads / f"test-orphan-{uuid.uuid4().hex[:8]}.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")
        analysis_id = uuid.uuid4().hex
        with get_db() as conn:
            conn.execute(
                "INSERT INTO analysis_results (analysis_id, image_path, result_json,"
                " created_at, user_email) VALUES (?,?,?,?,?)",
                (analysis_id, str(img), "{}", 0.0, None),
            )
            conn.commit()
        try:
            token = _register(OWNER)
            r = client.get(f"/api/analysis/{analysis_id}/image", params={"token": token})
            assert r.status_code == 404
        finally:
            with get_db() as conn:
                conn.execute("DELETE FROM analysis_results WHERE analysis_id = ?", (analysis_id,))
                conn.commit()
            img.unlink(missing_ok=True)


class TestTheLabRouteStillGatesOnLabAccess:
    def test_a_plain_account_cannot_use_the_lab_route(self, owned_analysis, monkeypatch):
        """The customer route must not have loosened the Lab one beside it."""
        monkeypatch.delenv("NGW_DEV_EMAILS", raising=False)
        analysis_id, _ = owned_analysis
        token = _register(OWNER)
        r = client.get(f"/api/lab/analysis/{analysis_id}/image", params={"token": token})
        assert r.status_code == 403, f"expected 403 from the Lab route, got {r.status_code}"
