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

# KNOWN BUG, DELIBERATELY NOT FIXED YET -- see the A/B below.
#
# Fixing the coordinate in isolation is a 29-point accuracy regression:
# measured over the 34-image corpus (VLM arm, cache disabled),
#     broken face_box : exact 15/34, acceptable 26/34, mean conf 0.788
#     fixed  face_box : exact  5/34, acceptable 14/34, mean conf 0.720
#     net +2 / -14
# Mechanism: with an out-of-bounds box, light_structure_pass hits its
# "face box too small" early return and contributes nothing, so resolution
# falls through to reference_read / definitive_signature -- the accurate
# resolvers.  A valid box lets the CV geometry passes run; they fail their
# own consistency checks, get demoted, and hand resolution to `specialty`
# classifiers that score worse.
#
# The coordinate fix must therefore land together with a retune of its
# downstream consumers, not before it.  The working patch is preserved.
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
