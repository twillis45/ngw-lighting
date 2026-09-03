"""
Adaptive Pricing Engine — Part 16.2 / 16.5
Maps value state + signals to price point, messaging, and CTA.

PRICE MAP (base prices before guardrails / experiment overrides):
  LOW_VALUE       → $39   low-friction, exploration framing
  DISCOVERY       → $39   learning + improvement framing
  SUCCESS_MOMENT  → $59   outcome anchor ("you just solved this — keep it")
  HIGH_INTENT     → $59   workflow + consistency framing
  FAILURE_TENSION → $39   fix-focused, urgency framing

ANTI-DISCOUNT GUARDRAILS (Part 16.8):
  - Never show a lower price than the highest seen in this session
  - Never oscillate rapidly — price consistency per session
  - session_max_price is tracked by the caller (sessionStorage on client)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import os

from engine.paywall.messaging import get_messaging

# ── Valid price points (snap to nearest) ─────────────────────────────────────
PRICE_LADDER = [39, 49, 59, 79]


# ── A price may only be SHOWN if it can actually be CHARGED ──────────────────
# Added 2026-09-03. Until now this ladder and Stripe checkout were entirely
# independent. The ladder computed 39/49/59/79 from behaviour, the UI displayed
# it, db/paywall_analytics recorded it as price_shown -- and
# api/routes/stripe_checkout.py built its line_items from ONE fixed
# STRIPE_PRICE_ID_MONTHLY, ignoring the price point completely.
#
# Verified against production on 2026-09-03: POST /api/paywall/adaptive-pricing
# with a high-intent profile returned price_point 59 and the CTA
# "Unlock Pro -- $59/mo", while checkout would have charged whatever the single
# monthly Price ID contains. Nobody has been mischarged only because Stripe is
# still in test mode. Flipping to live with this in place bills people an
# amount they were never shown.
#
# The fix is structural rather than a warning: a point is offerable only when a
# Stripe Price ID exists for it. Configure STRIPE_PRICE_ID_MONTHLY_49 and
# friends to open a rung. With none set, everyone sees the base price, which is
# what the single fixed ID charges -- display and charge agree by construction.
def sellable_points() -> list[int]:
    """Price points backed by a real Stripe Price ID, ascending.

    Always includes the ladder's base: STRIPE_PRICE_ID_MONTHLY is the one that
    has always existed, and it is what an unconfigured rung falls back to.
    """
    base = PRICE_LADDER[0]
    points = {base} if os.getenv("STRIPE_PRICE_ID_MONTHLY") else {base}
    for pt in PRICE_LADDER:
        if os.getenv(f"STRIPE_PRICE_ID_MONTHLY_{pt}"):
            points.add(pt)
    return sorted(points)


def _clamp_to_sellable(price: int) -> int:
    """Snap DOWN to the highest sellable point <= price. Never up: charging
    more than the behaviour model asked for is the worse failure."""
    allowed = sellable_points()
    eligible = [p for p in allowed if p <= price]
    return max(eligible) if eligible else allowed[0]

# ── State → base price ────────────────────────────────────────────────────────
_STATE_BASE_PRICE: Dict[str, int] = {
    "low_value":       39,
    "discovery":       39,
    "success_moment":  59,
    "high_intent":     59,
    "failure_tension": 39,
}

# ── Intelligence score → price boost ─────────────────────────────────────────
# Format: (min_score, boost_dollars)
_INTEL_PRICE_BOOSTS = [
    (0.80, 10),   # score >= 0.80 → +$10 (e.g. $39→$49, $59→$69→snapped to $59)
    (0.65, 0),    # score 0.65–0.79 → no boost
]


def get_adaptive_pricing(
    value_state: str,
    intelligence_score: Optional[float] = None,
    nailed_it_rate:     Optional[float] = None,   # reserved for future use
    missed_it_rate:     Optional[float] = None,   # reserved for future use
    usage_count:        int = 0,
    session_depth:      int = 0,
    session_max_price:  int = 0,      # anti-discount guard — highest price seen this session
    experiment_variant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute adaptive price, messaging, and CTA for the current user state.

    Returns:
        price_point        int   — resolved price (39 / 49 / 59 / 79)
        price_monthly      int   — same as price_point
        price_yearly       int   — price_point × 10 (~2 months free)
        yearly_discount_pct int
        messaging          dict  — headline, subheadline, cta, value_frame, proof, urgency
        cta_variant        str   — interpolated CTA label
        state              str   — value state used
        guardrail_applied  bool  — True if anti-discount rule raised the price
        experiment_variant str
    """
    state = value_state if isinstance(value_state, str) else str(value_state)
    base_price = _STATE_BASE_PRICE.get(state, 39)

    # ── Intelligence score boost ──────────────────────────────────────────────
    if intelligence_score is not None:
        for threshold, boost in _INTEL_PRICE_BOOSTS:
            if intelligence_score >= threshold:
                base_price = _snap_to_ladder(base_price + boost)
                break

    # ── Experiment variant override ───────────────────────────────────────────
    if experiment_variant == "price_high":
        base_price = _snap_to_ladder(base_price + 10)
    elif experiment_variant == "price_low":
        base_price = _snap_to_ladder(base_price - 10)

    # ── Anti-discount guardrail (Part 16.8) ───────────────────────────────────
    guardrail_applied = False
    if base_price < session_max_price:
        base_price = session_max_price
        guardrail_applied = True

    # Last word, after every adjustment above: never surface an unchargeable price.
    base_price = _clamp_to_sellable(base_price)

    messaging = get_messaging(state, price=base_price)

    return {
        "price_point":         base_price,
        "price_monthly":       base_price,
        "price_yearly":        base_price * 10,
        "yearly_discount_pct": 17,
        "messaging":           messaging,
        "cta_variant":         messaging["cta"],
        "state":               state,
        "guardrail_applied":   guardrail_applied,
        "experiment_variant":  experiment_variant,
    }


def _snap_to_ladder(price: int) -> int:
    """Snap a price to the nearest valid price point in PRICE_LADDER."""
    return min(PRICE_LADDER, key=lambda p: abs(p - price))
