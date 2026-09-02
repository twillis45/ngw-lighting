"""The free-tier limit must not depend on the client cooperating.

Found 2026-09-02. /recommend enforced the limit server-side — the gate was
real — but the COUNT it read only ever rose because the browser voluntarily
POSTed /api/usage/increment, the sole call site in the repo. Deleting one
fetch bought unlimited free analyses.

Measured before the fix:

    honest client, increments each time : 3 free, then 402
    never call increment                : 8 of 8 succeeded

This is the same shape as the rate-limit bypass fixed on 2026-08-30: a gate
whose input is supplied by the caller is not a gate. It matters now rather
than later because Stripe is still in test mode — nobody has been charged, so
nothing has been lost yet.

STILL OPEN and deliberately not fixed here: rotating session_id also bypasses
the limit, because an anonymous caller has no stable identity. Closing that
means keying anonymous counts on IP, which blocks shared offices and cafes —
a product decision, not a bug fix.
"""
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # NGW_DEV_MODE=1 in .env makes get_optional_user return a dev user whose
    # accumulated count already exceeds the threshold, so every request 402s
    # for the wrong reason. conftest documents this; a raw script hit it.
    monkeypatch.setenv("NGW_DEV_MODE", "0")
    monkeypatch.setenv("NGW_JWT_SECRET", "x" * 64)
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def _analyze(c, sid):
    return c.post("/recommend", json={
        "systems": [{"id": "s1", "name": "S",
                     "criteria": {"brightness": 5000, "color_accuracy": 90},
                     "features": {}}],
        "metadata": {"session_id": sid}}).status_code


def test_the_limit_holds_without_any_client_cooperation(client):
    """The bypass: never call /api/usage/increment."""
    sid = "nocoop-" + uuid.uuid4().hex[:10]
    codes = [_analyze(client, sid) for _ in range(8)]
    granted = codes.count(200)
    assert granted == 3, (
        f"{granted} free analyses granted to a client that never reported "
        f"usage — the free tier is enforced only against a cooperating client: {codes}")


def test_a_stale_client_still_calling_increment_does_not_lose_free_analyses(client):
    """The regression risk of fixing the above. If /api/usage/increment still
    incremented, a cached bundle would count twice and cut users off at 2."""
    sid = "stale-" + uuid.uuid4().hex[:10]
    codes = []
    for _ in range(6):
        codes.append(_analyze(client, sid))
        client.post("/api/usage/increment", json={"session_id": sid})
    granted = codes.count(200)
    assert granted == 3, (
        f"a client still POSTing /api/usage/increment got {granted} free "
        f"analyses instead of 3 — the count is being applied twice: {codes}")


def test_the_shipped_client_does_not_drive_the_count():
    """Structural. The count must come from the server path, not the browser."""
    from pathlib import Path
    ui = Path(__file__).resolve().parent.parent / "ui" / "src"
    callers = []
    for f in list(ui.rglob("*.js")) + list(ui.rglob("*.jsx")):
        code = "\n".join(l.split("//", 1)[0] for l in f.read_text(encoding="utf-8").splitlines())
        if "usage/increment" in code:
            callers.append(str(f.relative_to(ui)))
    assert not callers, (
        f"the client drives the usage count again, which makes the free tier "
        f"opt-in for whoever edits it: {callers}")
