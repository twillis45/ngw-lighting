"""Global pytest configuration — sets required env vars before any app import."""
import os
from pathlib import Path

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
# CONFIRMED 2026-09-03: a full run under the same socket blocker, with this
# guard in place, made ZERO outbound attempts (492 -> 0) and still had zero
# failures. The earlier commit recorded this as unsettled because the first
# red-proof was inconclusive -- it used test_api.py, which turns out to make no
# outbound calls either way, so it showed 0 before and 0 after and proved
# nothing.
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


# ── The schema has to exist, and nothing was creating it ─────────────────────
# Found 2026-09-08, the first time this suite ever ran in CI. 19 tests failed
# with `sqlite3.OperationalError: no such table: admin_changelog` (also
# image_ground_truth, feedback_aggregates, benchmark_baselines) and
# `table gold_set_entries has no column named setup_family`.
#
# WHY IT PASSED FOR FIVE MONTHS ON ONE MACHINE. main.py creates every table in
# its startup handler. But `TestClient(app)` built at MODULE level — which
# test_admin.py, test_lab.py and others do — never fires that handler; only
# `with TestClient(app)` does. So the suite never created the schema. It
# passed anyway wherever data/ngw_users.db already existed from having RUN the
# app, and failed on any fresh checkout. Deleting the local db reproduces all
# 19 immediately.
#
# That is the same defect as a test asserting a path only one laptop has, and
# it stayed invisible because CI could not start: tests.yml installed no
# pytest, so nothing ever ran these on a clean disk.
#
# This mirrors main.py's startup block rather than inventing a fixture schema —
# a test-only CREATE TABLE would drift from production silently, which is the
# failure one layer along.
@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    from db.database import init_db
    from db.benchmark import init_benchmark_tables
    from db.benchmark_baseline import init_baseline_tables
    from db.signals import init_signals_tables, seed_signals
    from db.experiments import init_experiments_tables

    Path("data").mkdir(parents=True, exist_ok=True)
    init_db()
    init_benchmark_tables()
    init_baseline_tables()
    init_signals_tables()
    seed_signals()          # no-op if rows already exist
    init_experiments_tables()


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
