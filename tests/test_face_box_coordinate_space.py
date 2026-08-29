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

# KNOWN BUG, DELIBERATELY NOT FIXED YET -- and RE-DIAGNOSED 2026-08-29.
# The patch is preserved at docs/patches/face-box-coordinate-fix.patch.
# (The 8/27 commit said it was "preserved" and it was not; it existed nowhere.)
#
# Re-measured 2026-08-29 on a working venv. The cost reproduces EXACTLY:
#
#     without the fix : 18/34 exact, 30/34 acceptable
#     with the fix    :  8/34 exact, 17/34 acceptable
#
# TWO EARLIER DIAGNOSES WERE WRONG. Both are corrected here.
#
# WRONG #1 -- the docstring above and the original report: "an unscaled box
# clamped to the original bounds could go negative, tripping the face-box-too-
# small early return and yielding pattern=unknown".
# MEASURED: of the 14 reads the fix loses, ZERO become unknown. All 14 become a
# DIFFERENT CONFIDENT PATTERN. Nothing is tripping an early return.
#
# WRONG #2 -- the 8/27 diagnosis: "reference_read's geometry handling is
# calibrated against the broken coordinate."
# It is not a calibration. It is a COORDINATE-SPACE INCONSISTENCY, and the
# evidence is that the patched state is worse than EITHER self-consistent state:
#
#     small images, face_box unmapped (today)      18/34 exact, 30/34 acceptable
#     pre-upscaled >2048 so no mapping occurs      16/34 exact, 26/34 acceptable
#     small images, face_box mapped (the patch)     8/34 exact, 17/34 acceptable
#
# A merely mis-calibrated consumer would not be beaten by BOTH consistent
# configurations. Something is disagreeing with itself.
#
# THE ACTUAL MECHANISM. At vision_pipeline.py:1161 and :1167, `h, w` are
# REASSIGNED to the upscaled dimensions after the resize. Everything computed
# afterwards -- person_mask, skin_mask, pose, palettes, background environment --
# therefore lives in UPSCALED space. face_box lives there too, so today it AGREES
# with every mask it is compared against. The block at :1313 maps only
# catchlights and face_geometry back down.
#
# So the returned payload is already two spaces mixed together:
#     upscaled space : face_box, masks, pose, palettes
#     original space : catchlights, face_geometry
#
# The patch moves face_box alone into original space, leaving it 3x-8x out of
# agreement with the masks -- and on this corpus the disagreement is enormous:
# 33 of 34 images are below the 2048 floor and 26 of 34 currently report a
# face_box lying OUTSIDE the source image. clamshell_clean is 171x256 and
# reports [11, 410, 1339, 1738].
#
# WHAT THE REAL FIX IS. Not this patch, and not a retune. The whole returned
# payload has to be ONE space, which means auditing every pixel-valued output of
# analyze_image_regions and mapping them together -- or keeping `h, w` as the
# original dimensions and converting at the MediaPipe boundary only. Either way
# it lands as one change with its own before/after corpus gate.
#
# WORTH KNOWING SEPARATELY, and it is not a bug: a real user uploads a LARGE
# photo, which is never upscaled, so none of this fires for them. Their path is
# the middle row above. Scored on the same corpus content pre-upscaled to 2200px,
# the engine gets 16/34 exact and 26/34 acceptable -- BELOW the 18/34 and 30/34
# the public accuracy page publishes, because 33 of the 34 scored images are
# small ones. The published numbers are not wrong about the corpus; they may be
# optimistic about a customer's file. That is its own item, not this one.
#
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
