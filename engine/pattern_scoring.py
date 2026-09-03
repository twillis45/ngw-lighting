"""One scorer, used by the engineering gate and by the page a buyer reads.

Created 2026-09-03 on review-board condition C5. There were two:

    tests/test_corpus_accuracy_gate.py::_acceptable  filtered "unknown" out of
        acceptable_patterns, then tested equality against expected_pattern
        FIRST and unfiltered
    api/routes/gallery.py::_verdict                  applied no "unknown"
        filter at all

So the number defended in engineering and the number shown to a buyer were
produced by different rules over different corpora, and nothing asserted they
described the same engine.

The first one is the interesting bug, because it defeats its own docstring:

    "'unknown' inside acceptable_patterns is excluded on purpose -- otherwise
     declining to answer scores as a hit and accuracy can be faked by refusing."

Correct intent, and the equality branch above it was never filtered. On the real
corpus entry data/reference_dataset/unknown/mixed_light_failure, whose
expected_pattern is literally "unknown", an engine that answers "unknown" --
that is, refuses to read the photograph -- scored BOTH acceptable AND exact.
The engine could earn a point by declining.

The rule here is one sentence: **an answer of "unknown" is a refusal, and a
refusal never scores**, whatever the ground truth says. Declining when there is
no evidence is correct behaviour and the decline floors exist to produce it --
but correct behaviour is not accuracy, and presenting it as accuracy is exactly
the DT guardrail (a display standing in for behavioural truth).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

#: An engine answer that means "I could not read this."
REFUSAL = "unknown"


def _allowed(gt: Dict[str, Any]) -> list:
    """acceptable_patterns with refusals removed."""
    return [a for a in (gt.get("acceptable_patterns") or []) if a != REFUSAL]


def is_exact(pattern: Optional[str], gt: Dict[str, Any]) -> bool:
    """The engine named the expected pattern. A refusal is never exact, even
    when the expected pattern IS 'unknown' -- that entry exists to record that
    the photograph cannot be read, not to hand out a point for agreeing."""
    if not pattern or pattern == REFUSAL:
        return False
    return pattern == gt.get("expected_pattern")


def is_acceptable(pattern: Optional[str], gt: Dict[str, Any]) -> bool:
    """The engine's answer falls within the human-verified range."""
    if not pattern or pattern == REFUSAL:
        return False
    return pattern == gt.get("expected_pattern") or pattern in _allowed(gt)


def is_scoreable(gt: Dict[str, Any]) -> bool:
    """Whether this entry can produce a point at all.

    An entry whose expected_pattern is a refusal has no correct answer to give,
    so it belongs in the denominator only if you are measuring something other
    than accuracy. Callers decide; this just names the condition.
    """
    return bool(gt.get("expected_pattern")) and gt.get("expected_pattern") != REFUSAL
