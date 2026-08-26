"""
POST /api/track              — receive a client-side event
GET  /api/analytics/stats    — aggregated dashboard stats (admin only)
GET  /api/analytics/dashboard — rich dashboard data (admin only)
GET  /api/analytics/provenance — data hygiene / session origin counts (admin only)
POST /api/analytics/sessions/{session_id}/promote — manually promote a session for learning review
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from auth.security import get_current_user, get_optional_user
from db.analytics import record_event, get_all_stats

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics"])

from config.admin import is_admin


class TrackBody(BaseModel):
    name: str
    session_id: Optional[str] = None
    data: Dict[str, Any] = {}


class ExcludeBody(BaseModel):
    exclude: bool = True  # True = mark as test, False = restore to production


@router.post("/track", status_code=204)
async def track(
    body: TrackBody,
    user=Depends(get_optional_user),
):
    """Accept a client-side analytics event. Auth is optional."""
    user_id = user["id"] if user else None
    user_email = user.get("email") if user else None

    try:
        record_event(
            name=body.name,
            user_id=user_id,
            session_id=body.session_id,
            data=body.data,
        )
    except Exception:
        logger.exception("Failed to record analytics event: %s", body.name)
        # Never fail the client — swallow silently

    # Create provenance record for this session on first contact.
    # INSERT OR IGNORE — no-op if session already classified.
    # Wrapped separately so a provenance failure never blocks event tracking.
    if body.session_id:
        try:
            from db.provenance import ensure_session_provenance
            ensure_session_provenance(
                session_id=body.session_id,
                user_id=user_id,
                user_email=user_email,
            )
        except Exception:
            logger.exception("Failed to ensure session provenance for %s", body.session_id)

    return None  # 204


@router.get("/analytics/stats")
async def analytics_stats(
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    """Return aggregated analytics stats. Admin only."""
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return get_all_stats(days=days)


@router.get("/analytics/dashboard")
async def analytics_dashboard(
    days: int = Query(30, ge=1, le=365),
    origin: Optional[str] = Query(None, pattern="^(production|internal|all)?$"),
    user=Depends(get_current_user),
):
    """
    Rich dashboard data combining all analytics modules. Admin only.

    origin: 'production' | 'internal' | 'all' (default: production via exclusion flags)
    """
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    from db.analytics import (
        get_kpi_summary,
        get_success_conversion_breakdown,
        get_pattern_performance,
        get_daily_trend,
        get_session_quality,
        get_all_stats,
    )
    base = get_all_stats(days, origin)
    return {
        "days":               days,
        "origin":             origin or "all",
        "kpi":                get_kpi_summary(days, origin),
        "success_conversion": get_success_conversion_breakdown(days, origin),
        "pattern_performance": get_pattern_performance(days, origin),
        "daily_trend":        get_daily_trend(days, origin),
        "session_quality":    get_session_quality(days, origin),
        "funnel":             base["funnel"],
        "patterns":           base["patterns"],
        "shoot_mode":         base["shoot_mode"],
        "retention":          base["retention"],
        "paywall":            base["paywall"],
    }


@router.get("/analytics/provenance")
async def analytics_provenance(
    days: int = Query(30, ge=1, le=365),
    origin: Optional[str] = Query(None, pattern="^(production|internal|all)?$"),
    user=Depends(get_current_user),
):
    """
    Data hygiene summary: session origin breakdown and exclusion counts.
    Shows how many sessions are being excluded from each analytics dimension.
    Admin only.

    origin: 'production' | 'internal' | 'all' — scopes the exclusion counts
    (the by_origin breakdown is always the full picture regardless of filter).
    """
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    from db.provenance import get_provenance_summary
    return get_provenance_summary(days=days, origin=origin)


@router.post("/analytics/sessions/{session_id}/exclude")
async def set_session_exclude(
    body: ExcludeBody,
    session_id: str = Path(..., description="Session ID to mark/unmark as test"),
    user=Depends(get_current_user),
):
    """
    Mark or unmark the current session as a test/dev session.
    Any authenticated user can flag their own session to remove it from metrics.
    Uses session_origin='test' so it can be toggled back; never touches 'internal' sessions.
    """
    from db.provenance import (
        ensure_session_provenance,
        mark_session_as_test,
        unmark_session_as_test,
    )

    user_email = user.get("email", "")

    # Ensure a provenance record exists before we try to update it
    ensure_session_provenance(
        session_id=session_id,
        user_id=user.get("id"),
        user_email=user_email,
    )

    if body.exclude:
        updated = mark_session_as_test(session_id, marked_by=user_email)
        logger.info("Session %s marked as test by %s", session_id, user_email)
    else:
        updated = unmark_session_as_test(session_id)
        logger.info("Session %s unmarked (restored) by %s", session_id, user_email)

    return {
        "excluded": body.exclude,
        "session_id": session_id,
        "provenance": updated,
    }


@router.post("/analytics/sessions/{session_id}/promote")
async def promote_session_for_learning(
    session_id: str = Path(..., description="Session ID to promote"),
    user=Depends(get_current_user),
):
    """
    Manually promote an expert/internal session for learning review.
    Sets manually_promote_for_learning_review=True and clears exclude_from_learning.

    Only sessions with eligible_for_reference_review=True may be promoted.
    Admin only.
    """
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")

    from db.provenance import get_session_provenance, promote_session_for_learning

    prov = get_session_provenance(session_id)
    if not prov:
        raise HTTPException(
            status_code=404,
            detail="Session provenance record not found. Has this session sent any events?",
        )
    if not prov.get("eligible_for_reference_review"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Session origin is '{prov.get('session_origin')}' — "
                "only internal or expert sessions are eligible for manual promotion."
            ),
        )
    updated = promote_session_for_learning(session_id)
    logger.info(
        "Session %s promoted for learning review by %s",
        session_id, user.get("email"),
    )
    return {
        "promoted": True,
        "session_id": session_id,
        "provenance": updated,
    }
