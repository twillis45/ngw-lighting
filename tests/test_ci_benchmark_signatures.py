"""Every call across the CI benchmark chain must match the signature it calls.

Three signature mismatches have now been found in this one chain, all invisible
for months because an earlier guard short-circuited before reaching them:

  1. save_baseline(...)      — five wrong arguments at the ONLY call site, so no
     baseline could ever be written. Found 2026-08-30.
  2. compare_to_baseline     — returned safe_to_merge whenever no baseline
     existed, which because of (1) was always. Found 2026-08-30.
  3. run_ci_benchmark(...)   — the route passed case_limit and notes; the
     function accepted neither. Found 2026-08-31, by the first benchmark case
     ever seeded into production, which was also the first request to get past
     the "no cases" guard.

The pattern is the point: a chain guarded by early returns hides every defect
downstream of the guard. These tests compare signatures directly, so a mismatch
fails without needing the whole chain to run.
"""
import inspect

from db.benchmark_baseline import save_baseline
from engine.benchmark_v2.ci_runner import run_ci_benchmark
from engine.benchmark_v2.runner import run_benchmark


def _params(fn):
    return set(inspect.signature(fn).parameters)


def _required(fn):
    return {p for p, v in inspect.signature(fn).parameters.items()
            if v.default is inspect.Parameter.empty}


def test_route_to_run_ci_benchmark():
    """api/routes/lab_benchmarks.py ci_run passes exactly these."""
    passed = {"triggered_by", "commit_sha", "pr_number", "branch", "repo",
              "case_limit", "notes"}
    missing = passed - _params(run_ci_benchmark)
    assert not missing, f"run_ci_benchmark does not accept: {missing}"


def test_run_ci_benchmark_to_run_benchmark():
    """The middle layer must be able to forward what it was given."""
    forwarded = {"run_type", "trigger", "triggered_by", "case_limit", "notes"}
    missing = forwarded - _params(run_benchmark)
    assert not missing, f"run_benchmark does not accept: {missing}"


def test_case_limit_is_not_silently_dropped():
    """It was accepted by the route and never reached the runner."""
    assert "case_limit" in _params(run_ci_benchmark)
    src = inspect.getsource(run_ci_benchmark)
    assert "case_limit   = case_limit" in src or "case_limit=case_limit" in src, (
        "run_ci_benchmark accepts case_limit but never forwards it")


def test_route_to_save_baseline():
    passed = {"version_id", "run_id", "overall_score", "pattern_scores",
              "blueprint_score", "confidence_error", "pattern_accuracy",
              "created_by"}
    missing = passed - _params(save_baseline)
    assert not missing, f"save_baseline does not accept: {missing}"
    unmet = _required(save_baseline) - passed
    assert not unmet, f"the route omits required arguments: {unmet}"
