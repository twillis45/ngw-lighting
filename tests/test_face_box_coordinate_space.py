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
# THE AUDIT, measured 2026-08-29 on a 400x590 image (scale 3.47), by testing
# each returned value against BOTH bounds rather than by reading the code:
#
#     _img_bgr                              UPSCALED   (2048, 1388)
#     _masks.person / skin / clothing / bg  UPSCALED   (2048, 1388)
#     region_attribution.face_box           UPSCALED   [0, 92, 1388, 1671]
#     catchlights[].abs_cx / abs_cy         ORIGINAL
#     catchlights.face_geometry.*           ORIGINAL   image_size (400, 590)
#
# So the payload is not one space with one stray field. It is TWO COHERENT
# GROUPS:
#
#     raster group   (upscaled): _img_bgr, every mask, face_box
#     geometry group (original): catchlights, face_geometry
#
# face_box belongs to the raster group and AGREES with it. Any consumer pairing
# face_box with a mask or with _img_bgr is correct today -- and is exactly what
# the naive patch breaks, which is why the patch is worse than either
# self-consistent configuration. Any consumer pairing face_box with a
# catchlight is wrong today.
#
# THE FIX WAS BUILT AND MEASURED, 2026-08-29 evening.
# docs/patches/b6-unify-coordinate-space.patch -- apply with `git apply`.
#
# It does what the audit prescribed: face_box mapped down, AND the rest of the
# raster group moved with it -- the four masks via uint8/INTER_NEAREST because
# cv2.resize refuses bool, and _img_bgr via INTER_AREA, with the original
# dimensions captured before h, w are reassigned. Analysis still runs at the
# upscaled resolution; only the boundary is normalised.
#
# RESULT -- the audit was right about the mechanism:
#
#     baseline (two spaces)               18/33 exact, 30/33 acceptable
#     face_box moved ALONE (naive patch)   8/33 exact, 17/33 acceptable
#     WHOLE raster group moved            17/33 exact, 29/33 acceptable
#
# Moving the group together costs 1 and 1, not 10 and 13. The loss was never
# about the coordinate being wrong; it was about face_box leaving the group it
# agrees with.
#
# Every assertion in THIS file passes under the patch: `pytest --runxfail`
# gives 10 passed, 2 skipped (the two with no face). face_box lies inside the
# source image on every input, and the API contract that coordinates match
# image_dimensions becomes true for the first time.
#
# EXACTLY THREE READS CHANGE:
#
#     overfill_flat     flat            -> ring_light   (lost;  want flat)
#     reflector_fill    butterfly       -> loop         (FIXED; want loop)
#     window_soft_side  window_portrait -> short        (lost;  want window_portrait)
#
# reflector_fill is the entry that appears on the PUBLIC accuracy page as a
# miss. The unified space corrects it.
#
# THE TWO REGRESSIONS WERE INVESTIGATED, 2026-08-29 late. They are REAL, not
# labelling artefacts, so the tradeoff stands rather than dissolving:
#
#   overfill_flat     -> ring_light at 0.71, source "specialty:reference_read".
#                        A specialty upgrade fires on the corrected geometry.
#                        Ground truth accepts flat / high_key / clamshell, and
#                        ring_light is a distinct source, not a tonal variant.
#                        A genuine miss.
#   window_soft_side  -> short at 0.94, source "reference_read". Ground truth
#                        accepts window_portrait / loop / rembrandt /
#                        window_negative_fill -- so the corpus DOES accept
#                        face-geometry answers here, and "short" is simply not
#                        among them. A genuine miss, though a near cousin of
#                        two patterns that are accepted.
#
# reflector_fill goes the other way at 0.95, and it is correct.
#
# So the net is -1, confirmed rather than assumed, and it is a real decision
# rather than a bug waiting to be found.
#
# NOT SHIPPED, and not out of timidity. The gate asserts exact >= 18 and
# acceptable >= 30; this is 17 and 29, so it fails. Lowering a baseline to make
# a change pass is the one move that would make every future number
# meaningless, so the baseline stays and the patch waits. It needs either the
# two regressions understood, or an explicit owner ruling that correctness is
# worth one point -- a real decision, recorded, not a quiet edit.
#
# A first attempt returned 1/33 because cv2.resize rejects boolean masks and
# the pipeline threw on every image. Caught by measuring, not by reviewing.
#
# WORTH KNOWING SEPARATELY, and it is not a bug: a real user uploads a LARGE
# photo, which is never upscaled, so none of this fires for them. Scored on the
# same corpus content pre-upscaled to 2200px the engine gets 16/34 and 26/34 --
# below the 18/34 and 30/34 the public accuracy page publishes, because 33 of
# the 34 scored images are small. The published numbers are not wrong about the
# corpus; they may be optimistic about a customer's file. Its own item.
#
# NARROWED 2026-09-02. This was a FILE-level pytestmark, so all 12 tests in
# the file were xfail(strict=False) -- which means none of them could fail the
# suite in EITHER direction. A non-strict xfail that passes reports XPASS and
# is not an error, so the file produced no signal at all.
#
# Measured under --runxfail: exactly THREE tests fail, all of them in
# test_face_box_lies_inside_source_image (athletic_rim_sculpt, broad,
# butterfly). Every case of test_face_box_is_usable_by_downstream_passes
# passes. Five working gates were being masked to cover three real failures.
#
# The marker now sits on the one test that actually fails. The downstream test
# is a live gate: if the clamp starts returning a degenerate box on an image
# where it currently works, the suite goes red instead of quietly reporting
# XPASS.
#
# The three failures are the b6 item and are NOT fixed here -- the patch costs
# one point of exact accuracy and needs an owner ruling, recorded above.
_COORD_BUG = pytest.mark.xfail(
    reason="face_box coordinate bug is load-bearing; fix requires retuning "
           "the 30+ vision passes calibrated against it. Fails on 3 of 6 "
           "sampled images; see the b6 note above.",
    strict=False,
)

from engine.image_analysis import analyze_image_regions

SMALL = [f for f in sorted(glob.glob("data/reference_dataset/*/*/image.jpg"))
         if max(Image.open(f).size) < 2048]


@_COORD_BUG
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
