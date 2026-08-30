"""
Benchmark System v2 — API routes.

Mounted under /api/lab/benchmarks via main.py.
Most endpoints require dev authentication (get_dev_user).
CI/baseline endpoints accept either a dev JWT or X-CI-Secret header (get_ci_or_dev_user).

Routes:
  GET  /api/lab/benchmarks/cases                    — list cases
  POST /api/lab/benchmarks/cases                    — create case
  GET  /api/lab/benchmarks/cases/{id}               — get case
  PUT  /api/lab/benchmarks/cases/{id}               — update case
  DEL  /api/lab/benchmarks/cases/{id}               — delete case
  GET  /api/lab/benchmarks/cases/{id}/history       — score history

  POST /api/lab/benchmarks/cases/from-gold-set/{id} — promote gold set → case

  POST /api/lab/benchmarks/run                      — trigger a manual run
  POST /api/lab/benchmarks/ci-run                   — CI-triggered run (X-CI-Secret or dev JWT)
  GET  /api/lab/benchmarks/runs                     — list runs
  GET  /api/lab/benchmarks/runs/{id}                — run detail
  GET  /api/lab/benchmarks/runs/{id}/results        — per-case results

  GET  /api/lab/benchmarks/pattern-metrics          — pattern performance table
  GET  /api/lab/benchmarks/summary                  — latest run summary for dashboard

  GET  /api/lab/benchmarks/baseline                 — current active baseline
  GET  /api/lab/benchmarks/baseline/history         — all stored baselines
  POST /api/lab/benchmarks/update-baseline          — promote latest passed run to baseline
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth.ci_guard import get_ci_or_dev_user
from auth.dev_guard import get_dev_user
from db.benchmark import (
    get_benchmark_cases, get_benchmark_case,
    create_benchmark_case, update_benchmark_case, delete_benchmark_case,
    get_benchmark_runs, get_benchmark_run,
    get_run_results, get_case_history,
    get_pattern_metrics, get_last_n_run_scores,
)

from engine.constants import ENGINE_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmarks", tags=["lab-benchmarks"])


# ── Request models ─────────────────────────────────────────────────────────────

class BenchmarkCaseCreate(BaseModel):
    pattern_id:         str
    image_path:         str
    difficulty:         str                  = "medium"
    environment_tags:   List[str]            = Field(default_factory=list)
    expected_analysis:  Dict[str, Any]       = Field(default_factory=dict)
    expected_blueprint: Dict[str, Any]       = Field(default_factory=dict)
    expected_fixes:     List[str]            = Field(default_factory=list)
    source_gold_set_id: Optional[str]        = None
    notes:              Optional[str]        = None


class BenchmarkCaseUpdate(BaseModel):
    pattern_id:         Optional[str]              = None
    difficulty:         Optional[str]              = None
    environment_tags:   Optional[List[str]]        = None
    expected_analysis:  Optional[Dict[str, Any]]   = None
    expected_blueprint: Optional[Dict[str, Any]]   = None
    expected_fixes:     Optional[List[str]]        = None
    notes:              Optional[str]              = None


class RunBenchmarkRequest(BaseModel):
    run_type:   str            = "manual"   # manual | ci | nightly
    trigger:    str            = "manual"   # manual | model_update | rule_change | scheduled
    case_limit: Optional[int]  = None
    notes:      Optional[str]  = None


class CIRunRequest(BaseModel):
    commit_sha: Optional[str] = None
    pr_number:  Optional[int] = None
    branch:     Optional[str] = None
    repo:       Optional[str] = None
    case_limit: Optional[int] = None
    notes:      Optional[str] = None


class UpdateBaselineRequest(BaseModel):
    notes: Optional[str] = None


# ── Cases ──────────────────────────────────────────────────────────────────────

@router.get("/cases")
async def list_cases(
    pattern_id: Optional[str] = Query(None),
    difficulty:  Optional[str] = Query(None),
    limit:       int           = Query(100, ge=1, le=500),
    user: Dict = Depends(get_dev_user),
):
    return {"cases": get_benchmark_cases(pattern_id=pattern_id, difficulty=difficulty, limit=limit)}


@router.get("/cases/{case_id}")
async def get_case(case_id: str, user: Dict = Depends(get_dev_user)):
    case = get_benchmark_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Benchmark case not found")
    return case


@router.get("/cases/{case_id}/image")
async def get_case_image(case_id: str, user: Dict = Depends(get_dev_user)):
    """Serve the image file for a benchmark case."""
    from pathlib import Path
    from fastapi.responses import FileResponse
    case = get_benchmark_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Benchmark case not found")
    image_path = Path(case.get("image_path", ""))
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    suffix = image_path.suffix.lower()
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".png": "image/png", ".webp": "image/webp",
                  ".heic": "image/heic"}.get(suffix, "image/jpeg")
    return FileResponse(str(image_path), media_type=media_type)


@router.post("/cases", status_code=201)
async def create_case(body: BenchmarkCaseCreate, user: Dict = Depends(get_dev_user)):
    return create_benchmark_case(
        pattern_id        = body.pattern_id,
        image_path        = body.image_path,
        expected_analysis = body.expected_analysis,
        expected_blueprint= body.expected_blueprint,
        expected_fixes    = body.expected_fixes,
        difficulty        = body.difficulty,
        environment_tags  = body.environment_tags,
        source_gold_set_id= body.source_gold_set_id,
        notes             = body.notes,
        created_by        = user.get("email"),
    )


@router.put("/cases/{case_id}")
async def update_case(case_id: str, body: BenchmarkCaseUpdate, user: Dict = Depends(get_dev_user)):
    if not get_benchmark_case(case_id):
        raise HTTPException(status_code=404, detail="Benchmark case not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return update_benchmark_case(case_id, **updates)


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(case_id: str, user: Dict = Depends(get_dev_user)):
    if not delete_benchmark_case(case_id):
        raise HTTPException(status_code=404, detail="Benchmark case not found")


@router.get("/cases/{case_id}/history")
async def case_history(
    case_id: str,
    limit:   int = Query(10, ge=1, le=50),
    user: Dict = Depends(get_dev_user),
):
    """Per-case score history across runs."""
    return {"case_id": case_id, "history": get_case_history(case_id, limit=limit)}


# ── Promote from Gold Set ──────────────────────────────────────────────────────

@router.post("/cases/from-gold-set/{entry_id}", status_code=201)
async def promote_from_gold_set(
    entry_id:   str,
    difficulty: str = Query("medium"),
    user: Dict = Depends(get_dev_user),
):
    """
    Promote an approved gold set entry into a benchmark case.
    Copies image_path and expected_analysis; infers pattern_id from metadata.
    """
    from db.database import get_gold_set_entry

    entry = get_gold_set_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Gold set entry not found")

    expected_analysis = entry.get("expected_analysis") or {}
    pattern_id = (
        expected_analysis.get("expected_pattern")
        or expected_analysis.get("lighting_family")
        or expected_analysis.get("pattern_id")
        or "unknown"
    )

    # Build blueprint from analysis fields if present
    expected_blueprint: Dict[str, Any] = {}
    for role in ("key_light", "fill_light", "rim_light"):
        short = role.replace("_light", "")
        if role in expected_analysis:
            expected_blueprint[short] = expected_analysis[role]

    return create_benchmark_case(
        pattern_id         = pattern_id,
        image_path         = entry["image_path"],
        expected_analysis  = expected_analysis,
        expected_blueprint = expected_blueprint,
        difficulty         = difficulty,
        source_gold_set_id = entry_id,
        notes              = f"Promoted from gold set entry {entry_id}",
        created_by         = user.get("email"),
    )


# ── Runs ───────────────────────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    user: Dict = Depends(get_dev_user),
):
    return {"runs": get_benchmark_runs(limit=limit)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: Dict = Depends(get_dev_user)):
    run = get_benchmark_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    return run


@router.get("/runs/{run_id}/results")
async def run_results(run_id: str, user: Dict = Depends(get_dev_user)):
    """All per-case scores for a run, sorted worst-first."""
    if not get_benchmark_run(run_id):
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    return {"run_id": run_id, "results": get_run_results(run_id)}


# ── Trigger run ────────────────────────────────────────────────────────────────

@router.post("/run")
async def trigger_run(body: RunBenchmarkRequest, user: Dict = Depends(get_dev_user)):
    """
    Trigger a synchronous benchmark run.
    Returns full results including per-pattern scores and regression alerts.
    """
    from db.benchmark import get_benchmark_cases as _count_cases
    from engine.benchmark_v2.runner import run_benchmark

    if not _count_cases(limit=1):
        return {
            "status":  "no_cases",
            "message": (
                "No benchmark cases found. "
                "Create via POST /api/lab/benchmarks/cases "
                "or promote from gold set via POST /api/lab/benchmarks/cases/from-gold-set/{id}."
            ),
        }

    try:
        return run_benchmark(
            run_type    = body.run_type,
            trigger     = body.trigger,
            triggered_by= user.get("email"),
            case_limit  = body.case_limit,
            notes       = body.notes,
        )
    except Exception as exc:
        logger.exception("Benchmark run failed")
        raise HTTPException(status_code=500, detail=f"Benchmark run failed: {exc}")


# ── CI-triggered run ───────────────────────────────────────────────────────────

@router.post("/ci-run")
async def ci_run(body: CIRunRequest, user: Dict = Depends(get_ci_or_dev_user)):
    """
    CI-triggered benchmark run.  Accepts X-CI-Secret header (for GitHub Actions)
    or a standard dev JWT.  Returns structured pass/fail with exit_code for shell.
    """
    from db.benchmark import get_benchmark_cases as _count_cases
    from engine.benchmark_v2.ci_runner import run_ci_benchmark

    if not _count_cases(limit=1):
        return {
            "status":    "no_cases",
            "exit_code": 0,
            "message":   (
                "No benchmark cases found — skipping CI evaluation. "
                "Create cases via POST /api/lab/benchmarks/cases "
                "or promote from gold set via POST /api/lab/benchmarks/cases/from-gold-set/{id}."
            ),
        }

    try:
        return run_ci_benchmark(
            triggered_by = user.get("email") or user.get("id", "ci"),
            commit_sha   = body.commit_sha,
            pr_number    = body.pr_number,
            branch       = body.branch,
            repo         = body.repo,
            case_limit   = body.case_limit,
            notes        = body.notes,
        )
    except Exception as exc:
        logger.exception("CI benchmark run failed")
        raise HTTPException(status_code=500, detail=f"CI benchmark run failed: {exc}")


# ── Baseline management ────────────────────────────────────────────────────────

@router.get("/baseline")
async def get_baseline(user: Dict = Depends(get_ci_or_dev_user)):
    """Return the current active baseline (scores used for regression comparison)."""
    from db.benchmark_baseline import get_latest_baseline
    baseline = get_latest_baseline()
    if not baseline:
        return {"has_baseline": False, "message": "No baseline set yet."}
    return {"has_baseline": True, "baseline": baseline}


@router.get("/baseline/history")
async def baseline_history(
    limit: int = Query(20, ge=1, le=100),
    user: Dict = Depends(get_dev_user),
):
    """Full history of all stored baselines, newest first."""
    from db.benchmark_baseline import get_baseline_history
    return {"baselines": get_baseline_history(limit=limit)}


@router.post("/update-baseline")
async def update_baseline(
    body: UpdateBaselineRequest,
    user: Dict = Depends(get_ci_or_dev_user),
):
    """
    Promote the latest completed run to the active baseline.
    Only succeeds when the most recent run has status='completed' (not 'failed' or 'blocked').
    Intended to be called automatically by CI after a passing merge to main.
    """
    from db.benchmark import get_benchmark_runs
    from db.benchmark_baseline import save_baseline

    runs = get_benchmark_runs(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="No benchmark runs found to promote.")

    latest = runs[0]
    if latest.get("status") not in ("completed",):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Latest run has status='{latest.get('status')}'. "
                "Only a 'completed' run can be promoted to baseline."
            ),
        )

    # This call was wrong in five ways and had NEVER succeeded — it is the only
    # save_baseline call site in the codebase, so no baseline could ever be
    # written, and compare_to_baseline returns "safe_to_merge" unconditionally
    # when no baseline exists. The regression gate was a permanent green light:
    # a run scoring 0.01 overall with 0.99 confidence error was reported safe.
    #
    # It passed total_cases and notes (no such parameters, and no columns for
    # them), per_pattern instead of pattern_scores, set_by instead of
    # created_by, and omitted the REQUIRED version_id. Every request 500'd with
    # TypeError. Fixed 2026-08-30 and covered by a test that calls it for real
    # rather than mocking it.
    per_pattern = {
        m["pattern_id"]: m.get("benchmark_score", 0.0)
        for m in (get_pattern_metrics() or [])
        if m.get("pattern_id")
    }
    baseline = save_baseline(
        version_id      = f"{ENGINE_VERSION}+{latest['id'][:8]}",
        run_id          = latest["id"],
        overall_score   = latest.get("overall_score") or 0.0,
        pattern_scores  = per_pattern,
        blueprint_score = latest.get("avg_blueprint_score") or 0.0,
        confidence_error= latest.get("confidence_error") or 0.0,
        pattern_accuracy= latest.get("pattern_accuracy") or 0.0,
        created_by      = user.get("email") or user.get("id", "ci"),
    )
    if body.notes:
        # The baseline table has no notes column. Logged rather than silently
        # dropped, so the caller's note is not simply lost.
        logger.info("[baseline] promoted run %s — note: %s", latest["id"], body.notes)
    return {"status": "ok", "baseline": baseline}


# ── Pattern metrics ────────────────────────────────────────────────────────────

@router.get("/pattern-metrics")
async def pattern_metrics(
    pattern_id: Optional[str] = Query(None),
    user: Dict = Depends(get_dev_user),
):
    """
    Per-pattern aggregated performance.
    Enriched with delta_change vs the previous run.
    """
    metrics = get_pattern_metrics(pattern_id=pattern_id)

    # Compute delta vs previous run
    runs = get_benchmark_runs(limit=2)
    delta_map: Dict[str, float] = {}
    if len(runs) >= 2:
        def _avg_by_pattern(results):
            from collections import defaultdict
            g: Dict[str, List[float]] = defaultdict(list)
            for r in results:
                pid = r.get("pattern_id", "unknown")
                g[pid].append(r.get("final_score", 0.0))
            return {k: sum(v) / len(v) for k, v in g.items()}

        cur  = _avg_by_pattern(get_run_results(runs[0]["id"]))
        prev = _avg_by_pattern(get_run_results(runs[1]["id"]))
        for pid in cur:
            if pid in prev:
                delta_map[pid] = cur[pid] - prev[pid]

    for m in metrics:
        m["delta_change"] = delta_map.get(m["pattern_id"])

    return {"metrics": metrics}


# ── Dashboard summary ──────────────────────────────────────────────────────────

@router.get("/summary")
async def dashboard_summary(user: Dict = Depends(get_dev_user)):
    """
    Compact summary of the latest benchmark run for the dashboard header.
    Returns overall score, trend, pass/fail status, and top regressions.
    """
    runs = get_benchmark_runs(limit=1)
    if not runs:
        return {
            "has_runs": False,
            "message":  "No benchmark runs yet. Trigger one via POST /api/lab/benchmarks/run",
        }

    latest = runs[0]
    trend  = get_last_n_run_scores(5)
    metrics = get_pattern_metrics()

    # Surface regressions and compute verdict breakdown
    results = get_run_results(latest["id"])
    regression_cases = [r for r in results if r.get("regression_flag")]
    # Accurate PASS/SOFT/FAIL counts matching CaseExplorer verdict thresholds
    # (UI uses 0.80/0.60 cutoffs, not the runner's 0.70 PASS_THRESHOLD)
    ui_passed = sum(1 for r in results if r.get("final_score") is not None and r["final_score"] >= 0.8)
    ui_soft = sum(1 for r in results if r.get("final_score") is not None and 0.6 <= r["final_score"] < 0.8)

    return {
        "has_runs":           True,
        "run_id":             latest["id"],
        "status":             latest["status"],
        "overall_score":      latest.get("overall_score"),
        "pattern_accuracy":   latest.get("pattern_accuracy"),
        "avg_blueprint_score": latest.get("avg_blueprint_score"),
        "confidence_error":   latest.get("confidence_error"),
        "total_cases":        latest.get("total_cases"),
        "passed_cases":       ui_passed,
        "soft_passed_cases":  ui_soft,
        "regression_count":   latest.get("regression_count"),
        "started_at":         latest.get("started_at"),
        "completed_at":       latest.get("completed_at"),
        "trend":              trend,
        "pattern_count":      len(metrics),
        "regression_cases":   len(regression_cases),
    }


@router.post("/drift-check")
async def trigger_drift_check(user: Dict = Depends(get_dev_user)):
    """
    Trigger a nightly-style drift detection run from the Lab UI.
    Runs a full benchmark, compares to baseline, creates Candidates for drift items.
    Same logic as the nightly GitHub Actions job — looser thresholds than CI.
    """
    from engine.benchmark_v2.nightly import run_nightly_check
    try:
        return run_nightly_check(triggered_by=user.get("email", "lab:manual"))
    except Exception as exc:
        logger.exception("Lab drift check failed")
        raise HTTPException(status_code=500, detail=f"Drift check failed: {exc}")


@router.get("/drift-config")
async def get_drift_config(user: Dict = Depends(get_dev_user)):
    """
    Return current drift check schedule and threshold configuration.
    Schedule is driven by GitHub Actions (.github/workflows/nightly.yml).
    Thresholds are defined in engine/benchmark_v2/nightly.py.
    """
    from engine.benchmark_v2.nightly import DRIFT_OVERALL, DRIFT_PATTERN, DRIFT_CONFIDENCE

    return {
        "schedule": {
            "cron":        "0 2 * * *",
            "description": "Daily at 02:00 UTC",
            "timezone":    "UTC",
        },
        "thresholds": {
            "overall":    DRIFT_OVERALL,
            "pattern":    DRIFT_PATTERN,
            "confidence": DRIFT_CONFIDENCE,
        },
        "notes": (
            "Schedule is configured in .github/workflows/nightly.yml. "
            "Thresholds are looser than CI — used for trend detection only, not blocking."
        ),
    }


# ── Confusion Matrix ─────────────────────────────────────────────────────────

@router.get("/confusion-matrix")
async def confusion_matrix(
    run_id: Optional[str] = Query(None, description="Specific run ID, or latest if omitted"),
    user: Dict = Depends(get_dev_user),
):
    """Build a confusion matrix from benchmark results — expected vs predicted pattern."""
    from db.database import get_db

    # Resolve run_id
    if not run_id:
        runs = get_benchmark_runs(limit=1)
        if not runs:
            return {"matrix": {}, "patterns": [], "total": 0, "message": "No benchmark runs found"}
        run_id = runs[0]["id"]

    run = get_benchmark_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Benchmark run not found")

    results = get_run_results(run_id)
    cases = {c["id"]: c for c in get_benchmark_cases(limit=500)}

    # Build matrix: matrix[expected][predicted] = count
    matrix: Dict[str, Dict[str, int]] = {}
    mismatches = []
    for r in results:
        case = cases.get(r["case_id"])
        if not case:
            continue
        expected = case.get("pattern_id", "unknown")
        predicted = r.get("predicted_pattern", "unknown") or "unknown"
        matrix.setdefault(expected, {})
        matrix[expected][predicted] = matrix[expected].get(predicted, 0) + 1
        if expected != predicted:
            mismatches.append({
                "case_id": r["case_id"],
                "expected": expected,
                "predicted": predicted,
                "image_path": case.get("image_path"),
                "confidence_score": r.get("confidence_score"),
            })

    patterns = sorted(set(list(matrix.keys()) + [p for row in matrix.values() for p in row.keys()]))

    return {
        "run_id": run_id,
        "patterns": patterns,
        "matrix": matrix,
        "mismatches": mismatches[:50],
        "total": len(results),
    }
