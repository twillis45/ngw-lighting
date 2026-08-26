"""
Intelligence System API — /api/intelligence/*
===============================================

GET  /api/intelligence/score          — current global score (compute or cached)
GET  /api/intelligence/score/history  — score trend over time
GET  /api/intelligence/patterns       — per-pattern scores + priority table
GET  /api/intelligence/clusters       — current failure/success cluster report
GET  /api/intelligence/nailed-it/stats — NAILED_IT event breakdown (admin)

POST /api/intelligence/nailed-it      — record a NAILED_IT outcome (enriched)
POST /api/intelligence/compute        — force recompute of score + pattern scores

GET  /api/intelligence/flags          — flag performance with intelligence scores
POST /api/intelligence/autonomy/run   — run one decision loop pass (admin)
GET  /api/intelligence/autonomy/log   — full audit log (admin)
GET  /api/intelligence/autonomy/queue — pending approval queue (admin)
POST /api/intelligence/autonomy/approve/{action_id} — approve queued action (admin)
POST /api/intelligence/autonomy/reject/{action_id}  — reject queued action (admin)
GET  /api/intelligence/autonomy/dashboard — autonomy summary (admin)
GET  /api/intelligence/sample-calc    — worked score example (no auth)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import os
from auth.security import get_optional_user, get_current_user
from db.intelligence import (
    init_intelligence_tables,
    record_nailed_it_event,
    get_nailed_it_events,
    get_intelligence_history,
    get_latest_intelligence_snapshot,
    get_latest_pattern_scores,
    get_autonomy_log,
    get_autonomy_queue,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intelligence"])

from auth.dev_guard import get_dev_user
from config.admin import is_admin

try:
    init_intelligence_tables()
except Exception as _e:
    logger.warning("intelligence: could not init tables — %s", _e)


# ── Models ─────────────────────────────────────────────────────────────────────

class NailedItEvent(BaseModel):
    session_id:        Optional[str]   = None
    user_id:           Optional[str]   = None
    predicted_pattern: str             = Field(..., min_length=1, max_length=64)
    confidence:        Optional[float] = Field(None, ge=0.0, le=1.0)
    signal_quality:    Optional[float] = Field(None, ge=0.0, le=1.0)
    blueprint_id:      Optional[str]   = None
    image_hash:        Optional[str]   = None
    subject_type:      Optional[str]   = None
    environment:       Optional[str]   = None
    shadow_density:    Optional[float] = None
    lighting_geometry: Optional[str]   = None
    edge_case_flags:   Dict[str, Any]  = {}


class ApprovalPayload(BaseModel):
    approved_by: str = Field(..., min_length=1)


class RejectPayload(BaseModel):
    rejected_by: str = Field(..., min_length=1)
    reason:      str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_admin(user: dict) -> None:
    # NGW_DEV_MODE=1 bypasses admin gate for local development
    if os.getenv("NGW_DEV_MODE", "").strip().lower() in ("1", "true", "yes"):
        return
    if not user or not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")


# ── NAILED_IT capture ─────────────────────────────────────────────────────────

@router.post("/intelligence/nailed-it", status_code=201)
async def record_nailed_it(
    body: NailedItEvent,
    user=Depends(get_optional_user),
):
    """
    Record an enriched NAILED_IT outcome event.
    Symmetric with POST /failures/event — called by ResultsScreenV2 on nailed_it.
    """
    resolved_user_id = body.user_id
    if user:
        resolved_user_id = user.get("id") or user.get("sub") or body.user_id

    event_id = record_nailed_it_event(
        predicted_pattern=body.predicted_pattern,
        session_id=body.session_id,
        user_id=resolved_user_id,
        confidence=body.confidence,
        signal_quality=body.signal_quality,
        blueprint_id=body.blueprint_id,
        image_hash=body.image_hash,
        subject_type=body.subject_type,
        environment=body.environment,
        shadow_density=body.shadow_density,
        lighting_geometry=body.lighting_geometry,
        edge_case_flags=body.edge_case_flags,
    )

    logger.info(
        "nailed_it pattern=%s confidence=%.2f session=%s",
        body.predicted_pattern, body.confidence or 0.0,
        body.session_id or "anon",
    )
    return {"id": event_id}


# ── Score endpoints ───────────────────────────────────────────────────────────

@router.get("/intelligence/score")
async def get_score(
    days: int = 30,
    force: bool = False,
    user: Dict = Depends(get_dev_user),
):
    """
    Return current global intelligence score.
    Uses cached snapshot unless force=true or no snapshot exists.
    """
    if not force:
        cached = get_latest_intelligence_snapshot(window_days=days)
        if cached:
            from engine.intelligence.score import _interpret
            import json
            comps = json.loads(cached.get("components_json") or "{}")
            return {
                "score":           cached["score"],
                "interpretation":  _interpret(cached["score"]),
                "window_days":     days,
                "computed_at":     cached["computed_at"],
                "cached":          True,
                "components":      comps,
            }

    from engine.intelligence.score import compute_global_score
    return {**compute_global_score(days=days, save=True), "cached": False}


@router.get("/intelligence/score/history")
async def get_score_history(days: int = 30, limit: int = 30, user: Dict = Depends(get_dev_user)):
    """Score trend — last `limit` snapshots for the given window."""
    history = get_intelligence_history(limit=limit, window_days=days)
    return {"window_days": days, "history": history}


@router.get("/intelligence/patterns")
async def get_pattern_scores(
    days: int = 30,
    force: bool = False,
    user: Dict = Depends(get_dev_user),
):
    """
    Per-pattern intelligence scores + priority table.
    Returns cached scores unless force=true.
    """
    if not force:
        cached = get_latest_pattern_scores(window_days=days)
        if cached:
            return {"window_days": days, "patterns": cached, "cached": True}

    from engine.intelligence.score import compute_pattern_scores
    patterns = compute_pattern_scores(days=days, save=True)
    return {"window_days": days, "patterns": patterns, "cached": False}


@router.post("/intelligence/compute", status_code=200)
async def force_compute(
    days: int = 30,
    user=Depends(get_current_user),
):
    """Force-recompute global + pattern scores. Admin only."""
    _require_admin(user)
    from engine.intelligence.score import compute_global_score, compute_pattern_scores, compute_weighted_global_score
    global_score = compute_global_score(days=days, save=True)
    pattern_scores = compute_pattern_scores(days=days, save=True)
    weighted = compute_weighted_global_score(pattern_scores)
    return {
        "global_score":   global_score,
        "weighted_score": weighted,
        "pattern_count":  len(pattern_scores),
        "patterns":       pattern_scores,
    }


@router.get("/intelligence/sample-calc")
async def sample_calculation():
    """Worked example of the scoring formula — no auth required."""
    from engine.intelligence.score import sample_score_calculation
    return sample_score_calculation()


# ── Clustering ────────────────────────────────────────────────────────────────

@router.get("/intelligence/clusters")
async def get_clusters(
    days: int = 30,
    user=Depends(get_current_user),
):
    """Current failure/success cluster report. Admin only."""
    _require_admin(user)
    from engine.intelligence.clustering import build_cluster_report
    return build_cluster_report(days=days)


# ── NAILED_IT stats ───────────────────────────────────────────────────────────

@router.get("/intelligence/nailed-it/stats")
async def nailed_it_stats(
    days: int = 30,
    user=Depends(get_current_user),
):
    """NAILED_IT breakdown by pattern. Admin only."""
    _require_admin(user)
    from db.database import get_db
    import time as _time
    cutoff = _time.time() - days * 86400
    with get_db() as conn:
        rows = conn.execute(
            """SELECT predicted_pattern,
                      COUNT(*) AS count,
                      AVG(confidence) AS avg_confidence,
                      AVG(signal_quality) AS avg_signal_quality
               FROM nailed_it_events
               WHERE created_at >= ?
               GROUP BY predicted_pattern
               ORDER BY count DESC""",
            (cutoff,),
        ).fetchall()
    return {
        "days":     days,
        "patterns": [dict(r) for r in rows],
        "total":    sum(r["count"] for r in rows),
    }


# ── Flag intelligence ─────────────────────────────────────────────────────────

@router.get("/intelligence/flags")
async def flag_intelligence(
    days: int = 30,
    user=Depends(get_current_user),
):
    """Flag performance table with intelligence scores and decisions. Admin only."""
    _require_admin(user)
    from engine.intelligence.flag_optimizer import evaluate_all_flags
    decisions = evaluate_all_flags(days=days)
    return {"days": days, "flags": decisions}


# ── Autonomy ──────────────────────────────────────────────────────────────────

@router.post("/intelligence/autonomy/run")
async def run_autonomy_loop(
    days: int = 30,
    user=Depends(get_current_user),
):
    """Run one pass of the autonomous optimization loop. Admin only."""
    _require_admin(user)
    from engine.intelligence.autonomy import run_decision_loop
    return run_decision_loop(days=days)


@router.get("/intelligence/autonomy/log")
async def autonomy_log(
    limit: int = 50,
    risk_tier: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Full autonomy audit log. Admin only."""
    _require_admin(user)
    return {
        "log": get_autonomy_log(limit=limit, risk_tier=risk_tier, status=status)
    }


@router.get("/intelligence/autonomy/queue")
async def autonomy_queue(user=Depends(get_current_user)):
    """Pending MEDIUM/HIGH risk actions awaiting approval. Admin only."""
    _require_admin(user)
    return {"queue": get_autonomy_queue(status="pending")}


@router.post("/intelligence/autonomy/approve/{action_id}")
async def approve_action(
    action_id: str,
    body: ApprovalPayload,
    user=Depends(get_current_user),
):
    """Approve a pending MEDIUM/HIGH risk queued action. Admin only."""
    _require_admin(user)
    from engine.intelligence.autonomy import approve_queued_action
    return approve_queued_action(action_id, approved_by=body.approved_by)


@router.post("/intelligence/autonomy/reject/{action_id}")
async def reject_action(
    action_id: str,
    body: RejectPayload,
    user=Depends(get_current_user),
):
    """Reject a pending queued action. Admin only."""
    _require_admin(user)
    from engine.intelligence.autonomy import reject_queued_action
    return reject_queued_action(action_id, rejected_by=body.rejected_by, reason=body.reason)


@router.get("/intelligence/autonomy/dashboard")
async def autonomy_dashboard(
    days: int = 7,
    user=Depends(get_current_user),
):
    """Autonomy summary for ExecDashboard — active actions, rollbacks, guardrail status."""
    _require_admin(user)
    from engine.intelligence.autonomy import build_autonomy_dashboard_summary
    return build_autonomy_dashboard_summary(days=days)
