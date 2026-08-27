"""Scored accuracy gate over the reference corpus.

Why this exists: on 2026-08-26 a face_box coordinate fix that was provably
correct in isolation (and had its own red-proofed unit test) cut corpus
accuracy from 15/34 exact to 5/34.  The full suite -- 2,641 tests -- stayed
green throughout, because nothing ran a real image end to end and asserted on
the resolved pattern.  A unit suite cannot see an accuracy regression.

Baselines below are MEASURED, not aspirational (run_vlm=False, 2026-08-26,
after ground-truth labels were remapped to canonical pattern_ids -- which
RAISED both numbers despite making acceptable_patterns stricter):
    exact       17/34
    acceptable  29/34

Lowering a baseline is a product decision, not a test fix.  If a change drops
these, either the change is wrong or the number is a deliberate trade -- say
which in the commit.
"""
import glob
import json
import os

import pytest

from engine.orchestrator import analyze_image

CORPUS = sorted(glob.glob("data/reference_dataset/*/*/image.jpg"))

# Measured 2026-08-26 over the full 34-image corpus, run_vlm=False.
BASELINE_EXACT = 17
BASELINE_ACCEPTABLE = 29

# A fast subset for the default suite. These are entries that resolved to an
# acceptable pattern at baseline, so any drop here is a real regression.
FAST_SUBSET = (
    "butterfly", "clamshell_clean", "loop_standard", "split_strong",
    "high_key", "low_key", "rembrandt_classic", "window_light_side",
)


def _truth(path):
    meta = json.load(open(os.path.join(os.path.dirname(path), "metadata.json")))
    return meta.get("ground_truth") or {}


def _acceptable(pattern, gt):
    """'unknown' inside acceptable_patterns is excluded on purpose -- otherwise
    declining to answer scores as a hit and accuracy can be faked by refusing."""
    if pattern is None:
        return False
    allowed = [a for a in (gt.get("acceptable_patterns") or []) if a != "unknown"]
    return pattern == gt.get("expected_pattern") or pattern in allowed


@pytest.mark.skipif(not CORPUS, reason="reference corpus not present")
@pytest.mark.parametrize("slug", FAST_SUBSET)
def test_known_good_entry_still_resolves(slug):
    """Each of these resolved to an acceptable pattern at baseline."""
    matches = [p for p in CORPUS if os.path.basename(os.path.dirname(p)) == slug]
    if not matches:
        pytest.skip(f"{slug} not in corpus")
    path = matches[0]
    gt = _truth(path)
    result = analyze_image(path, run_vlm=False)
    assert _acceptable(result.authoritative_pattern, gt), (
        f"{slug}: got {result.authoritative_pattern!r}, "
        f"expected {gt.get('expected_pattern')!r} or one of "
        f"{[a for a in (gt.get('acceptable_patterns') or []) if a != 'unknown']}"
    )


@pytest.mark.benchmark
@pytest.mark.skipif(not CORPUS, reason="reference corpus not present")
def test_full_corpus_accuracy_holds_baseline():
    """Full scored sweep. Deselected by default (slow); run before engine changes."""
    exact = acceptable = 0
    regressions = []
    for path in CORPUS:
        gt = _truth(path)
        pattern = analyze_image(path, run_vlm=False).authoritative_pattern
        if pattern == gt.get("expected_pattern"):
            exact += 1
        if _acceptable(pattern, gt):
            acceptable += 1
        else:
            regressions.append((os.path.basename(os.path.dirname(path)),
                                pattern, gt.get("expected_pattern")))
    detail = "\n".join(f"  {s}: got {p!r} want {w!r}" for s, p, w in regressions)
    assert exact >= BASELINE_EXACT, (
        f"exact accuracy fell: {exact} < {BASELINE_EXACT}\n{detail}")
    assert acceptable >= BASELINE_ACCEPTABLE, (
        f"acceptable accuracy fell: {acceptable} < {BASELINE_ACCEPTABLE}\n{detail}")
