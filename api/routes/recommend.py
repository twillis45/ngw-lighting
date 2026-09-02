"""Recommend route — thin HTTP layer.

All business logic lives in engine.services.recommend_service.
This route only:
  1. Validates the request
  2. Calls build_recommend_result()
  3. Formats the HTTP response
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from engine.request_context import set_request_context, clear_request_context

logger = logging.getLogger(__name__)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from auth.security import get_optional_user
from db.database import get_analysis_count, increment_analysis_count, get_active_subscription
from db.provenance import get_internal_emails
from engine.services.recommend_service import (
    build_recommend_result,
    ENGINE_VERSION,
)

_DEFAULT_PAYWALL_THRESHOLD = 3

router = APIRouter()


# ── Request models ──

class SystemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: Optional[str] = None
    criteria: Dict[str, Any] = Field(default_factory=dict)
    features: Dict[str, Any] = Field(default_factory=dict)
    taxonomy_refs: Dict[str, Any] = Field(default_factory=dict)
    modifier: Optional[float] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("id must be non-empty")
        return str(v).strip()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("name must be non-empty")
        return str(v).strip()


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    systems: List[SystemRequest] = Field(min_length=1)
    input: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    modifiers_available: List[str] = Field(default_factory=list)


def _json_safe_errors(errs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in errs:
        item = dict(e)
        ctx = item.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {k: str(v) for k, v in ctx.items()}
        out.append(item)
    return out


# ── Endpoint ──

@router.post("/recommend")
def recommend(body: Dict[str, Any], user=Depends(get_optional_user)) -> Dict[str, Any]:
    """Recommend a lighting system from caller-provided candidates.

    This route is a thin HTTP layer. All business logic — selection,
    scoring, response formatting — lives in
    engine.services.recommend_service.build_recommend_result().

    Server-side paywall gate: free/anonymous sessions are capped at
    the paywall_timing flag threshold (default 3). Paid subscribers bypass.
    """
    # ── Paywall gate ─────────────────────────────────────────────────────────
    is_paid = False
    if user:
        # Admin/internal emails always bypass the paywall — no subscription needed
        user_email = user.get("email", "")
        if user_email.lower() in get_internal_emails():
            is_paid = True
            logger.info("[recommend] paywall bypass: user=%s is_internal=True (unlimited analyses)", user_email)
        else:
            try:
                sub = get_active_subscription(user_email)
                is_paid = sub is not None
                if is_paid:
                    logger.info("[recommend] paywall bypass: user=%s is_paid=True plan=%s", user_email, sub.get("plan") if isinstance(sub, dict) else "active")
            except Exception as exc:
                logger.error("subscription check failed for user=%s: %s", user_email, exc)
                raise HTTPException(
                    status_code=503,
                    detail={"code": "SUBSCRIPTION_CHECK_FAILED",
                            "message": "Unable to verify subscription. Please try again."},
                )
    else:
        logger.info("[recommend] paywall check: anonymous user (no JWT)")

    _count_key = None
    if not is_paid:
        session_id: str = (body.get("metadata") or {}).get("session_id", "")
        if not session_id:
            raise HTTPException(
                status_code=400,
                detail={"code": "SESSION_ID_REQUIRED", "message": "session_id is required in metadata."},
            )
        user_id: Optional[str] = None
        if user:
            user_id = user.get("id") or user.get("sub") or None
        if session_id:
            count = get_analysis_count(session_id, user_id=user_id)
            threshold = _DEFAULT_PAYWALL_THRESHOLD
            try:
                from api.routes.flags import get_flags_for_session
                flags = get_flags_for_session(session_id)
                paywall_flag = next(
                    (f for f in flags.values()
                     if f.get("group") == "paywall_timing" and f.get("enabled")),
                    None,
                )
                if paywall_flag:
                    threshold = paywall_flag.get("config", {}).get("threshold", _DEFAULT_PAYWALL_THRESHOLD)
            except Exception as exc:
                logger.warning("[recommend] paywall flags load failed: %s", exc)
            if count >= threshold:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "code": "PAYWALL_LIMIT_REACHED",
                        "message": "Free analysis limit reached. Upgrade to Pro for unlimited analyses.",
                        "count": count,
                        "threshold": threshold,
                    },
                )

            # COUNT HERE, server-side. Until 2026-09-02 the count only ever rose
            # because the browser voluntarily POSTed /api/usage/increment — the
            # sole call site in the repo — so the free tier was enforced only
            # against a cooperating client. Measured:
            #
            #   honest client, increments each time : 3 free, then 402
            #   never call increment                : 8 of 8 succeeded
            #
            # Deleting one fetch bought unlimited free analyses. The gate above
            # was real; the number it read was supplied by the caller.
            #
            # Failure to record must not grant a free analysis, but must also
            # not deny a paid-for one, so it is logged and allowed through —
            # the honest trade for a counter, unlike the waitlist where a
            # failed read destroyed data and refusing was correct.
            # Recorded AFTER validation, not here — see below. The GATE
            # belongs early (no point doing work for someone over the limit)
            # but the COUNT must not tick for a request that never becomes an
            # analysis: validation runs further down, so counting here charged
            # a free analysis for a malformed body and returned 402 instead of
            # 422 for anyone near their limit. Caught by the suite, not by me.
            _count_key = (session_id, user_id)
    # ─────────────────────────────────────────────────────────────────────────

    # Set request context for log tracing
    _session_id = (body.get("metadata") or {}).get("session_id", "")
    set_request_context(
        user_id=user.get("id") or user.get("sub") if user else None,
        user_email=user.get("email") if user else None,
        session_id=_session_id or None,
    )
    try:
        req = RecommendRequest.model_validate(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_json_safe_errors(e.errors()))

    # The request is real and will be served — count it now. Free-tier
    # enforcement must not depend on the client reporting its own usage (that
    # was the defect), but it must also not charge for a request the server
    # rejected. Failure to record is logged and allowed through: not recording
    # must not grant a free analysis, but must not deny a paid-for one either.
    if _count_key is not None:
        _sid, _uid = _count_key
        try:
            increment_analysis_count(_sid, user_id=_uid)
        except Exception as exc:
            logger.error("[recommend] analysis count NOT recorded for %s: %s", _sid, exc)

    try:
        result = build_recommend_result(
            systems=[s.model_dump() for s in req.systems],
            input_ctx=req.input,
            modifiers_available=req.modifiers_available,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_json_safe_errors(e.errors()))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=[{"msg": str(e)}])

    metadata = dict(req.metadata or {})
    metadata["engine_version"] = ENGINE_VERSION

    response: Dict[str, Any] = {
        "status": "success",
        "request_id": result.request_id,
        "metadata": metadata,
        "usage": {
            "processing_ms": result.processing_ms,
        },
        "result": {
            "content": result.content,
            "structured": result.structured,
            "diagram_spec": result.diagram_spec,
            "confidence": result.confidence,
        },
    }

    # Candidate-first data (new — consumers can adopt progressively)
    if result.primary_candidate:
        response["candidates"] = {
            "primary_candidate": result.primary_candidate,
            "alternate_candidates": result.alternate_candidates,
        }
    if result.validation_scores:
        response["validationScores"] = result.validation_scores
    if result.needs_review:
        response["needsReview"] = True

    clear_request_context()
    return response
