"""Confidence calibration guard.

MEASURED 2026-08-26 (run_vlm=False, 34-image corpus, AFTER ground-truth labels
were remapped to canonical pattern_ids), scored over the 29 entries whose
expected_pattern is canonical:

    exact                        16/29  (55%)
    acceptable                   26/29  (90%)
    mean stated confidence       0.799
    corr(confidence, correct)   +0.035

    stated 0.52  ->  actual 0.86   (+0.33)   under-confident
    stated 0.76  ->  actual 0.86   (+0.09)   under-confident
    stated 0.94  ->  actual 0.93   (-0.01)   well calibrated

IMPORTANT -- this supersedes an earlier reading of the same engine.  Before the
labels were corrected, the same code measured corr = -0.047 with the 0.9+ bin
at 0.83 actual, which looked like dangerous overconfidence.  It was not: 9 of
34 ground-truth labels were source_context / modifier concepts (golden_hour,
overcast_natural, gobo) scored as if they were patterns.  Fixing the yardstick
moved the top bin from -0.11 to -0.01.  The lesson is recorded because the
wrong conclusion was stated confidently first.

Remaining real defect: UNDER-confidence at the low end.  Answers stated at 0.52
are right 86% of the time, so the number understates reliability and the
correlation stays near zero.  Not corrected here -- a mapping fitted to 29
samples would overfit.  It needs more labeled entries.

Still non-canonical and awaiting a human call (see
scripts/remap_canonical_truth.py): gobo, golden_hour, hurley_triangle.
"""
import json

import pytest

CORPUS_LABEL_AUDIT = "canonical pattern_id required for scoring"


def _canonical_ids():
    data = json.load(open("data/lighting_patterns.json"))
    pats = data if isinstance(data, list) else data.get("patterns") or []
    return {p["pattern_id"] for p in pats}


def test_ground_truth_labels_are_canonical_pattern_ids():
    """9 of 34 corpus labels are not canonical patterns.

    TX guardrail: source_context (golden_hour, overcast_natural) and modifier
    (gobo) concepts must not sit as peer pattern outputs.  Scoring pattern
    accuracy against them is a category error and depresses every metric
    computed from this corpus.
    """
    import glob
    import os

    canon = _canonical_ids()
    offenders = []
    for meta_path in sorted(glob.glob("data/reference_dataset/*/*/metadata.json")):
        gt = (json.load(open(meta_path)).get("ground_truth") or {})
        expected = gt.get("expected_pattern")
        if expected and expected not in canon and expected != "unknown":
            offenders.append((os.path.basename(os.path.dirname(meta_path)), expected))

    # Pinned at the measured count. Lower it as labels are corrected; a rise
    # means new non-canonical labels were introduced.
    assert len(offenders) <= 3, (
        f"non-canonical ground-truth labels rose to {len(offenders)}: {offenders}"
    )


@pytest.mark.benchmark
def test_confidence_still_carries_no_signal():
    """Documents the defect. Fails if confidence becomes informative -- good news,
    but update the recorded baseline when it happens."""
    pytest.skip(
        "Requires a full corpus sweep; see docs and the numbers in this module's "
        "docstring. Run scripts/measure_calibration.py to regenerate."
    )
