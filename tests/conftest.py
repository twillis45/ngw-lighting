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

# ── No live VLM calls from the suite ─────────────────────────────────────────
# Measured 2026-09-03 by blocking outbound sockets for a whole run: the suite
# made 492 connection attempts to api.openai.com (162.159.140.245 /
# 172.66.0.243). engine/vlm.py probes https://api.openai.com/v1/models on app
# startup, and every TestClient(app) construction triggers it; paid completions
# go to the same host through the SDK, so the endpoint mix was not knowable
# from the outside.
#
# ZERO tests failed with all outbound traffic blocked -- nothing in the suite
# depends on a live provider. So the calls bought nothing and cost latency, a
# live key on the wire on every run, and an unquantified billing risk.
#
# vlm_available() is keyed purely on the env var being non-empty, so clearing
# it here is the whole fix. Tests that exercise the configured path supply
# their own fake key (see tests/test_vlm.py::TestVLMAvailable, which patches in
# "sk-test"), and that still works because patch.dict sets it locally.
for _k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[_k] = ""


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
def _reset_analysis_counts():
    """Give every test a clean free-tier quota.

    Added 2026-09-02 with the paywall fix. /recommend now increments the
    analysis count server-side — it has to, because the count previously only
    rose when the browser volunteered it, which made the free tier opt-in. But
    the counts live in a shared table, so without this a test's result depends
    on how many /recommend calls ran before it: TestRecommendErrors started
    seeing 402 instead of 422 purely because earlier tests had used the quota.

    Same disease as the rate-limit buckets below, and the same fix.
    """
    def _clear():
        try:
            from db.database import get_db
            with get_db() as conn:
                conn.execute("DELETE FROM session_analysis_counts")
        except Exception:
            pass  # table may not exist yet on a fresh DB
    _clear()
    yield
    _clear()


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
