"""run_vlm=False must disable the VLM only -- never the CV pipeline.

engine/image_analysis.py gated a single 109-line block on
`describe_mode == "vision" and run_vlm`.  That block holds BOTH the VLM
future and analyze_image_regions() -- the entire CV pipeline (MediaPipe,
masks, face_box, catchlights, cue extraction).  The block's own comment
says the two are "completely independent", but the shared condition meant
run_vlm=False silently returned an empty analysis rather than a CV-only one.

VL guardrail: the VLM is hinting, not ground truth.  A build where the CV
cannot run without it has that backwards.
"""
import os

import pytest

from engine.image_analysis import describe_image
from engine.orchestrator import analyze_image

IMAGE = "data/reference_dataset/rembrandt/rembrandt_classic/image.jpg"

pytestmark = pytest.mark.skipif(
    not os.path.exists(IMAGE), reason="reference corpus not present"
)


def test_cv_pipeline_runs_with_vlm_disabled():
    out = describe_image(IMAGE, "vision", run_vlm=False)
    vision = out.get("vision") or {}
    assert vision.get("ok"), "vision block absent -- the CV pipeline did not run"
    ra = vision.get("region_attribution") or {}
    assert ra.get("face_box") is not None, "no face_box -- CV pipeline did not run"
    assert out.get("cue_report"), "no cue_report -- cue extraction did not run"


def test_vlm_disabled_reports_no_description_and_no_false_error():
    out = describe_image(IMAGE, "vision", run_vlm=False)
    assert out.get("vlm_description") is None
    # Skipping the VLM deliberately is not a misconfiguration.
    assert not out.get("_vlm_error"), f"spurious error: {out.get('_vlm_error')}"


def test_orchestrator_produces_analysis_without_vlm():
    r = analyze_image(IMAGE, run_vlm=False)
    assert r.vision_data, "vision_data empty -- no analysis ran at all"
