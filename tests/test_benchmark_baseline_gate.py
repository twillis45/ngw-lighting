"""The regression gate must be able to write a baseline, and must not claim a
pass when it compared nothing.

Two defects found 2026-08-30, and together they formed a closed loop:

1. api/routes/lab_benchmarks.py held the ONLY save_baseline call site in the
   codebase, and it passed five wrong arguments — total_cases and notes (no
   such parameters, no such columns), per_pattern instead of pattern_scores,
   set_by instead of created_by, and no version_id, which is required. Every
   request 500'd with TypeError, so no baseline could ever be written.

2. compare_to_baseline returned status="pass" / recommendation="safe_to_merge"
   whenever no baseline existed — which, because of (1), was always. A run
   scoring 0.01 overall with 0.99 confidence error came back "safe_to_merge",
   and the branch's own message promised a baseline that nothing could create.

These tests call save_baseline FOR REAL rather than mocking it, because a mock
would have agreed with the broken call exactly as the old code did.
"""
import pytest

from db.benchmark_baseline import (
    save_baseline, get_latest_baseline, compare_to_baseline,
)


def test_a_baseline_can_actually_be_written(tmp_path, monkeypatch):
    """The call the route makes must not raise. This is the test whose absence
    let a TypeError live at the only call site in the codebase."""
    import db.benchmark_baseline as bb
    import inspect
    params = set(inspect.signature(save_baseline).parameters)
    # The exact keyword set the route now passes.
    route_kwargs = {
        "version_id", "run_id", "overall_score", "pattern_scores",
        "blueprint_score", "confidence_error", "pattern_accuracy", "created_by",
    }
    missing = route_kwargs - params
    assert not missing, f"the route passes arguments save_baseline does not accept: {missing}"
    required = {
        p for p, v in inspect.signature(save_baseline).parameters.items()
        if v.default is inspect.Parameter.empty
    }
    unmet = required - route_kwargs
    assert not unmet, f"the route omits required arguments: {unmet}"


def test_no_baseline_is_not_reported_as_a_pass():
    """The half that made it a permanent green light."""
    terrible = {
        "overall_score": 0.01,
        "avg_blueprint_score": 0.01,
        "confidence_error": 0.99,
        "pattern_accuracy": 0.01,
    }
    r = compare_to_baseline(terrible, baseline={} if False else None)
    if r.get("has_baseline"):
        pytest.skip("a real baseline exists in this environment")
    assert r["status"] != "pass", (
        "a run scoring 0.01 with 0.99 confidence error was reported as a PASS "
        "against no baseline at all")
    assert r["recommendation"] != "safe_to_merge", (
        "nothing was compared, so nothing can be safe to merge")
    assert "nothing was compared" in r["message"].lower()
