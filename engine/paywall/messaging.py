"""
Messaging System — Part 16.3
Headline, subheadline, CTA, and value frame per value state.
All copy is state-aware and never optimises price in isolation.
"""
from __future__ import annotations

from typing import Any, Dict

# State-keyed messaging templates
#
# NO SOCIAL PROOF HERE, and none until it is true. Two lines were removed on
# 2026-09-03 after the stage-8 review board found them live in the paywall:
#
#   "Used by photographers who want consistent results."
#   "Photographers using NGW report 3x faster setup time."
#
# The second is a fabricated statistic. There are no users; nobody reported
# anything; no measurement of setup time has ever been taken. docs/CLAIM_LEDGER.md
# row 14 had already ruled on this class -- "Delete until true. Reinstate when a
# named photographer agrees to be quoted" -- and the sentence was reworded
# instead of deleted, which moved it out of the ledger's sight and INTO the
# paywall, the one surface where a false claim is doing commercial work.
#
# CLAUDE.md section III (SP): never present synthetic/proxy/heuristic values as
# human-confirmed truth. An adoption claim with no adopters is the plainest
# possible case. Replacements describe what the product DOES, which is checkable.
#
# test_paywall_copy_claims_nothing_about_users.py enforces this.
_MESSAGING: Dict[str, Dict[str, Any]] = {
    "low_value": {
        "headline":    "Understand your lighting",
        "subheadline": "Get precise setups — no more guessing what works.",
        "cta":         "Start for ${price}/mo",
        "value_frame": "exploration",
        "proof":       "Every read shows its evidence: catchlights, shadow geometry, ratios.",
        "urgency":     None,
    },
    "discovery": {
        "headline":    "Get consistent results",
        "subheadline": "You're learning fast — unlock the full system.",
        "cta":         "Unlock Full Access — ${price}/mo",
        "value_frame": "learning",
        "proof":       "Full blueprints. Every modifier. All 28 patterns.",
        "urgency":     None,
    },
    "success_moment": {
        "headline":    "You just nailed it — make it repeatable",
        "subheadline": "Save this exact setup. Reproduce it on every shoot.",
        "cta":         "Keep This Result — ${price}/mo",
        "value_frame": "outcome",
        "proof":       "Full blueprint: light positions, heights, power ratios, modifiers.",
        "urgency":     "Your setup is ready to save — don't lose it.",
    },
    "high_intent": {
        "headline":    "Run your shoots with confidence",
        "subheadline": "Shoot Mode. Blueprints. Every pattern — fully unlocked.",
        "cta":         "Unlock Pro — ${price}/mo",
        "value_frame": "workflow",
        "proof":       "Everything you need for every shoot, on set.",
        "urgency":     None,
    },
    "failure_tension": {
        "headline":    "Fix what went wrong — fast",
        "subheadline": "Get the exact adjustment your lighting needs right now.",
        "cta":         "Fix It Now — ${price}/mo",
        "value_frame": "fix",
        "proof":       "NGW identifies the exact problem and gives you the solution.",
        "urgency":     "Don't leave the set without getting this right.",
    },
}

_DEFAULT = _MESSAGING["low_value"]


def get_messaging(state: str, price: int = 39) -> Dict[str, Any]:
    """
    Return messaging dict for a value state with price interpolated into CTA.
    Safe to call with any state string — falls back to low_value if unknown.
    """
    template = dict(_MESSAGING.get(state, _DEFAULT))
    template["cta"]   = template["cta"].replace("${price}", f"${price}")
    template["price"] = price
    return template


def get_all_variants(price: int = 39) -> Dict[str, Dict[str, Any]]:
    """Return all messaging variants (for admin preview / dashboard)."""
    return {state: get_messaging(state, price=price) for state in _MESSAGING}
