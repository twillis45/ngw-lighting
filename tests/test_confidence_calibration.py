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
    """The vocabulary the ENGINE means by `pattern`.

    Was `data/lighting_patterns.json` — a SETUP LIBRARY, not the pattern enum.
    Checking labels against it reported 3 offenders that are perfectly valid
    engine values (projected, triangle), while the two vocabularies overlap on
    only 5 of 28 entries. A guard measuring against the wrong vocabulary
    manufactures work and hides the real thing.
    """
    from engine.enums import LightingPattern

    return {e.value for e in LightingPattern}


def _deprecated_aliases():
    """Values the enum keeps only so pre-cutover records deserialize.

    engine/enums.py marks these "REMOVE after 2026-05-06". A label that is a
    valid enum value can still be the WRONG label if it is one of these --
    golden_hour is annotated "source_context only; pattern resolved
    separately", so scoring pattern accuracy against it is a category error
    even though the value parses.
    """
    return {"rim_only", "axial", "flat_fashion", "gobo_projection",
            "golden_hour", "overcast_natural"}


def test_ground_truth_labels_are_canonical_pattern_ids():
    """Every corpus label must be a live pattern value the engine can mean.

    Two ways to fail: a value the enum does not carry at all, or a value it
    carries only as an expired migration alias.
    """
    import glob
    import os

    canon = _canonical_ids()
    expired = _deprecated_aliases()
    unknown_value, stale_alias = [], []

    for meta_path in sorted(glob.glob("data/reference_dataset/*/*/metadata.json")):
        gt = (json.load(open(meta_path)).get("ground_truth") or {})
        expected = gt.get("expected_pattern")
        slug = os.path.basename(os.path.dirname(meta_path))
        if not expected or expected == "unknown":
            continue
        if expected not in canon:
            unknown_value.append((slug, expected))
        elif expected in expired:
            stale_alias.append((slug, expected))

    assert not unknown_value, (
        f"labels the engine cannot mean at all: {unknown_value}"
    )
    # Pinned at the measured count. Lower it as labels are corrected; a rise
    # means a stale alias was reintroduced as ground truth.
    assert len(stale_alias) <= 1, (
        f"expired migration aliases used as ground truth rose to "
        f"{len(stale_alias)}: {stale_alias}"
    )
