"""
Benchmark System v2 — Baseline storage and regression comparison.

The baseline is the last known-good performance record.
It is ONLY updated when:
  1. A CI run passes (no regressions detected)
  2. The change has been merged to main (via POST /update-baseline)

Schema: benchmark_baselines
  - One active row at a time (is_active = 1)
  - Full history retained for trend analysis

Regression thresholds (hard-coded per spec):
  overall_score   drop  > 3%   → FAIL
  any pattern     drop  > 5%   → FAIL
  confidence_error increase > 0.05 → FAIL
  blueprint_score drop  > 5%   → FAIL
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS benchmark_baselines (
        id                TEXT PRIMARY KEY,
        version_id        TEXT NOT NULL,
        overall_score     REAL NOT NULL,
        pattern_scores    TEXT NOT NULL DEFAULT '{}',
        blueprint_score   REAL NOT NULL DEFAULT 0.0,
        confidence_error  REAL NOT NULL DEFAULT 0.0,
        pattern_accuracy  REAL NOT NULL DEFAULT 0.0,
        run_id            TEXT,
        commit_sha        TEXT,
        branch            TEXT,
        created_by        TEXT,
        created_at        REAL NOT NULL,
        is_active         INTEGER DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_baselines_active  ON benchmark_baselines(is_active);
    CREATE INDEX IF NOT EXISTS idx_baselines_created ON benchmark_baselines(created_at DESC);
"""

# ── Regression thresholds ─────────────────────────────────────────────────────

THRESHOLD_OVERALL     = 0.03   # 3%   overall drop  → fail
THRESHOLD_PATTERN     = 0.05   # 5%   per-pattern   → fail
THRESHOLD_BLUEPRINT   = 0.05   # 5%   blueprint     → fail
THRESHOLD_CONFIDENCE  = 0.05   # +0.05 conf increase → fail


def init_baseline_tables() -> None:
    """Idempotent: create baseline table if not exists."""
    with get_db() as conn:
        conn.executescript(_SCHEMA)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_baseline(
    version_id: str,
    overall_score: float,
    pattern_scores: Dict[str, float],
    blueprint_score: float,
    confidence_error: float,
    pattern_accuracy: float = 0.0,
    run_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
    branch: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save a new baseline and deactivate all previous ones.
    Returns the new active baseline.
    """
    bid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute("UPDATE benchmark_baselines SET is_active = 0")
        conn.execute(
            """INSERT INTO benchmark_baselines
               (id, version_id, overall_score, pattern_scores, blueprint_score,
                confidence_error, pattern_accuracy, run_id, commit_sha, branch,
                created_by, created_at, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (bid, version_id, overall_score, json.dumps(pattern_scores),
             blueprint_score, confidence_error, pattern_accuracy,
             run_id, commit_sha, branch, created_by, now),
        )
    return get_latest_baseline()  # type: ignore[return-value]


def get_latest_baseline() -> Optional[Dict[str, Any]]:
    """Return the active baseline, falling back to most recent if none active."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM benchmark_baselines
               WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM benchmark_baselines ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    return _deser(row) if row else None


def get_baseline_history(limit: int = 20) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM benchmark_baselines ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_deser(r) for r in rows]


def _deser(row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("pattern_scores"):
        try:
            d["pattern_scores"] = json.loads(d["pattern_scores"])
        except Exception:
            d["pattern_scores"] = {}
    d["is_active"] = bool(d.get("is_active"))
    return d


# ── Core comparison logic ─────────────────────────────────────────────────────

def compare_to_baseline(
    run_result: Dict[str, Any],
    baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compare a completed run result against the active baseline.

    Returns a structured comparison dict with:
      - status:         "pass" | "fail"
      - recommendation: "safe_to_merge" | "block_deploy"
      - regressions:    list of regression dicts
      - improvements:   list of improvement dicts
      - delta:          overall score change (signed)
      - fail_reasons:   list of failure cause strings
    """
    if baseline is None:
        baseline = get_latest_baseline()

    # No baseline yet — NOTHING WAS COMPARED, and this must not read as a pass.
    #
    # Until 2026-08-30 this returned status="pass" and
    # recommendation="safe_to_merge", which is a verdict about a comparison
    # that did not happen. It was not a harmless default either: the only
    # save_baseline call site in the codebase raised TypeError on every
    # request, so no baseline could ever exist and this branch was the ONLY
    # branch. The regression gate green-lit everything — a run scoring 0.01
    # overall with 0.99 confidence error came back "safe_to_merge".
    #
    # The writer is fixed, so this branch is now genuinely the first-run case.
    # It still refuses to call itself a pass: "no_baseline" cannot be mistaken
    # for one by a human or by a script checking == "pass".
    if baseline is None:
        return {
            "has_baseline":   False,
            "status":         "no_baseline",
            "recommendation": "no_baseline",
            "overall_score":  run_result.get("overall_score", 0.0),
            "delta":          0.0,
            "baseline_score": None,
            "blueprint_score":  run_result.get("avg_blueprint_score", 0.0),
            "blueprint_delta":  0.0,
            "confidence_error": run_result.get("confidence_error", 0.0),
            "confidence_delta": 0.0,
            "regressions":    [],
            "improvements":   [],
            "fail_reasons":   [],
            "message":        ("No baseline exists, so nothing was compared. "
                               "Promote this run to establish the first baseline."),
        }

    cur_overall    = run_result.get("overall_score", 0.0)
    prev_overall   = baseline.get("overall_score", 0.0)
    cur_blueprint  = run_result.get("avg_blueprint_score", 0.0)
    prev_blueprint = baseline.get("blueprint_score", 0.0)
    cur_conf       = run_result.get("confidence_error", 0.0)
    prev_conf      = baseline.get("confidence_error", 0.0)
    cur_patterns   = run_result.get("per_pattern", {})
    prev_patterns  = baseline.get("pattern_scores", {})

    regressions: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []
    fail_reasons: List[str] = []

    # 1. Overall score
    overall_delta = cur_overall - prev_overall
    if overall_delta < -THRESHOLD_OVERALL:
        regressions.append({
            "type":     "overall",
            "field":    "overall_score",
            "previous": round(prev_overall, 4),
            "current":  round(cur_overall, 4),
            "delta":    round(overall_delta, 4),
            "severity": "critical",
            "reason":   (
                f"Overall score dropped {abs(overall_delta):.1%} "
                f"(threshold: {THRESHOLD_OVERALL:.0%})"
            ),
        })
        fail_reasons.append("overall_regression")
    elif overall_delta > 0.01:
        improvements.append({
            "type": "overall", "field": "overall_score",
            "previous": round(prev_overall, 4), "current": round(cur_overall, 4),
            "delta": round(overall_delta, 4),
        })

    # 2. Blueprint score
    bp_delta = cur_blueprint - prev_blueprint
    if bp_delta < -THRESHOLD_BLUEPRINT:
        regressions.append({
            "type":     "blueprint",
            "field":    "blueprint_score",
            "previous": round(prev_blueprint, 4),
            "current":  round(cur_blueprint, 4),
            "delta":    round(bp_delta, 4),
            "severity": "critical",
            "reason":   (
                f"Blueprint score dropped {abs(bp_delta):.1%} "
                f"(threshold: {THRESHOLD_BLUEPRINT:.0%})"
            ),
        })
        fail_reasons.append("blueprint_regression")
    elif bp_delta > 0.02:
        improvements.append({
            "type": "blueprint", "field": "blueprint_score",
            "previous": round(prev_blueprint, 4), "current": round(cur_blueprint, 4),
            "delta": round(bp_delta, 4),
        })

    # 3. Per-pattern scores
    for pid, cur_score in cur_patterns.items():
        prev_score = prev_patterns.get(pid)
        if prev_score is None:
            continue  # new pattern — skip (can't regress what wasn't tracked)
        delta = cur_score - prev_score
        if delta < -THRESHOLD_PATTERN:
            regressions.append({
                "type":       "pattern",
                "pattern_id": pid,
                "previous":   round(prev_score, 4),
                "current":    round(cur_score, 4),
                "delta":      round(delta, 4),
                "severity":   "critical",
                "reason":     (
                    f"Pattern '{pid}' dropped {abs(delta):.1%} "
                    f"(threshold: {THRESHOLD_PATTERN:.0%})"
                ),
            })
            fail_reasons.append(f"pattern_regression:{pid}")
        elif delta > 0.02:
            improvements.append({
                "type": "pattern", "pattern_id": pid,
                "previous": round(prev_score, 4), "current": round(cur_score, 4),
                "delta": round(delta, 4),
            })

    # 4. Confidence error (increase = bad)
    conf_delta = cur_conf - prev_conf
    if conf_delta > THRESHOLD_CONFIDENCE:
        regressions.append({
            "type":     "confidence",
            "field":    "confidence_error",
            "previous": round(prev_conf, 4),
            "current":  round(cur_conf, 4),
            "delta":    round(conf_delta, 4),
            "severity": "warning",
            "reason":   (
                f"Confidence error increased by {conf_delta:.3f} "
                f"(threshold: {THRESHOLD_CONFIDENCE:.2f})"
            ),
        })
        fail_reasons.append("confidence_regression")

    failed = len(fail_reasons) > 0

    return {
        "has_baseline":     True,
        "status":           "fail" if failed else "pass",
        "recommendation":   "block_deploy" if failed else "safe_to_merge",
        "overall_score":    round(cur_overall, 4),
        "delta":            round(overall_delta, 4),
        "baseline_score":   round(prev_overall, 4),
        "blueprint_score":  round(cur_blueprint, 4),
        "blueprint_delta":  round(bp_delta, 4),
        "confidence_error": round(cur_conf, 4),
        "confidence_delta": round(conf_delta, 4),
        "regressions":      regressions,
        "improvements":     improvements,
        "fail_reasons":     fail_reasons,
        "baseline_version": baseline.get("version_id"),
        "baseline_run_id":  baseline.get("run_id"),
    }
