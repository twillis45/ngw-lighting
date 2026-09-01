"""Global pytest configuration — sets required env vars before any app import."""
import os

# Must be set before main.py / auth/security.py is imported, otherwise the
# RuntimeError("NGW_JWT_SECRET is not set...") fires at collection time.
os.environ.setdefault("NGW_JWT_SECRET", "test-secret-value-for-pytest-not-for-production")

# Force NGW_DEV_MODE=0 in tests so load_dotenv() (called inside main.py) cannot
# activate dev-mode auth.  Tests that need to act as an authenticated user use
# app.dependency_overrides instead (see test_admin.py, test_shoot_match.py).
# Without this, .env's NGW_DEV_MODE=1 makes get_optional_user return a dev-mode
# user whose accumulated analysis count (user:dev-mode) triggers the paywall gate.
os.environ["NGW_DEV_MODE"] = "0"


# ── Rate-limit isolation ─────────────────────────────────────────────────────
# The limiter's buckets are process-global and were never reset between tests,
# while every TestClient shares one client IP. So a test's result depended on
# what earlier tests had already spent in the same 60-second window.
#
# Found 2026-08-31: test_20_concurrent_shoot_match PASSES alone and FAILS in the
# full suite. It fires 20 requests against a limit of 30/60s, so any earlier
# shoot-match call in the same window pushes the total over and the assertion
# sees 429s. Nothing was wrong with the endpoint or the test — the suite was
# simply not isolated, which is why it had never been runnable clean.
import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets():
    """Give every test a clean limiter, so ordering cannot decide the result."""
    try:
        from auth.rate_limit import _buckets, _lock
    except Exception:
        yield
        return
    with _lock:
        _buckets.clear()
    yield
    with _lock:
        _buckets.clear()
