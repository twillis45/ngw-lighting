"""face_box must be reported in the source image's coordinate space.

MediaPipe needs a long edge of at least NGW_MP_MIN_DIM, so vision_pipeline
upscales smaller images before detection.  Detection results therefore come
back in the upscaled space and have to be mapped down again -- the block at
vision_pipeline.py:1315 does this for catchlights and face geometry.

face_box was missing from that block.  Downstream passes receive the ORIGINAL
image, so an unscaled box clamped to the original bounds could go negative,
tripping the "face box too small" early return in light_structure_pass and
yielding pattern="unknown" at confidence 0.1 on any image below the floor.
"""
import glob

import pytest
from PIL import Image

# KNOWN BUG, DELIBERATELY NOT FIXED YET -- and now diagnosed.
#
# Re-measured 2026-08-27 against current code (the first A/B was before the
# gobo remap and several engine changes). The cost REPRODUCES and is larger:
#
#     without the fix : 18/34 exact, 30/34 acceptable
#     with the fix    :  8/34 exact, 17/34 acceptable
#                       -10 exact,  -13 acceptable
#
# The first diagnosis was incomplete. It is not merely that a valid box lets
# light_structure_pass run and outrank better sources. Of the 14 reads the fix
# loses, SIX change answer while staying on the SAME resolver:
#
#     butterfly            butterfly -> split      [reference_read -> reference_read]
#     clamshell_clean      clamshell -> loop       [reference_read -> reference_read]
#     mixed_light_failure  loop      -> clamshell  [reference_read -> reference_read]
#
# reference_read -- the resolver carrying most of the engine's accuracy --
# concludes differently, and worse, from a CORRECT face box. Its geometry
# handling is calibrated against the broken coordinate.
#
# So the retune named in this comment is not a downstream weighting tweak. It
# is reference_read's own face-geometry handling, and it needs its own
# before/after corpus gate. The coordinate fix must land WITH that work, in
# one change, or accuracy drops by more than half.
#
# The working patch is preserved and applies cleanly with `git apply --3way`.
pytestmark = pytest.mark.xfail(
    reason="face_box coordinate bug is load-bearing; fix requires retuning "
           "the 30+ vision passes calibrated against it",
    strict=False,
)

from engine.image_analysis import analyze_image_regions

SMALL = [f for f in sorted(glob.glob("data/reference_dataset/*/*/image.jpg"))
         if max(Image.open(f).size) < 2048]


@pytest.mark.parametrize("path", SMALL[:6], ids=lambda p: p.split("/")[-2])
def test_face_box_lies_inside_source_image(path):
    w, h = Image.open(path).size
    ra = (analyze_image_regions(path, return_masks=False) or {}).get("region_attribution") or {}
    fb = ra.get("face_box")
    if fb is None:
        pytest.skip("no face detected")
    x0, y0, x1, y1 = fb
    assert 0 <= x0 < x1 <= w, f"x extent {x0}..{x1} outside source width {w}"
    assert 0 <= y0 < y1 <= h, f"y extent {y0}..{y1} outside source height {h}"


@pytest.mark.parametrize("path", SMALL[:6], ids=lambda p: p.split("/")[-2])
def test_face_box_is_usable_by_downstream_passes(path):
    """The clamp that light_structure_pass applies must leave a real box."""
    w, h = Image.open(path).size
    ra = (analyze_image_regions(path, return_masks=False) or {}).get("region_attribution") or {}
    fb = ra.get("face_box")
    if fb is None:
        pytest.skip("no face detected")
    x0, y0, x1, y1 = fb
    fw = min(x1, w) - max(0, x0)
    fh = min(y1, h) - max(0, y0)
    assert fw >= 20 and fh >= 20, f"clamped box {fw}x{fh} trips the 'too small' early return"
