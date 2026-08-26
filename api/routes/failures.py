"""
Failure Event API — /api/failures/*

Receives enriched MISSED_IT signals from the client.
Records them to failure_events, classifies them immediately,
and feeds the failure-cluster ingestion pipeline.

POST /api/failures/event      — record a confirmed failure
POST /api/failures/feedback   — attach structured user feedback to a failure
GET  /api/failures/stats      — per-pattern failure breakdown (admin)
GET  /api/failures/loop       — feedback loop metrics: MISSED_IT → NAILED_IT (admin)
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.security import get_optional_user, get_current_user
from db.failures import (
    init_failure_tables,
    record_failure_event,
    set_failure_class,
    record_failure_feedback,
    get_failure_stats,
    get_feedback_loop_stats,
)
from engine.learning.failure_classifier import classify_failure

logger = logging.getLogger(__name__)
router = APIRouter(tags=["failures"])

from config.admin import is_admin

# Ensure tables exist at import time (same pattern as other routers)
try:
    init_failure_tables()
except Exception as _e:
    logger.warning("Could not init failure tables: %s", _e)


# ── Models ────────────────────────────────────────────────────────────────────

class FailureEvent(BaseModel):
    """
    Full-context failure event — sent after outcome='failed' is confirmed.
    """
    # Identity
    session_id:         Optional[str]   = None
    user_id:            Optional[str]   = None

    # What the system predicted
    predicted_pattern:  str             = Field(..., min_length=1, max_length=64)
    confidence:         Optional[float] = Field(None, ge=0.0, le=1.0)
    signal_quality:     Optional[float] = Field(None, ge=0.0, le=1.0)

    # What the user was working with
    blueprint_id:       Optional[str]   = None
    image_hash:         Optional[str]   = None

    # Context for classification
    subject_type:       Optional[str]   = None
    environment:        Optional[str]   = None
    shadow_density:     Optional[float] = None
    lighting_geometry:  Optional[str]   = None
    edge_case_flags:    Dict[str, Any]  = {}

    # Raw shoot-mode context for blueprint_failure detection
    shoot_mode_entered: bool            = False
    steps_completed:    int             = 0
    deviation_count:    int             = 0

    # Optional immediate feedback reason
    feedback_reason:    Optional[str]   = None
    feedback_text:      Optional[str]   = None


class FeedbackPayload(BaseModel):
    failure_event_id:   str
    session_id:         Optional[str] = None
    reason:             str           = Field(
        ...,
        description=(
            "wrong_pattern | blueprint_didnt_work | couldnt_understand | "
            "low_confidence_confirmed | other"
        ),
    )
    free_text:          Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/failures/event", status_code=201)
async def record_failure(
    body: FailureEvent,
    user=Depends(get_optional_user),
):
    """
    Record a confirmed failure and immediately classify it.
    Returns the failure_event_id so the client can attach feedback.
    """
    # Classify synchronously — classification is pure logic, very fast
    failure_class = classify_failure(
        confidence=body.confidence,
        signal_quality=body.signal_quality,
        shoot_mode_entered=body.shoot_mode_entered,
        steps_completed=body.steps_completed,
        deviation_count=body.deviation_count,
        edge_case_flags=body.edge_case_flags,
    )

    # Resolve user_id: prefer authenticated identity
    resolved_user_id = body.user_id
    if user:
        resolved_user_id = user.get("id") or user.get("sub") or body.user_id

    # Store raw context in raw_context_json for future replay
    raw_context = {
        "shoot_mode_entered": body.shoot_mode_entered,
        "steps_completed": body.steps_completed,
        "deviation_count": body.deviation_count,
    }

    event_id = record_failure_event(
        predicted_pattern=body.predicted_pattern,
        session_id=body.session_id,
        user_id=resolved_user_id,
        confidence=body.confidence,
        signal_quality=body.signal_quality,
        blueprint_id=body.blueprint_id,
        image_hash=body.image_hash,
        failure_class=failure_class,
        subject_type=body.subject_type,
        environment=body.environment,
        shadow_density=body.shadow_density,
        lighting_geometry=body.lighting_geometry,
        edge_case_flags=body.edge_case_flags,
        raw_context=raw_context,
    )

    # Optionally capture immediate inline feedback
    if body.feedback_reason:
        try:
            record_failure_feedback(
                failure_event_id=event_id,
                reason=body.feedback_reason,
                session_id=body.session_id,
                free_text=body.feedback_text,
            )
        except Exception as e:
            logger.warning("Inline feedback write failed for %s: %s", event_id, e)

    logger.info(
        "failure_event session=%s pattern=%s class=%s confidence=%.2f",
        body.session_id or "anon",
        body.predicted_pattern,
        failure_class,
        body.confidence or 0.0,
    )

    return {"id": event_id, "failure_class": failure_class}


@router.post("/failures/feedback", status_code=201)
async def attach_feedback(
    body: FeedbackPayload,
    user=Depends(get_optional_user),
):
    """Attach structured user feedback to a previously recorded failure."""
    try:
        fb_id = record_failure_feedback(
            failure_event_id=body.failure_event_id,
            reason=body.reason,
            session_id=body.session_id,
            free_text=body.free_text,
        )
    except Exception as e:
        logger.exception("Failed to record failure feedback: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save feedback")

    return {"id": fb_id}


@router.get("/failures/stats")
async def failure_stats(
    days: int = 30,
    user=Depends(get_current_user),
):
    """Per-pattern failure breakdown. Admin only."""
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    return {"days": days, "patterns": get_failure_stats(days)}


@router.get("/failures/loop")
async def feedback_loop(
    days: int = 30,
    user=Depends(get_current_user),
):
    """
    Feedback loop metrics: MISSED_IT rate, NAILED_IT rate,
    high-confidence failure breakdown.  Admin only.
    """
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    return get_feedback_loop_stats(days)
