"""
GET  /api/experiments/metrics            — per-flag conversion + revenue metrics (admin)
GET  /api/experiments/metrics/{flag}     — single flag metrics (admin)
GET  /api/experiments/candidates         — decision engine: promote/rollback/hold (admin)
POST /api/experiments/event              — record an experiment event
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.security import get_current_user, get_optional_user
from db.experiments import (
    generate_candidates,
    get_all_experiment_metrics,
    get_experiment_metrics,
    invalidate_metrics_cache,
    record_experiment_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["experiments"])

from config.admin import is_admin


@router.get("/experiments/metrics")
async def all_metrics(
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    """All active experiment metrics. Admin only."""
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    return {"days": days, "experiments": get_all_experiment_metrics(days)}


@router.get("/experiments/metrics/{flag_name}")
async def flag_metrics(
    flag_name: str,
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    """Single flag metrics. Admin only."""
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    return get_experiment_metrics(flag_name, days)


@router.get("/experiments/candidates")
async def candidates(
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    """
    Decision engine: evaluate all experiments and return promote/rollback/hold candidates.
    Admin only.
    """
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    return {"days": days, "candidates": generate_candidates(days)}


class ExpEvent(BaseModel):
    session_id: str
    flag_name: str
    variant: str
    event_name: str
    group: Optional[str] = None   # narrows attribution to a specific flag group
    data: dict = {}


@router.post("/experiments/event", status_code=204)
async def experiment_event(
    body: ExpEvent,
    user=Depends(get_optional_user),
):
    """
    Record an experiment exposure or conversion event.
    Called client-side when a user hits a paywall, upgrades, or completes a key action.
    """
    try:
        record_experiment_event(
            session_id=body.session_id,
            flag_name=body.flag_name,
            variant=body.variant,
            event_name=body.event_name,
            data=body.data,
            group=body.group,
        )
        # Invalidate cached metrics so the next dashboard read reflects the new event
        invalidate_metrics_cache()
    except Exception:
        logger.exception("Failed to record experiment event")
    return None
