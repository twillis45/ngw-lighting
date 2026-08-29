"""The engine must not name a lighting pattern when it has no evidence.

Added 2026-08-29 for build item b5, "the engine can say I cannot read this."

The earlier attempt was abandoned for a good reason: the corpus holds exactly
ONE entry whose ground truth is `unknown`, and fitting a confidence cutoff to
one labelled case would have been the face_box mistake in a new costume -- a
number tuned to a measurement rather than to reality.

This test avoids that entirely. Its inputs are unreadable BY CONSTRUCTION --
random noise contains no photograph, so no labelling judgement is involved and
there is nothing to overfit to. What it asserts is a category rule, not a
threshold: "flat" is a claim about how a photograph was lit, and asserting it
about random noise is wrong in kind, not merely inaccurate.

Measured before the floor shipped:

    pure_noise            -> flat       0.0
    flat_grey             -> flat       0.0
    pure_white            -> flat       0.0
    pure_black            -> unknown    0.0
    vertical_gradient     -> loop       0.70   <- still not caught
    portrait_blurred_out  -> rembrandt  0.43   <- still not caught

and across the 33 scoreable corpus entries the minimum confidence is 0.28,
with nothing at or below 0.1 -- so a floor at 0.0 costs zero real reads.
"""
import numpy as np
import cv2
import pytest

from engine.orchestrator import analyze_image

DECLINE = {"unknown", "none", None, ""}


def _write(tmp_path, name, arr):
    p = tmp_path / f"{name}.jpg"
    cv2.imwrite(str(p), arr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return str(p)


@pytest.mark.parametrize("name", ["pure_noise", "flat_grey", "pure_white", "pure_black"])
def test_no_pattern_is_named_for_an_input_with_no_evidence(tmp_path, name):
    H, W = 900, 600
    rng = np.random.default_rng(7)
    arr = {
        "pure_noise": lambda: rng.integers(0, 256, (H, W, 3), dtype=np.uint8),
        "flat_grey":  lambda: np.full((H, W, 3), 128, np.uint8),
        "pure_white": lambda: np.full((H, W, 3), 255, np.uint8),
        "pure_black": lambda: np.zeros((H, W, 3), np.uint8),
    }[name]()
    r = analyze_image(_write(tmp_path, name, arr), run_vlm=False)
    assert r.authoritative_pattern in DECLINE, (
        f"{name} contains no lighting information, but the engine named "
        f"{r.authoritative_pattern!r} at confidence "
        f"{getattr(r, 'pattern_confidence', None)!r}"
    )


def test_the_floor_is_structural_not_fitted():
    """0.0 must mean 'no evidence' -- if a real read ever lands there the floor
    is silently discarding it, and this test is where that gets caught."""
    from tests.test_corpus_accuracy_gate import CORPUS
    if not CORPUS:
        pytest.skip("reference corpus not present")
    lows = []
    for p in CORPUS:
        c = getattr(analyze_image(p, run_vlm=False), "pattern_confidence", None)
        if isinstance(c, (int, float)) and c <= 0.1:
            lows.append((p, c))
    assert not lows, (
        "a real corpus read now sits at or below 0.1 confidence, so the decline "
        f"floor is no longer free: {lows}"
    )


@pytest.mark.xfail(strict=False, reason=(
    "KNOWN GAP, recorded rather than hidden. A vertical gradient returns 'loop' "
    "at 0.70 and a blurred-out portrait returns 'rembrandt' at 0.43. Both carry "
    "real confidence, so the 0.0 floor cannot reach them. Catching these needs a "
    "subject-presence check -- is there a face or a lit object at all -- which is "
    "separate work, not a lower threshold."))
def test_confident_nonsense_is_still_named(tmp_path):
    H, W = 900, 600
    g = np.tile(np.linspace(0, 255, H, dtype=np.uint8)[:, None], (1, W))
    r = analyze_image(_write(tmp_path, "gradient", np.dstack([g, g, g])), run_vlm=False)
    assert r.authoritative_pattern in DECLINE, (
        f"a plain gradient was read as {r.authoritative_pattern!r}")
