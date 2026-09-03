"""The paywall must not claim adoption it does not have.

Found live in production 2026-09-03 by the stage-8 review board:
    "Used by photographers who want consistent results."
    "Photographers using NGW report 3x faster setup time."

The second is a fabricated statistic -- no users exist, no setup time has ever
been measured. CLAIM_LEDGER row 14 had already ruled this class FALSE and
ordered it deleted until a named photographer agrees to be quoted; it was
reworded rather than deleted, which moved it out of the ledger's sight and into
the paywall, where it does commercial work.

This enumerates EVERY string the paywall can surface, rather than checking the
two that were found. A gate scoped to where a bug was seen is scoped to the
wrong thing.
"""
import re
import pytest

from engine.paywall.messaging import _MESSAGING

# Claims about OTHER PEOPLE using the product, or measured outcomes for them.
_ADOPTION = re.compile(
    r"\b("
    r"used by|trusted by|join(ed)?\s+\d|thousands|hundreds of|"
    r"photographers (using|who use|report|say|tell)|"
    r"our (users|customers|photographers)|"
    r"\d+\s*[x×]\s*(faster|better|quicker)|"
    r"\d+%\s+(faster|better|of (users|photographers))|"
    r"rated|reviews?\b|testimonial"
    r")",
    re.I,
)


def _every_string(obj, path="_MESSAGING"):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _every_string(v, f"{path}[{k!r}]")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _every_string(v, f"{path}[{i}]")


def test_no_paywall_string_claims_adoption():
    offenders = [
        (path, txt) for path, txt in _every_string(_MESSAGING)
        if _ADOPTION.search(txt)
    ]
    assert not offenders, "paywall copy claims users or outcomes it cannot show:\n" + "\n".join(
        f"  {p}: {t!r}" for p, t in offenders
    )


def test_the_detector_actually_detects():
    """Guards the guard: an enumerating gate whose pattern matches nothing is
    indistinguishable from a clean codebase."""
    for bad in (
        "Used by photographers who want consistent results.",
        "Photographers using NGW report 3× faster setup time.",
        "Trusted by 500 photographers",
        "Rated 4.8 by our users",
    ):
        assert _ADOPTION.search(bad), f"detector missed {bad!r}"


def test_it_does_not_flag_honest_product_description():
    for ok in (
        "Full blueprint: light positions, heights, power ratios, modifiers.",
        "Every read shows its evidence: catchlights, shadow geometry, ratios.",
        "Full blueprints. Every modifier. All 28 patterns.",
    ):
        assert not _ADOPTION.search(ok), f"false positive on {ok!r}"
