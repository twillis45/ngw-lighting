"""
Benchmark System v2 — CI Runner.

Called by POST /api/lab/benchmarks/ci-run.

Flow:
  1. Run full benchmark suite (reuses runner.run_benchmark)
  2. Compare result to active baseline (compare_to_baseline)
  3. Format structured CI output + GitHub PR comment
  4. Return exit_code: 0 (pass) or 1 (fail)

Output shape matches the spec exactly so GitHub Actions can parse it
with `jq` and scripts/post_pr_comment.py can format the PR comment.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_ci_benchmark(
    triggered_by: Optional[str] = "ci",
    commit_sha: Optional[str] = None,
    pr_number: Optional[str] = None,
    branch: Optional[str] = None,
    repo: Optional[str] = None,
    case_limit: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute the benchmark suite and compare to baseline.
    Returns a CI-structured result dict including PR comment markdown.
    """
    from engine.benchmark_v2.runner import run_benchmark
    from db.benchmark_baseline import compare_to_baseline

    started_at = time.time()
    meta = {
        "commit_sha": commit_sha,
        "pr_number":  pr_number,
        "branch":     branch,
        "repo":       repo,
    }

    # ── Run benchmark ──────────────────────────────────────────────────────────
    try:
        # case_limit and notes were accepted by the ROUTE and dropped here:
        # api/routes/lab_benchmarks.py passed both, this signature took
        # neither, and every call raised TypeError. It went unnoticed for
        # months because the route short-circuits on "no benchmark cases"
        # BEFORE reaching this line, and production had none — so the first
        # case ever seeded, on 2026-08-31, was also the first request to get
        # this far. run_benchmark below has always accepted case_limit.
        _ci_note = (
            f"CI run — sha={commit_sha or 'unknown'} "
            f"pr={pr_number or 'none'} branch={branch or 'unknown'}"
        )
        run_result = run_benchmark(
            run_type     = "ci",
            trigger      = "ci",
            triggered_by = triggered_by,
            case_limit   = case_limit,
            notes        = f"{_ci_note} — {notes}" if notes else _ci_note,
        )
    except Exception as exc:
        logger.exception("CI benchmark run failed with exception")
        duration = round(time.time() - started_at, 1)
        return _error_result(str(exc), meta, duration)

    # ── Compare to baseline ────────────────────────────────────────────────────
    comparison = compare_to_baseline(run_result)

    duration = round(time.time() - started_at, 1)

    # ── Build output ───────────────────────────────────────────────────────────
    status         = comparison["status"]
    regressions    = comparison.get("regressions", [])
    improvements   = comparison.get("improvements", [])

    result = {
        # CI decision fields (read by GitHub Actions)
        "status":           status,
        "recommendation":   comparison["recommendation"],
        "exit_code":        0 if status == "pass" else 1,

        # Scores
        "overall_score":    comparison["overall_score"],
        "delta":            comparison["delta"],
        "baseline_score":   comparison.get("baseline_score"),
        "blueprint_score":  comparison.get("blueprint_score"),
        "blueprint_delta":  comparison.get("blueprint_delta"),
        "confidence_error": comparison.get("confidence_error"),
        "confidence_delta": comparison.get("confidence_delta"),
        "pattern_accuracy": run_result.get("pattern_accuracy"),

        # Run metadata
        "run_id":           run_result.get("run_id"),
        "total_cases":      run_result.get("total_cases"),
        "passed_cases":     run_result.get("passed_cases"),
        "has_baseline":     comparison["has_baseline"],
        "baseline_version": comparison.get("baseline_version"),
        "duration_s":       duration,

        # Regression / improvement detail
        "regressions":  regressions,
        "improvements": improvements,
        "fail_reasons": comparison.get("fail_reasons", []),
        "insights":     run_result.get("insights", []),

        # Per-pattern breakdown
        "per_pattern": run_result.get("per_pattern", {}),

        # GitHub metadata (passed through)
        **meta,

        # Formatted PR comment (ready to POST to GitHub API)
        "pr_comment": _format_pr_comment(run_result, comparison, meta),
    }

    _log_summary(result)
    return result


# ── PR comment formatter ──────────────────────────────────────────────────────

def _format_pr_comment(
    run: Dict[str, Any],
    cmp: Dict[str, Any],
    meta: Dict[str, Any],
) -> str:
    """Build the GitHub PR comment markdown string."""
    status      = cmp["status"]
    regressions = cmp.get("regressions", [])
    improvements= cmp.get("improvements", [])
    has_baseline= cmp.get("has_baseline", False)
    overall     = cmp["overall_score"]
    delta       = cmp["delta"]
    prev        = cmp.get("baseline_score")
    commit_sha  = meta.get("commit_sha")
    run_id      = run.get("run_id", "unknown")

    lines: List[str] = []

    # ── Header ─────────────────────────────────────────────────────────────────
    # A run that evaluated NOTHING is not a pass, and this comment is what a
    # human actually reads on a PR. Fixed 2026-08-31: with the case_limit bug
    # resolved, a real run came back HTTP 200, status "pass", "Cases: 0/0
    # passed" and this comment saying "✅ Benchmark Passed / Safe to merge ✓".
    #
    # The machine-readable status had already been fixed in compare_to_baseline
    # that morning. This markdown builds its own strings and was missed — the
    # same fix has to be made everywhere the verdict is PHRASED, not just where
    # it is computed.
    _total_cases = run.get("total_cases") or 0
    if _total_cases == 0:
        lines += [
            "## ⚠️ Benchmark Measured Nothing",
            "",
            "**Not a pass.** Zero cases were evaluated, so this run says nothing "
            "about whether the engine regressed.",
            "",
            "Seed benchmark cases before treating this check as evidence.",
        ]
    elif status == "fail":
        lines += [
            "## ❌ Benchmark Regression Detected",
            "",
            "**🚫 Deployment Blocked** — fix regressions before merging.",
        ]
    else:
        lines += ["## ✅ Benchmark Passed"]
        if delta > 0.01:
            lines.append(f"**Score improved:** `+{delta:.1%}`")
        if improvements:
            lines.append(
                f"**{len(improvements)} improvement(s) detected.**"
            )
        if _total_cases:
            lines.append("**Safe to merge ✓**")

    lines += ["", "---", ""]

    # ── Score table ────────────────────────────────────────────────────────────
    if has_baseline and prev is not None:
        delta_str = f"`{'+' if delta >= 0 else ''}{delta:.1%}`"
        lines.append(
            f"**Overall Score:** `{prev:.3f}` → `{overall:.3f}` ({delta_str})"
        )
    else:
        lines.append(
            f"**Overall Score:** `{overall:.3f}` *(no baseline — first run establishes it)*"
        )

    if run.get("pattern_accuracy") is not None:
        lines.append(f"**Pattern Accuracy:** `{run['pattern_accuracy']:.1%}`")

    bp, bp_d = cmp.get("blueprint_score"), cmp.get("blueprint_delta", 0.0)
    if bp is not None:
        bp_str = f" (`{'+' if bp_d >= 0 else ''}{bp_d:.1%}`)" if has_baseline else ""
        lines.append(f"**Blueprint Score:** `{bp:.3f}`{bp_str}")

    ce, ce_d = cmp.get("confidence_error"), cmp.get("confidence_delta", 0.0)
    if ce is not None:
        ce_str = f" (`{'+' if ce_d >= 0 else ''}{ce_d:.3f}`)" if has_baseline else ""
        lines.append(f"**Confidence Error:** `{ce:.3f}`{ce_str}")

    passed = run.get("passed_cases", 0)
    total  = run.get("total_cases", 0)
    lines.append(f"**Cases:** `{passed}/{total}` passed")

    # ── Regressions ────────────────────────────────────────────────────────────
    if regressions:
        lines += ["", "### 🔴 Regressions", ""]
        for r in regressions:
            if r["type"] == "pattern":
                lines.append(
                    f"- **{r['pattern_id']}:** "
                    f"`{r['previous']:.3f}` → `{r['current']:.3f}` "
                    f"(`{r['delta']:+.1%}`)"
                )
            elif r["type"] in ("overall", "blueprint"):
                label = r["field"].replace("_", " ").title()
                lines.append(
                    f"- **{label}:** "
                    f"`{r['previous']:.3f}` → `{r['current']:.3f}` "
                    f"(`{r['delta']:+.1%}`)"
                )
            elif r["type"] == "confidence":
                lines.append(
                    f"- **Confidence Error:** "
                    f"`{r['previous']:.3f}` → `{r['current']:.3f}` "
                    f"(`+{r['delta']:.3f}`)"
                )

    # ── Improvements ───────────────────────────────────────────────────────────
    if improvements:
        lines += ["", "### 🟢 Improvements", ""]
        for imp in improvements[:5]:
            if imp["type"] == "pattern":
                lines.append(
                    f"- **{imp['pattern_id']}:** "
                    f"`{imp['previous']:.3f}` → `{imp['current']:.3f}` "
                    f"(`{imp['delta']:+.1%}`)"
                )
            elif imp["type"] in ("overall", "blueprint"):
                label = imp["field"].replace("_", " ").title()
                lines.append(
                    f"- **{label}:** "
                    f"`{imp['previous']:.3f}` → `{imp['current']:.3f}` "
                    f"(`{imp['delta']:+.1%}`)"
                )

    # ── Insights ────────────────────────────────────────────────────────────────
    insights = [
        i for i in run.get("insights", [])
        if i != "No significant failure patterns detected in this run."
    ]
    if insights:
        lines += ["", "### 🔍 Insights", ""]
        for i in insights[:4]:
            lines.append(f"- {i}")

    # ── Footer ──────────────────────────────────────────────────────────────────
    lines += ["", "---", ""]
    if commit_sha:
        lines.append(f"*Commit: `{commit_sha[:8]}`* &nbsp;·&nbsp; ")
    lines.append(f"*Run: `{run_id[:8]}`* &nbsp;·&nbsp; *[NGW Benchmark CI](../../actions)*")

    return "\n".join(lines)


def _format_error_comment(error: str) -> str:
    return "\n".join([
        "## ❌ Benchmark Run Failed",
        "",
        "**🚫 Deployment Blocked** — benchmark suite could not complete.",
        "",
        f"**Error:** `{error}`",
        "",
        "*Fix the error and re-push to unblock.*",
    ])


def _error_result(
    error: str, meta: Dict[str, Any], duration: float
) -> Dict[str, Any]:
    return {
        "status":          "fail",
        "recommendation":  "block_deploy",
        "exit_code":       1,
        "error":           error,
        "overall_score":   0.0,
        "delta":           0.0,
        "regressions":     [],
        "improvements":    [],
        "fail_reasons":    ["run_error"],
        "duration_s":      duration,
        "pr_comment":      _format_error_comment(error),
        **meta,
    }


def _log_summary(result: Dict[str, Any]) -> None:
    regs = result.get("regressions", [])
    imps = result.get("improvements", [])
    logger.info(
        "CI benchmark complete: status=%s score=%.3f delta=%+.3f "
        "regressions=%d improvements=%d duration=%.1fs",
        result["status"],
        result["overall_score"],
        result["delta"],
        len(regs), len(imps),
        result["duration_s"],
    )
    for r in regs:
        logger.warning("  REGRESSION %s: %+.1%%", r.get("pattern_id") or r.get("field"), r["delta"])
