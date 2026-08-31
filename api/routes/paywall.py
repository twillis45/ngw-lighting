"""
POST /api/paywall/event                         — unified paywall event (writes analytics + experiment tables)
POST /api/usage/increment                       — server-side analysis count sync
POST /api/paywall/upgrade-intent                — log upgrade funnel entry
POST /api/paywall/adaptive-pricing              — Part 16: compute adaptive price + messaging for user state
POST /api/paywall/impression                    — Part 16: record paywall impression
POST /api/paywall/impression/{id}/converted     — Part 16: mark impression as converted
POST /api/paywall/impression/{id}/dismissed     — Part 16: mark impression as dismissed
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth.security import get_optional_user
from db.experiments import record_experiment_event
from db.database import get_db, increment_analysis_count

# ── Part 16: adaptive paywall ─────────────────────────────────────────────────
try:
    from engine.paywall.value_state import detect_value_state
    from engine.paywall.adaptive_pricing import get_adaptive_pricing
    from db.paywall_analytics import (
        init_paywall_analytics_tables,
        record_paywall_impression,
        mark_impression_converted,
        mark_impression_dismissed,
    )
    init_paywall_analytics_tables()
    _adaptive_enabled = True
except Exception as _adaptive_exc:
    _adaptive_enabled = False
    import warnings
    warnings.warn(f"Adaptive paywall not available: {_adaptive_exc}")

logger = logging.getLogger(__name__)
router = APIRouter(tags=["paywall"])


# ── Models ────────────────────────────────────────────────────────────────────

class PaywallEvent(BaseModel):
    session_id: str
    event_name: str          # PAYWALL_TRIGGERED | PAYWALL_DISMISSED | PAYWALL_BYPASSED
    trigger: str             # success_moment | shoot_mode | analysis_limit | passive_nudge
    type: str                # hard | soft | value_triggered | nudge
    analysis_count: int = 0
    active_flags: List[str] = []
    data: dict = {}


class UsageIncrement(BaseModel):
    session_id: str
    event: str = "analysis_complete"


class UpgradeIntent(BaseModel):
    session_id: str
    plan: str                # pro | studio
    billing_period: str      # monthly | yearly
    price: float
    trigger: Optional[str] = None
    active_flags: List[str] = []


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/paywall/event", status_code=204)
async def paywall_event(
    body: PaywallEvent,
    user=Depends(get_optional_user),
):
    """
    Record a paywall lifecycle event.
    Writes to experiment_events for each active flag so metrics stay in sync.
    """
    CONVERSION_GROUPS = {"pricing", "paywall_timing", "cta_messaging", "paywall_value"}

    try:
        from api.routes.flags import get_flags_for_session
        flags = get_flags_for_session(body.session_id)
    except Exception as exc:
        # Was a bare `except Exception: flags = {}`, which swallowed an
        # ImportError for a module that never existed — so every experiment
        # recorded zero events and nothing said so. Kept non-fatal (a flag
        # lookup must not break checkout) but no longer silent.
        logger.warning("flag lookup failed, treating as no flags: %s", exc)
        flags = {}

    for flag_name, flag_def in flags.items():
        if not flag_def.get("enabled"):
            continue
        if flag_def.get("group") not in CONVERSION_GROUPS:
            continue
        record_experiment_event(
            session_id=body.session_id,
            flag_name=flag_name,
            variant=flag_def.get("variant", "control"),
            event_name=body.event_name,
            group=flag_def.get("group"),
            data={
                "trigger": body.trigger,
                "type": body.type,
                "analysis_count": body.analysis_count,
                **body.data,
            },
        )

    logger.info(
        "paywall_event session=%s event=%s trigger=%s",
        body.session_id, body.event_name, body.trigger,
    )


@router.post("/paywall/upgrade-intent", status_code=204)
async def upgrade_intent(
    body: UpgradeIntent,
    user=Depends(get_optional_user),
):
    """Log an upgrade funnel entry (user reached pricing screen and selected a plan)."""
    try:
        from api.routes.flags import get_flags_for_session
        flags = get_flags_for_session(body.session_id)
    except Exception as exc:
        # Was a bare `except Exception: flags = {}`, which swallowed an
        # ImportError for a module that never existed — so every experiment
        # recorded zero events and nothing said so. Kept non-fatal (a flag
        # lookup must not break checkout) but no longer silent.
        logger.warning("flag lookup failed, treating as no flags: %s", exc)
        flags = {}

    for flag_name, flag_def in flags.items():
        if not flag_def.get("enabled"):
            continue
        record_experiment_event(
            session_id=body.session_id,
            flag_name=flag_name,
            variant=flag_def.get("variant", "control"),
            event_name="UPGRADE_STARTED",
            data={
                "plan": body.plan,
                "billing_period": body.billing_period,
                "price": body.price,
                "trigger": body.trigger,
            },
        )


@router.post("/usage/increment", status_code=200)
async def usage_increment(
    body: UsageIncrement,
    user=Depends(get_optional_user),
):
    """
    Increment analysis count for a session.
    Returns current count and whether the session is at the paywall threshold.
    """
    try:
        from api.routes.flags import get_flags_for_session
        flags = get_flags_for_session(body.session_id)
        paywall_flag = next(
            (f for f in flags.values() if f.get("group") == "paywall_timing" and f.get("enabled")),
            None,
        )
        threshold = (paywall_flag or {}).get("config", {}).get("threshold", 3)
    except Exception:
        threshold = 3

    # Prefer user_id scoping when the caller is authenticated — this makes
    # counts portable across browsers and devices.
    user_id: Optional[str] = None
    if user:
        user_id = user.get("id") or user.get("sub") or None

    try:
        result = increment_analysis_count(body.session_id, user_id=user_id)
        count = result["count"]
    except Exception as exc:
        logger.warning("Failed to increment analysis count for session=%s: %s", body.session_id, exc)
        count = 0

    is_at_limit = count >= threshold
    logger.info(
        "usage_increment session=%s user_id=%s count=%d threshold=%d at_limit=%s",
        body.session_id, user_id or "anon", count, threshold, is_at_limit,
    )
    return {"threshold": threshold, "count": count, "is_at_limit": is_at_limit}


# ── Part 16: Adaptive Paywall ─────────────────────────────────────────────────

class AdaptivePricingRequest(BaseModel):
    session_id:         Optional[str]  = None
    user_id:            Optional[str]  = None
    recent_outcome:     Optional[str]  = None   # "nailed_it" | "missed_it"
    usage_count:        int            = 0
    session_count:      int            = 0
    shoot_mode_used:    bool           = False
    blueprint_views:    int            = 0
    session_max_price:  int            = 0       # anti-discount guard
    experiment_variant: Optional[str]  = None


class ImpressionPayload(BaseModel):
    value_state:        str
    price_shown:        int
    session_id:         Optional[str]  = None
    user_id:            Optional[str]  = None
    messaging_variant:  Optional[str]  = None
    cta_variant:        Optional[str]  = None
    trigger_type:       Optional[str]  = None
    guardrail_applied:  bool           = False
    experiment_variant: Optional[str]  = None


@router.post("/paywall/adaptive-pricing")
async def adaptive_pricing(
    body: AdaptivePricingRequest,
    user=Depends(get_optional_user),
):
    """
    Part 16.5 — Compute adaptive price + messaging for the current user state.
    POST (not GET) to keep behaviour signals private.
    """
    if not _adaptive_enabled:
        return {"price_monthly": 39, "price_yearly": 390, "state": "low_value",
                "messaging": {"cta": "Unlock Full Access — $39/mo"}, "error": "adaptive_disabled"}

    resolved_user_id = body.user_id
    if user:
        resolved_user_id = user.get("id") or user.get("sub") or body.user_id

    state_result = detect_value_state(
        session_id=body.session_id,
        user_id=resolved_user_id,
        recent_outcome=body.recent_outcome,
        usage_count=body.usage_count,
        session_count=body.session_count,
        shoot_mode_used=body.shoot_mode_used,
        blueprint_views=body.blueprint_views,
    )

    pricing = get_adaptive_pricing(
        value_state=state_result["state"],
        session_max_price=body.session_max_price,
        experiment_variant=body.experiment_variant,
    )

    return {
        "value_state":   state_result["state"],
        "state_signals": state_result["signals"],
        **pricing,
    }


@router.post("/paywall/impression", status_code=201)
async def log_impression(
    body: ImpressionPayload,
    user=Depends(get_optional_user),
):
    """Part 16.11 — Record that a paywall was shown with a specific price and state."""
    if not _adaptive_enabled:
        return {"impression_id": None}

    resolved_user_id = body.user_id
    if user:
        resolved_user_id = user.get("id") or user.get("sub") or body.user_id

    impression_id = record_paywall_impression(
        value_state=body.value_state,
        price_shown=body.price_shown,
        session_id=body.session_id,
        user_id=resolved_user_id,
        messaging_variant=body.messaging_variant,
        cta_variant=body.cta_variant,
        trigger_type=body.trigger_type,
        guardrail_applied=body.guardrail_applied,
        experiment_variant=body.experiment_variant,
    )
    return {"impression_id": impression_id}


@router.post("/paywall/impression/{impression_id}/converted")
async def impression_converted(
    impression_id: str,
    user=Depends(get_optional_user),
):
    """Part 16.12 — Mark a paywall impression as converted (upgrade flow started)."""
    if _adaptive_enabled:
        mark_impression_converted(impression_id)
    return {"ok": True}


@router.post("/paywall/impression/{impression_id}/dismissed")
async def impression_dismissed(
    impression_id: str,
    user=Depends(get_optional_user),
):
    """Part 16.12 — Mark a paywall impression as dismissed."""
    if _adaptive_enabled:
        mark_impression_dismissed(impression_id)
    return {"ok": True}
