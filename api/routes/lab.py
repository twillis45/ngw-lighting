"""Lab API routes — protected by dev email whitelist.

Provides:
- Dev access check
- Full-fidelity image analysis (workbench)
- Gold set CRUD
- Rule candidate CRUD
- Batch evaluation
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import shutil
import threading
import time
import uuid
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.utils.upload_naming import canonical_upload_name

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response as FastAPIResponse
from pydantic import BaseModel, Field

from auth.dev_guard import get_dev_user
from auth.security import get_optional_user
from auth.rate_limit import check_rate_limit
from engine.request_context import set_request_context, clear_request_context
from db.database import (
    DATA_DIR,
    get_db,
    create_gold_set_entry,
    get_gold_set_entries,
    get_gold_set_entry,
    update_gold_set_entry,
    delete_gold_set_entry,
    create_rule_candidate,
    get_rule_candidates,
    get_rule_candidate,
    update_rule_candidate,
    delete_rule_candidate,
    log_admin_change,
    get_admin_changelog,
)

router = APIRouter(prefix="/lab", tags=["lab"])

#: Customer-facing analysis. Mounted at /api, NOT /api/lab.
#: The Studio shell's only analyse path used to be /api/lab/analyze, which is
#: get_dev_user — so a paying customer could not analyse a photo at all. These
#: are the SAME handler functions, re-mounted; there is deliberately no second
#: implementation to drift from.
analyze_router = APIRouter(tags=["analyze"])


def is_admin_or_dev(email: Optional[str]) -> bool:
    """True for accounts that are not customers.

    Reuses get_internal_emails() — the same set that excludes a session from
    metrics, cohorts and conversion — so "who is internal" has one definition.
    """
    if not email:
        return False
    from db.provenance import get_internal_emails
    return email.strip().lower() in get_internal_emails()

UPLOAD_DIR = DATA_DIR / "uploads" / "lab"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
#: Default 90s, not 180s, because Cloudflare sits in front of Render in
#: production (verified: `server: cloudflare`, cf-ray on every response) and its
#: default origin timeout is 100s. At 180s an analysis between 100s and 180s
#: returned a Cloudflare 524 to the caller while this server kept working and
#: succeeded — a confusing gateway error instead of an honest one. Failing at 90s
#: means the 504 below is ours, and says something useful.
#: Measured Aug 26 2026 on an M3 Max: CV-only 0.7s, full pipeline with VLM 28.1s.
#: Render's standard plan is slower, so 90s leaves real headroom; raise
#: NGW_ANALYSIS_TIMEOUT only alongside a Cloudflare origin-timeout increase.
ANALYSIS_TIMEOUT_SECONDS = int(os.getenv("NGW_ANALYSIS_TIMEOUT", "90"))

# ── In-flight analysis tracking (cancel support) ─────────────
_inflight_lock = threading.Lock()
_inflight: Dict[str, asyncio.Future] = {}   # analysis_id → Future
_cancelled: set[str] = set()                # analysis_ids that were cancelled
_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tiff", ".tif"}
_ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "image/heic", "image/heif", "image/tiff",
}


def _extract_exif(image_bytes: bytes) -> Dict[str, Any]:
    """Extract photographer-relevant EXIF metadata from image bytes.

    Returns a dict with shutter, aperture, iso, focal_length, camera_body,
    lens_model — all strings formatted for display. Missing fields are None.
    """
    try:
        from PIL import Image as PILImage
        from PIL.ExifTags import TAGS, GPSTAGS
        import io

        img = PILImage.open(io.BytesIO(image_bytes))
        exif_raw = img._getexif()
        if not exif_raw:
            return {}

        # Build tag-name lookup
        decoded = {}
        for tag_id, value in exif_raw.items():
            tag_name = TAGS.get(tag_id, tag_id)
            decoded[tag_name] = value

        result: Dict[str, Any] = {}

        # Aperture (FNumber)
        fn = decoded.get("FNumber")
        if fn:
            val = float(fn) if not hasattr(fn, "numerator") else fn.numerator / fn.denominator
            result["aperture"] = f"f/{val:.1f}" if val != int(val) else f"f/{int(val)}"

        # Shutter speed (ExposureTime)
        et = decoded.get("ExposureTime")
        if et:
            if hasattr(et, "numerator"):
                num, den = et.numerator, et.denominator
                if num and den and num < den:
                    result["shutter"] = f"1/{den // num}s"
                elif num and den:
                    result["shutter"] = f"{num / den:.1f}s"
            else:
                val = float(et)
                if val < 1:
                    result["shutter"] = f"1/{int(round(1 / val))}s"
                else:
                    result["shutter"] = f"{val:.1f}s"

        # ISO
        iso = decoded.get("ISOSpeedRatings")
        if iso:
            result["iso"] = str(iso) if not isinstance(iso, (list, tuple)) else str(iso[0])

        # Focal length
        fl = decoded.get("FocalLength")
        if fl:
            val = float(fl) if not hasattr(fl, "numerator") else fl.numerator / fl.denominator
            result["focal_length"] = f"{int(val)}mm" if val == int(val) else f"{val:.1f}mm"

        # Camera body (Make + Model)
        make = decoded.get("Make", "").strip()
        model = decoded.get("Model", "").strip()
        if model:
            # Many cameras prepend make into model (e.g. "Canon" + "Canon EOS R5")
            if make and model.lower().startswith(make.lower()):
                result["camera_body"] = model
            elif make:
                result["camera_body"] = f"{make} {model}"
            else:
                result["camera_body"] = model

        # Lens model
        lens = decoded.get("LensModel", "").strip()
        if lens:
            result["lens"] = lens

        # White balance
        wb = decoded.get("WhiteBalance")
        if wb is not None:
            result["white_balance"] = "Auto" if wb == 0 else "Manual"

        # Flash
        flash = decoded.get("Flash")
        if flash is not None:
            result["flash_fired"] = bool(flash & 0x01) if isinstance(flash, int) else False

        return result
    except Exception:
        return {}


async def _validate_upload(upload: UploadFile) -> bytes:
    """Read file contents and validate size + MIME type. Returns raw bytes."""
    content = await upload.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )
    ext = Path(upload.filename or "image.jpg").suffix.lower()
    ct = (upload.content_type or "").split(";")[0].strip().lower()
    if ext not in _ALLOWED_IMAGE_EXTS and ct not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext or ct}'. Please upload a JPEG, PNG, WebP, HEIC, or TIFF image.",
        )
    return content


# ── Models ────────────────────────────────────────────────

class GoldSetCreate(BaseModel):
    image_path: str
    expected_analysis: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    status: str = "draft"         # draft | approved | archived | rejected
    setup_family: Optional[str] = None   # SetupFamily machine value
    provenance: Optional[str] = None     # SP-001: source/rights provenance


class GoldSetUpdate(BaseModel):
    expected_analysis: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    setup_family: Optional[str] = None   # SetupFamily machine value
    provenance: Optional[str] = None     # SP-001: source/rights provenance


class RuleCandidateCreate(BaseModel):
    title: str
    description: str
    rationale: Optional[str] = None
    source_gold_set_id: Optional[str] = None
    source_image_path: Optional[str] = None
    proposed_change: Dict[str, Any] = Field(default_factory=dict)
    status: str = "proposed"  # proposed | accepted | rejected | implemented


class RuleCandidateUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    rationale: Optional[str] = None
    source_image_path: Optional[str] = None
    proposed_change: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


# ── Status / Access Check ─────────────────────────────────

@router.get("/status")
async def lab_status(user: Dict = Depends(get_dev_user)):
    """Check dev access. Returns 200 if authorized, 403 otherwise."""
    return {
        "status": "ok",
        "user": user.get("email"),
        "lab_version": "0.1.0",
    }


# ── Fast face preflight — returns face_box + catchlights in <2s ─────────

# ── PUBLIC ROUTE — the one exception in this router ──────────
# Every other /lab route is curator-only via get_dev_user. This one is not:
# the customer-facing Studio shell calls it to drive the processing animation
# (ui/src/screens/studio/_core/useLightingRead.js), and that fetch carries no
# Authorization header, so a gated dependency returns 401 before the paywall is
# ever evaluated. It is CV-only — no VLM, no pipeline, no DB write — and stays
# rate-limited below. Do NOT copy this pattern to a new /lab route.
@router.post("/face-preflight")
async def lab_face_preflight(
    request: Request,
    image: UploadFile = File(...),
    user: Optional[Dict] = Depends(get_optional_user),
):
    """Fast CV-only pass: face bounding box + catchlight positions.

    Runs analyze_image_regions (no VLM, no full pipeline) and returns
    face geometry data for the processing animation overlay. Designed
    to complete in <2s so the animation can start with real data while
    the full analysis continues in parallel.
    """
    check_rate_limit("lab_face_preflight", request, limit=20, window=60)
    content = await _validate_upload(image)

    import tempfile, os, math
    from PIL import Image as PILImage
    from engine.image_analysis import analyze_image_regions
    from engine.vision_pipeline import _MODEL_DIR, _make_mp_image
    import mediapipe as mp

    # Write temp file
    ext = Path(image.filename or "image.jpg").suffix.lower() or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=str(UPLOAD_DIR)) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        vision = analyze_image_regions(tmp_path, return_masks=False)

        if not vision.get("ok"):
            return {"ok": False, "error": "Face detection failed"}

        ra = vision.get("region_attribution", {})
        face_box = ra.get("face_box")  # [x0, y0, x1, y1] in pixels

        # Get actual image dimensions
        pil_img = PILImage.open(tmp_path)
        img_w, img_h = pil_img.size

        # Catchlight positions
        cl_data = vision.get("catchlight", {}) or vision.get("catchlights", {})
        catchlights = []
        if isinstance(cl_data, dict):
            for cl in cl_data.get("catchlights", []):
                catchlights.append({
                    "eye": cl.get("eye"),
                    "position": cl.get("position"),
                    "abs_cx": cl.get("abs_cx"),
                    "abs_cy": cl.get("abs_cy"),
                    "intensity": cl.get("intensity"),
                    "shape": cl.get("shape"),
                })

        # face_box is in the engine's internal resolution (often upscaled).
        # Detect the scale factor and normalize everything to 0→1.
        face_box_norm = None
        if face_box:
            # The engine upscales small images. face_box coords may exceed
            # original img dimensions. Infer the internal resolution from
            # the face_box extents vs image size.
            internal_w = max(img_w, face_box[2] + 1)
            internal_h = max(img_h, face_box[3] + 1)
            # Better: check region_attribution for the actual processed dims
            ra_w = ra.get("_image_w", 0)
            ra_h = ra.get("_image_h", 0)
            if ra_w > 0: internal_w = ra_w
            if ra_h > 0: internal_h = ra_h

            face_box_norm = {
                "x": face_box[0] / internal_w,
                "y": face_box[1] / internal_h,
                "w": (face_box[2] - face_box[0]) / internal_w,
                "h": (face_box[3] - face_box[1]) / internal_h,
            }

        # Normalize catchlight positions — abs_cx/abs_cy appear to be in
        # ORIGINAL image resolution, not the upscaled internal resolution.
        # Try original first; if values are > 1.0, switch to internal.
        for cl in catchlights:
            if cl.get("abs_cx") is not None and img_w and img_h:
                nx = cl["abs_cx"] / img_w
                ny = cl["abs_cy"] / img_h
                # Sanity: if > 1 these must be in upscaled space
                if nx > 1.0 or ny > 1.0:
                    int_w = internal_w if face_box else img_w
                    int_h = internal_h if face_box else img_h
                    nx = cl["abs_cx"] / int_w
                    ny = cl["abs_cy"] / int_h
                cl["nx"] = nx
                cl["ny"] = ny

        # ── Extract face mesh landmarks for precise positioning ──
        landmarks = {}
        try:
            import cv2
            import numpy as np
            face_lm_model = _MODEL_DIR / "face_landmarker.task"
            if face_lm_model.exists():
                img_cv = cv2.imread(tmp_path)
                if img_cv is not None:
                    fh, fw = img_cv.shape[:2]
                    img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
                    mp_img = _make_mp_image(img_rgb)

                    lm_opts = mp.tasks.vision.FaceLandmarkerOptions(
                        base_options=mp.tasks.BaseOptions(model_asset_path=str(face_lm_model)),
                        running_mode=mp.tasks.vision.RunningMode.IMAGE,
                        num_faces=1,
                    )
                    landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(lm_opts)
                    try:
                        lm_res = landmarker.detect(mp_img)
                    finally:
                        landmarker.close()

                    if lm_res.face_landmarks:
                        lm = lm_res.face_landmarks[0]
                        # Key landmark indices (MediaPipe 478-point face mesh):
                        LM_MAP = {
                            'nose_tip':    4,    # tip of nose (more accurate than 1)
                            'nose_bridge': 6,    # between eyes
                            'nose_bottom': 2,    # bottom of nose (septum area)
                            'forehead':    10,
                            'chin':        152,
                            'mouth_top':   13,
                            'mouth_bot':   14,
                            'left_eye':    468,  # iris center
                            'right_eye':   473,  # iris center
                            'left_jaw':    234,
                            'right_jaw':   454,
                            'left_cheek':  123,
                            'right_cheek': 352,
                            'left_brow':   70,   # left eyebrow center
                            'right_brow':  300,  # right eyebrow center
                        }
                        for name, idx in LM_MAP.items():
                            if idx < len(lm):
                                landmarks[name] = {
                                    'x': lm[idx].x,  # 0→1 normalized
                                    'y': lm[idx].y,
                                }
        except Exception as e:
            landmarks = {"error": str(e)}

        return {
            "ok": True,
            "image_size": {"w": img_w, "h": img_h},
            "face_box": face_box,
            "face_box_norm": face_box_norm,
            "catchlights": catchlights,
            "landmarks": landmarks,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Workbench: Full-fidelity Analysis ─────────────────────

@analyze_router.post("/analyze")
async def lab_analyze(
    request: Request,
    image: UploadFile = File(...),
    debug: bool = Query(False, description="Generate debug overlay image (internal only)"),
    delete_after: bool = Query(False, description="Delete uploaded image after analysis (privacy mode)"),
    sensitivity: str = Query("balanced", description="Pattern sensitivity: strict, balanced, flexible"),
    user: Optional[Dict] = Depends(get_optional_user),
):
    """Run full pipeline analysis on an uploaded image.

    Requires a signed-in account: the analysis meter and the free-tier
    allowance are keyed on a user id, and an anonymous caller cannot be
    metered. ``debug=true`` returns complete model dumps and is restricted
    to internal accounts.


    Returns complete model dumps for debugging/review.
    When debug=True, also generates a visual debug overlay showing
    all detected signals and returns the overlay URL.
    """
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in to analyze a photo.",
        )
    # debug=true returns complete model dumps — curator/dev material, never a customer's.
    # debug=true returns complete model dumps — curator/dev material, never a customer's.
    if debug and not is_admin_or_dev(user.get("email")):
        raise HTTPException(
            status_code=403,
            detail="debug output is restricted to internal accounts.",
        )
    check_rate_limit("lab_analyze", request, limit=10, window=60)
    content = await _validate_upload(image)
    # Save uploaded file with canonical name — original filename preserved separately
    original_filename = image.filename or "image.jpg"
    fname = canonical_upload_name(original_filename, origin="lab")
    fpath = UPLOAD_DIR / fname

    with open(fpath, "wb") as f:
        f.write(content)

    # ── EXIF extraction — pull photographer-relevant camera data ──
    exif_data = _extract_exif(content)

    # Run full analysis pipeline via orchestrator (in thread — CPU-bound)
    try:
        from engine.orchestrator import analyze_image

        # Set request context so all downstream log lines include user/session IDs
        set_request_context(
            user_id=user.get("id") or user.get("sub"),
            user_email=user.get("email"),
            session_id=None,  # Lab workbench has no session_id
        )

        # Generate analysis_id up-front so the client can cancel by id
        analysis_id = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None,
            partial(analyze_image, str(fpath), run_extended=True, run_vlm=True, debug=debug,
                    analysis_id_override=analysis_id,
                    sensitivity=sensitivity if sensitivity in ('strict', 'balanced', 'flexible') else 'balanced'),
        )

        # Register in-flight task for cancellation
        with _inflight_lock:
            _inflight[analysis_id] = future

        try:
            ar = await asyncio.wait_for(future, timeout=ANALYSIS_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            future.cancel()
            raise HTTPException(
                status_code=504,
                detail=f"Analysis timed out after {ANALYSIS_TIMEOUT_SECONDS}s. "
                       "Try again, or use a smaller image.",
            )
        except asyncio.CancelledError:
            raise HTTPException(status_code=499, detail="Analysis cancelled.")
        finally:
            with _inflight_lock:
                _inflight.pop(analysis_id, None)
                _cancelled.discard(analysis_id)
            clear_request_context()

        if not ar.ok:
            raise HTTPException(status_code=500, detail="; ".join(ar.notes))

        # ── Sentry context — attach pattern/confidence to this request scope ──
        try:
            import sentry_sdk as _sentry
            _sentry.set_tag("pattern", ar.authoritative_pattern or "unknown")
            _sentry.set_tag("confidence_label", getattr(ar, "pattern_confidence_label", "weak"))
            _sentry.set_context("analysis", {
                "analysis_id": analysis_id,
                "pattern": ar.authoritative_pattern or "unknown",
                "confidence": getattr(ar, "pattern_confidence", 0.0),
                "source": getattr(ar, "authoritative_pattern_source", "none"),
                "needs_review": bool(
                    getattr(getattr(ar, "pattern_candidates", None), "needs_review", False)
                ),
            })
        except Exception:
            pass

        # ── Debug overlay generation (diagnostic only) ──
        debug_overlay_url = None
        if debug and ar.pipeline_results is not None:
            try:
                from engine.vision_debug import generate_analysis_overlay

                img_bgr = ar.debug_data.get("img_bgr")
                face_box = ar.debug_data.get("face_box")
                masks = ar.debug_data.get("masks", {})
                person_mask = masks.get("person") if isinstance(masks, dict) else None

                overlay_stem = f"overlay_{fpath.stem}_{uuid.uuid4().hex[:8]}"
                overlay_filename = f"{overlay_stem}.jpg"
                overlay_path = Path("static/debug") / overlay_filename

                # Extract classified catchlights (with roles) from lighting intelligence
                _li_for_overlay = ar.lighting_intel
                _ci_for_overlay = getattr(_li_for_overlay, "catchlight_intelligence", None) or {}
                _intel_cls = (
                    _ci_for_overlay.get("catchlights", [])
                    if isinstance(_ci_for_overlay, dict) else []
                )

                saved_path = generate_analysis_overlay(
                    img_bgr,
                    ar.pipeline_results,
                    face_box=face_box,
                    person_mask=person_mask,
                    output_path=str(overlay_path),
                    vision_data=ar.vision_data,
                    intel_catchlights=_intel_cls,
                )
                if saved_path:
                    debug_overlay_url = f"/static/debug/{overlay_filename}"

                    # ── Sidecar JSON — enables per-layer overlay regeneration ──
                    # Stores all data needed to regenerate the overlay with any
                    # subset of layers, without re-running the full pipeline.
                    try:
                        import json as _json
                        import numpy as _np

                        def _json_safe(obj):
                            """Recursively convert non-serializable values."""
                            if isinstance(obj, _np.ndarray):
                                return None  # arrays are too large; skip
                            if isinstance(obj, dict):
                                return {k: _json_safe(v) for k, v in obj.items()}
                            if isinstance(obj, (list, tuple)):
                                return [_json_safe(v) for v in obj]
                            if isinstance(obj, _np.generic):
                                return obj.item()
                            return obj

                        sidecar = {
                            "pipeline_results": _json_safe(ar.pipeline_results),
                            "face_box": face_box,
                            # vision_catchlights: full MediaPipe catchlight data (face_geometry +
                            # per-catchlight list) — required for catchlight dot overlay on regen.
                            "vision_catchlights": _json_safe(
                                ar.vision_data.get("catchlights") if ar.vision_data else None
                            ),
                            # intel_catchlights: role-classified catchlights from lighting_inference
                            # (each has eye, position, role) — drives key/fill color-coding on regen.
                            "intel_catchlights": _json_safe(_intel_cls),
                            # person_mask is a numpy array — too large; skip.
                            # Highlight heatmap layer won't have person mask on regen,
                            # but all other layers are unaffected.
                        }
                        sidecar_path = Path("static/debug") / f"{overlay_stem}.json"
                        sidecar_path.write_text(_json.dumps(sidecar, default=str))

                        # ── Source image snapshot — critical for layer regen ──
                        # Save the original (un-annotated) image so the regenerate
                        # endpoint always has a clean base to draw on.
                        # Primary: re-encode from the numpy img_bgr in debug_data.
                        # Fallback: copy the original upload file directly — this
                        # is identical quality and works even if img_bgr is None.
                        src_path = Path("static/debug") / f"{overlay_stem}_src.jpg"
                        if img_bgr is not None:
                            import cv2 as _cv2_src
                            ok = _cv2_src.imwrite(str(src_path), img_bgr, [_cv2_src.IMWRITE_JPEG_QUALITY, 95])
                            if not ok:
                                # cv2 write failed — fall back to copying the upload
                                import shutil as _shutil
                                _shutil.copy2(str(fpath), str(src_path))
                        else:
                            # img_bgr not in debug_data — copy the original upload
                            import shutil as _shutil
                            _shutil.copy2(str(fpath), str(src_path))
                    except Exception as _se:
                        import logging as _log
                        _log.getLogger(__name__).warning("Sidecar/src write failed (layer regen will not work): %s", _se)

            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Debug overlay failed: %s", exc)

        # Serialize VLM description for comparison view
        vlm_data = None
        vlm_desc = ar.vlm_description
        if vlm_desc and getattr(vlm_desc, "ok", False):
            vlm_data = vlm_desc.model_dump() if hasattr(vlm_desc, "model_dump") else vlm_desc.__dict__

        # Check VLM availability so UI can show button state
        try:
            from engine.vlm import vlm_available as _vlm_available
            vlm_is_available = _vlm_available()
        except Exception:
            vlm_is_available = False

        # Serialize CV vision data (strip numpy arrays)
        cv_data = {k: v for k, v in ar.vision_data.items() if not k.startswith("_")}

        # Lighting inference data — LightingInference is a plain @dataclass (not Pydantic).
        # Read fields explicitly by attribute name — more reliable than vars() or model_dump().
        import logging as _log
        _li_log = _log.getLogger(__name__)
        _li = ar.lighting_intel
        if _li is not None:
            lighting_data = {
                "pattern":                       getattr(_li, "pattern", "unknown"),
                "pattern_confidence":            getattr(_li, "pattern_confidence", 0.0),
                "key_position_text":             getattr(_li, "key_position_text", ""),
                "key_side":                      getattr(_li, "key_side", "unknown"),
                "modifier_family":               getattr(_li, "modifier_family", None),
                "modifier_confidence":           getattr(_li, "modifier_confidence", 0.0),
                "light_count":                   getattr(_li, "light_count", 0),
                "fill_method_text":              getattr(_li, "fill_method_text", ""),
                "detected_mood":                 getattr(_li, "detected_mood", None),
                "mood_confidence":               getattr(_li, "mood_confidence", 0.0),
                "detected_skin_tone":            getattr(_li, "detected_skin_tone", None),
                "skin_tone_confidence":          getattr(_li, "skin_tone_confidence", 0.0),
                "background_light_detected":     getattr(_li, "background_light_detected", False),
                "background_light_confidence":   getattr(_li, "background_light_confidence", 0.0),
                "detected_cct_kelvin":           getattr(_li, "detected_cct_kelvin", None),
                "detected_distance_class":       getattr(_li, "detected_distance_class", None),
                "detected_environment":          getattr(_li, "detected_environment", None),
                "notes":                         getattr(_li, "notes", []),
                "catchlight_intelligence":       getattr(_li, "catchlight_intelligence", None),
                # Shadow penumbra apparent source size — available even without catchlights.
                # "point" | "small" | "medium" | "large" | "very_large" | None
                "penumbra_source_size": (
                    (ar.pipeline_results or {}).get("penumbra", {}).get("apparent_source_size")
                    if ar.pipeline_results else None
                ),
            }
            _li_log.info(
                "lighting_intel: pattern=%s conf=%.2f key_pos=%r modifier=%s light_count=%s",
                lighting_data["pattern"], lighting_data["pattern_confidence"],
                lighting_data["key_position_text"], lighting_data["modifier_family"],
                lighting_data["light_count"],
            )
        else:
            # lighting_intel is None — infer_lighting_from_vision failed or was skipped.
            # Fallback: use authoritative_pattern from the top-level result (always set).
            _li_log.warning(
                "ar.lighting_intel is None — lighting_inference skipped. notes=%s", ar.notes
            )
            lighting_data = {
                "pattern":            ar.authoritative_pattern or "unknown",
                "pattern_confidence": getattr(ar, "pattern_confidence", 0.0),
                "key_position_text":  "",
                "modifier_family":    None,
                "light_count":        0,
            }

        # Solver result (new — enrichment from solver chain)
        solver_data = None
        if ar.solver_result and hasattr(ar.solver_result, "model_dump"):
            solver_data = ar.solver_result.model_dump()

        # Extract reconstruction + edge_case_flags from pipeline_results for the UI
        pipeline_recon = None
        pipeline_edge_flags = None
        if ar.pipeline_results:
            recon_pass = ar.pipeline_results.get("reconstruction", {})
            if recon_pass.get("ok"):
                pipeline_recon = {k: v for k, v in recon_pass.items() if k != "ok"}
            edge_flags = ar.pipeline_results.get("edge_case_flags")
            if edge_flags:
                pipeline_edge_flags = edge_flags if isinstance(edge_flags, dict) else {}

        # Also pull edge_case_flags from the AnalysisResult dataclass if available
        if pipeline_edge_flags is None and ar.edge_case_flags is not None:
            pipeline_edge_flags = (
                ar.edge_case_flags.model_dump()
                if hasattr(ar.edge_case_flags, "model_dump")
                else vars(ar.edge_case_flags)
            )

        # ── Signal diagnostics — catchlight clock positions + key signal values ──
        # Surfaces the deduped inputs to pattern gates so classification
        # decisions can be inspected in the Lab Workbench.
        signal_diagnostics: Dict[str, Any] = {}
        try:
            # ── Catchlights: prefer deduped reflection_architecture ──────
            # Raw catchlight lists include floor bounces, jewellery
            # reflections, and proximity duplicates.  Show the deduped
            # count the pipeline actually uses for pattern gates, with the
            # raw count for context.
            _cl_raw = ar.vision_data.get("catchlights", {})
            _cl_list = _cl_raw.get("catchlights", []) if _cl_raw.get("ok") else []
            _raw_count = len(_cl_list)

            # Build clock-position table from raw list (for dedup filtering)
            def _build_entry(_c):
                _pos = _c.get("position", "")
                try:
                    _hour = int(_pos.split()[0]) if _pos else None
                except Exception:
                    _hour = None
                _quad = None
                if _hour is not None:
                    if _hour in (10, 11): _quad = "upper_left"
                    elif _hour in (1, 2): _quad = "upper_right"
                    elif _hour == 12: _quad = "top_center"
                    elif _hour == 3: _quad = "hard_right"
                    elif _hour == 9: _quad = "hard_left"
                    elif 4 <= _hour <= 8: _quad = "lower"
                return {
                    "eye": _c.get("eye"),
                    "position": _pos,
                    "hour": _hour,
                    "quad": _quad,
                    "shape": _c.get("shape"),
                    "size_ratio": _c.get("size_ratio"),
                }

            # Use reflection_architecture deduped data when available
            _cr_diag = getattr(ar, "cue_report", None)
            _ra_diag = getattr(_cr_diag, "reflection_architecture", None) if _cr_diag else None
            if _ra_diag and _ra_diag.total_catchlights < _raw_count:
                # Show deduped summary — filter raw list to keep only the
                # brightest per clock-position group (same logic as dedup).
                # Group by (eye, clock-hour ±1) and keep highest size_ratio.
                _seen: Dict[str, dict] = {}
                for _c in _cl_list:
                    _entry = _build_entry(_c)
                    _h = _entry.get("hour")
                    _e = _entry.get("eye", "?")
                    if _h is None:
                        continue
                    # Skip floor bounces (5-7 o'clock) when 3+ raw exist
                    if _raw_count >= 3 and 5 <= _h <= 7:
                        continue
                    # Skip hard-left/right jewellery risk
                    if _entry.get("quad") in ("hard_left", "hard_right"):
                        continue
                    # Group by eye + clock zone (±1 hour = same source)
                    _zone = f"{_e}_{_h // 2}"
                    _existing = _seen.get(_zone)
                    if _existing is None or (_entry.get("size_ratio") or 0) > (_existing.get("size_ratio") or 0):
                        _seen[_zone] = _entry
                _deduped_table = list(_seen.values())
                signal_diagnostics["catchlights"] = _deduped_table
                signal_diagnostics["catchlight_summary"] = {
                    "raw_count": _raw_count,
                    "deduped_count": _ra_diag.total_catchlights,
                    "displayed_count": len(_deduped_table),
                    "per_eye": _ra_diag.per_eye_counts,
                    "symmetry": round(_ra_diag.symmetry_score, 2),
                    "dedup_note": _ra_diag.notes[0] if _ra_diag.notes else None,
                    "filtered": [
                        "floor_bounces (5-7 o'clock)",
                        "jewellery_risk (3/9 o'clock)",
                        "proximity_duplicates",
                    ],
                }
            else:
                # No dedup available or no reduction — show raw
                signal_diagnostics["catchlights"] = [_build_entry(_c) for _c in _cl_list]
                signal_diagnostics["catchlight_summary"] = {
                    "raw_count": _raw_count,
                    "deduped_count": _raw_count,
                    "displayed_count": _raw_count,
                }

            # Key signals from light_structure
            _cr = getattr(ar, "cue_report", None)
            _ls = getattr(_cr, "light_structure", None) if _cr else None
            _ls_pattern_name = getattr(_ls, "pattern_name", None) or ""
            signal_diagnostics["signals"] = {
                "left_right_asymmetry":   round(getattr(_ls, "left_right_asymmetry", 0.0), 4),
                "shadow_density":          round(getattr(_ls, "shadow_density", 0.0), 4),
                "triangle_isolation":      round(getattr(_ls, "triangle_isolation", 0.0), 4),
                "highlight_width_ratio":   round(getattr(_ls, "highlight_width_ratio", 0.0), 4),
                "nose_shadow_angle_deg":   round(getattr(_ls, "nose_shadow_centroid_angle_deg", 0.0), 1),
                "nose_shadow_distance":    round(getattr(_ls, "nose_shadow_centroid_distance", 0.0), 4),
                "shadow_pass_pattern":     _ls_pattern_name,
            }

            # Catchlight intelligence boost diagnostic
            _li_diag = getattr(ar, "lighting_intel", None)
            _ci_diag = getattr(_li_diag, "catchlight_intelligence", None) or {}
            _ci_diag = _ci_diag if isinstance(_ci_diag, dict) else {}
            _pk_diag = (_ci_diag.get("primary_key") or {})
            _pk_quad_diag = _pk_diag.get("quad", "") or ""
            _has_cl_diag = bool(_pk_diag)
            _ring_diag = _ci_diag.get("ring_light_detected", False)
            _ca_deg_diag = round(getattr(_ls, "nose_shadow_centroid_angle_deg", 0.0), 1)
            _ca_diagonal = (20 < _ca_deg_diag < 80) or (280 < _ca_deg_diag < 340)
            _lra_diag = signal_diagnostics["signals"]["left_right_asymmetry"]
            _cd_diag = round(getattr(_ls, "nose_shadow_centroid_distance", 0.0), 4)
            signal_diagnostics["catchlight_boost"] = {
                "primary_key_quad":           _pk_quad_diag or "none",
                "has_catchlights":            _has_cl_diag,
                "ring_light_detected":        _ring_diag,
                "off_axis_boost_fired":       _pk_quad_diag in ("upper_right", "upper_left"),
                "off_axis_boost_value":       0.08 if _pk_quad_diag in ("upper_right", "upper_left") else 0.0,
                "shadow_pass_called_loop":    _ls_pattern_name == "loop",
                "fill_heavy_boost_eligible":  (
                    _lra_diag < 0.10
                    and _cd_diag > 0.08
                    and _ls_pattern_name == "loop"
                    and _ca_diagonal
                ),
                "fill_heavy_boost_value":     0.05 if (
                    _lra_diag < 0.10 and _cd_diag > 0.08
                    and _ls_pattern_name == "loop" and _ca_diagonal
                ) else 0.0,
                "centroid_angle_deg":         _ca_deg_diag,
                "centroid_diagonal":          _ca_diagonal,
            }

            # Gate evaluations — which gates fired and what they decided
            _pattern = (lighting_data.get("pattern") or "")
            _lra = signal_diagnostics["signals"]["left_right_asymmetry"]

            _split_penalty = 0.35 * (1.0 - _lra / 0.20) if _lra < 0.20 else 0.0
            signal_diagnostics["gates"] = [
                {
                    "name": "split_asymmetry_gate",
                    "description": "Penalise split confidence when lr_asymmetry < 0.20 (weak shadow for 90° key)",
                    "checked": True,
                    "triggered": _lra < 0.20,
                    "value": _lra,
                    "threshold": 0.20,
                    "result": f"confidence −{_split_penalty:.2f}" if _lra < 0.20 else "passed",
                },
            ]

            # Always use the authoritative (post-resolution) pattern — lighting_intel
            # can disagree with the resolver (e.g. "loop" vs "butterfly").
            signal_diagnostics["final_pattern"] = ar.authoritative_pattern or _pattern or ""

            # ── Layer 0: full catchlight intelligence dump ──────────────────
            _ci_full = getattr(ar.lighting_intel, "catchlight_intelligence", None) if ar.lighting_intel else None
            _ci_full = _ci_full if isinstance(_ci_full, dict) else {}
            signal_diagnostics["layer_0"] = {
                "ring_light_detected":       _ci_full.get("ring_light_detected", False),
                "primary_key":               _ci_full.get("primary_key"),
                "modifier":                  _ci_full.get("modifier"),
                "fill_bilateral":            _ci_full.get("fill_bilateral"),
                "key_intensity_pct":         _ci_full.get("key_intensity_pct"),
                "fill_intensity_pct":        _ci_full.get("fill_intensity_pct"),
                "fill_ratio":                _ci_full.get("fill_ratio"),
                "stops_down":                _ci_full.get("stops_down"),
                "light_count_from_catchlights": _ci_full.get("light_count_from_catchlights"),
                "catchlights":               _ci_full.get("catchlights"),
                "notes":                     _ci_full.get("notes"),
            }

            # ── Layer 1: shadow pass + pattern boosts ───────────────────────
            _lsp_pattern = getattr(_ls, "pattern_name", None) or "none"
            _lsp_lra     = round(getattr(_ls, "left_right_asymmetry", 0.0), 4)
            _lsp_sd      = round(getattr(_ls, "shadow_density", 0.0), 4)
            _lsp_ti      = round(getattr(_ls, "triangle_isolation", 0.0), 4)
            _lsp_cd      = round(getattr(_ls, "nose_shadow_centroid_distance", 0.0), 4)
            _lsp_ca      = round(getattr(_ls, "nose_shadow_centroid_angle_deg", 0.0), 1)
            _lsp_tb      = round(getattr(_ls, "top_bottom_ratio", 0.0), 4)
            _lsp_hw      = round(getattr(_ls, "highlight_width_ratio", 0.0), 4)
            _lsp_symm    = round(getattr(_ls, "symmetry_score", 0.0), 4)
            _lsp_ca_diag = (20 < _lsp_ca < 80) or (280 < _lsp_ca < 340)
            _boost_shadow_pass  = 0.12 if _lsp_pattern == "loop" else 0.0
            _boost_lrasym       = 0.06 if (0.10 < _lsp_lra < 0.25 and _lsp_cd > 0.1) else 0.0
            _boost_fill_heavy   = 0.05 if (_lsp_lra < 0.10 and _lsp_cd > 0.08 and _lsp_pattern == "loop" and _lsp_ca_diag) else 0.0
            _boost_offaxis_cl   = 0.08 if _pk_quad_diag in ("upper_right", "upper_left") else 0.0
            _penalty_tri_iso    = -0.04 if _lsp_ti > 0.12 else 0.0
            signal_diagnostics["layer_1"] = {
                "shadow_pass_pattern":    _lsp_pattern,
                "left_right_asymmetry":   _lsp_lra,
                "shadow_density":         _lsp_sd,
                "triangle_isolation":     _lsp_ti,
                "centroid_angle_deg":     _lsp_ca,
                "centroid_diagonal":      _lsp_ca_diag,
                "centroid_distance":      _lsp_cd,
                "top_bottom_ratio":       _lsp_tb,
                "highlight_width_ratio":  _lsp_hw,
                "symmetry_score":         _lsp_symm,
                "boosts": {
                    "shadow_pass_loop_confirmed": _boost_shadow_pass,
                    "lr_asym_plus_centroid":      _boost_lrasym,
                    "fill_heavy_loop_centroid":   _boost_fill_heavy,
                    "catchlight_off_axis":        _boost_offaxis_cl,
                    "triangle_iso_penalty":       _penalty_tri_iso,
                    "total_delta":                round(_boost_shadow_pass + _boost_lrasym + _boost_fill_heavy + _boost_offaxis_cl + _penalty_tri_iso, 3),
                },
            }
        except Exception as _diag_exc:
            signal_diagnostics["error"] = str(_diag_exc)

        # ── Phase L1 observability record ────────────────────────────────────
        # emit_analysis_l1 was already called inside analyze_image() (at the end
        # of the pipeline).  We call _build_record here separately to get the
        # dict for the API response — no duplicate log emission.
        _l1_record: dict = {}
        try:
            from engine.observability import _build_record as _obs_build
            _l1_record = _obs_build(ar)
        except Exception as _obs_exc:
            _log.getLogger(__name__).debug("L1 record build failed: %s", _obs_exc)

        response = {
            "status": "ok",
            "analysis_id": ar.analysis_id,
            "system_version": ar.version_metadata.pipeline_version if ar.version_metadata else None,
            "image_path": str(fpath),
            "original_filename": original_filename,
            "description": ar.description,
            "reference_analysis": ar.reference_analysis.model_dump() if ar.reference_analysis else {},
            "vlm": vlm_data,
            "vlm_available": vlm_is_available,
            "vlm_error": ar.vlm_error,  # None on success; error string if VLM call failed
            "vlm_reconstruction": ar.vlm_reconstruction,
            "cv": cv_data,
            "classification": ar.classification,
            "lighting_inference": lighting_data,
            "solver": solver_data,
            "reconstruction": pipeline_recon,
            "edge_case_flags": pipeline_edge_flags,
            "signal_diagnostics": signal_diagnostics,
            # Top-level authoritative values — always present regardless of lighting_intel state
            "authoritative_pattern":        ar.authoritative_pattern or "unknown",
            "authoritative_pattern_source": getattr(ar, "authoritative_pattern_source", "none"),
            "authoritative_confidence":     getattr(ar, "pattern_confidence", 0.0),
            "authoritative_confidence_label": getattr(ar, "pattern_confidence_label", "weak"),
            # OD-3: source_context coexists with pattern (window_portrait → window, etc.)
            "source_context":               getattr(ar, "source_context", None),
            # Geometric base preserved when tonal specialty (low_key, high_key) overrides
            "geometric_base":               getattr(ar, "geometric_base", None),
            "analyzed_by": user.get("email"),
            "analyzed_at": time.time(),
            "stage_timings": getattr(ar, "stage_timings", {}),
            "image_dimensions": ar.description.get("size") if ar.description else None,
            # EXIF camera data — aperture, shutter, ISO, focal length, body, lens
            "camera_settings": exif_data if exif_data else None,
            # Phase L1 — structured observability surface
            "observability": _l1_record,
        }

        if debug_overlay_url:
            response["debug_overlay_url"] = debug_overlay_url

        # Build 3A: persist trimmed replay blob — best-effort, non-blocking
        try:
            import json as _replay_json
            import time as _replay_time
            from engine.orchestrator import analysis_result_to_replay_dict
            replay_payload = analysis_result_to_replay_dict(ar)
            replay_json_str = _replay_json.dumps(replay_payload, default=str)
            _sys_ver = (
                replay_payload.get("version_metadata", {}).get("pipeline_version")
                if isinstance(replay_payload.get("version_metadata"), dict)
                else None
            )
            with get_db() as _replay_conn:
                _replay_conn.execute(
                    """INSERT OR REPLACE INTO analysis_results
                       (analysis_id, image_path, system_version, result_json, created_at, user_email)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        ar.analysis_id,
                        str(fpath),
                        _sys_ver,
                        replay_json_str,
                        _replay_time.time(),
                        user.get("email"),
                    ),
                )
        except Exception as _replay_err:
            import logging as _replay_log
            _replay_log.getLogger(__name__).warning(
                "Build 3A: failed to persist replay blob: %s", _replay_err
            )

        # Privacy mode: delete the uploaded image after analysis + replay persistence
        if delete_after and fpath.exists():
            try:
                fpath.unlink()
                logger.info("delete_after: removed %s", fpath)
            except Exception as _del_err:
                logger.warning("delete_after: failed to remove %s — %s", fpath, _del_err)

        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            import sentry_sdk as _sentry
            _sentry.capture_exception(e)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}",
        )


def _normalize_cloud_url(url: str) -> str:
    """Transform cloud storage share URLs into direct-download URLs."""
    import re
    # Dropbox: ?dl=0 → ?dl=1  (preview page → raw file)
    if "dropbox.com" in url or "dropboxusercontent.com" in url:
        url = re.sub(r'[?&]dl=0', lambda m: m.group(0).replace('dl=0', 'dl=1'), url)
        if "dl=1" not in url:
            url += ("&" if "?" in url else "?") + "dl=1"
        return url
    # Google Drive: /file/d/{id}/view → uc?export=download&id={id}
    m = re.search(r"drive\.google\.com/file/d/([^/?#]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.search(r"drive\.google\.com/open\?id=([^&]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


@router.post("/fetch-image-url")
async def fetch_image_url_proxy(
    url: str = Form(...),
    user: Dict = Depends(get_dev_user),
):
    """Server-side proxy to fetch a remote image URL, bypassing browser CORS.
    Automatically normalizes Dropbox and Google Drive share links to direct downloads.
    """
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL — must start with http:// or https://")
    fetch_url = _normalize_cloud_url(url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            resp = await client.get(fetch_url, headers={"User-Agent": "Mozilla/5.0 (compatible; NGW/1.0)"})
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Remote URL returned {resp.status_code}")
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="That link doesn't point directly to an image. For Dropbox, use a direct download link.")
        return FastAPIResponse(content=resp.content, media_type=content_type)
    except httpx.RequestError as e:
        raise HTTPException(status_code=400, detail=f"Could not reach that URL: {e}")


@analyze_router.post("/analyze/cancel/{analysis_id}")
async def cancel_analysis(
    analysis_id: str,
    user: Dict = Depends(get_dev_user),
):
    """Cancel an in-flight analysis by its analysis_id.

    Returns 200 whether or not the task was still running (idempotent).
    """
    with _inflight_lock:
        future = _inflight.pop(analysis_id, None)
        _cancelled.add(analysis_id)
    if future and not future.done():
        future.cancel()
        return {"cancelled": True, "analysis_id": analysis_id}
    return {"cancelled": False, "analysis_id": analysis_id, "detail": "Not in-flight (already finished or unknown)"}


@analyze_router.get("/analyze/status")
async def analyze_status(user: Dict = Depends(get_dev_user)):
    """Return the list of currently in-flight analysis ids."""
    with _inflight_lock:
        ids = list(_inflight.keys())
    return {"in_flight": ids, "count": len(ids), "timeout_seconds": ANALYSIS_TIMEOUT_SECONDS}


@router.get("/analysis/{analysis_id}")
async def get_analysis_replay(
    analysis_id: str,
    user: Dict = Depends(get_dev_user),
):
    """Return stored replay data for a past analysis run.

    Returns:
    - result: stored replay blob from analysis_results (if persisted — only available
              for analyses run AFTER Build 3A was deployed on 2026-04-02)
    - vlm_disagreements: all disagreement records for this analysis_id
    - user_feedback: all feedback records for this analysis_id
    - corrections: all correction log entries for this analysis_id

    DATA NOTES:
    - result is only available for analyses run after Build 3A deployment
    - session_signals.outcome is synthetic, not human ground truth
    - resolved_value in vlm_disagreements is CV-resolved, not human-labeled
    """
    import json as _rj

    with get_db() as conn:
        # 1. Stored replay blob
        row = conn.execute(
            "SELECT analysis_id, image_path, system_version, result_json, created_at"
            " FROM analysis_results WHERE analysis_id = ?",
            (analysis_id,),
        ).fetchone()

        result_data = None
        if row:
            try:
                result_data = {
                    "analysis_id":   row["analysis_id"],
                    "image_path":    row["image_path"],
                    "system_version": row["system_version"],
                    "created_at":    row["created_at"],
                    "replay_payload": _rj.loads(row["result_json"]),
                }
            except Exception:
                result_data = {
                    "analysis_id": analysis_id,
                    "error": "failed to parse stored result",
                }

        # 2. VLM disagreements
        disagreements = conn.execute(
            """SELECT id, field_name, vlm_value, vlm_confidence, resolved_value,
                      resolved_source, agreement, disagreement_magnitude,
                      pipeline_version, created_at
               FROM vlm_disagreements WHERE analysis_id = ? ORDER BY created_at""",
            (analysis_id,),
        ).fetchall()

        # 3. User feedback
        feedback_rows = conn.execute(
            "SELECT * FROM user_feedback WHERE analysis_id = ? ORDER BY created_at",
            (analysis_id,),
        ).fetchall()

        # 4. Corrections
        correction_rows = conn.execute(
            """SELECT id, image_path, field_name, old_value, new_value,
                      corrected_by, corrected_at, system_version, source
               FROM image_correction_log WHERE analysis_id = ? ORDER BY corrected_at""",
            (analysis_id,),
        ).fetchall()

    return {
        "analysis_id": analysis_id,
        "result": result_data,
        "vlm_disagreements": [dict(r) for r in disagreements],
        "user_feedback": [dict(r) for r in feedback_rows],
        "corrections": [dict(r) for r in correction_rows],
        "data_notes": {
            "result_availability": (
                "Only available for analyses run after Build 3A deployment (2026-04-02)."
                " Returns null for earlier runs."
            ),
            "outcome_field": (
                "session_signals.outcome is synthetic — not human-confirmed ground truth."
            ),
            "resolved_value": (
                "vlm_disagreements.resolved_value is CV-resolver decision,"
                " not human-labeled ground truth."
            ),
        },
        "found": result_data is not None,
    }


# ── Build 3.1: Safe replay image serving ──────────────────────────────────────

_REPLAY_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
    ".heic": "image/heic", ".heif": "image/heif",
}

# Safe base directories for replay image serving.
# Only images inside these directories may be served.
_SAFE_IMAGE_BASES = [
    UPLOAD_DIR.resolve(),                                          # data/uploads/lab/
    (DATA_DIR / "uploads" / "reference_dataset").resolve(),        # reference dataset images
    (DATA_DIR / "uploads" / "reference_ingest").resolve(),         # reference ingest staging
    (DATA_DIR / "reference_dataset").resolve(),                    # reference dataset entries
    (DATA_DIR / "reference_library").resolve(),                    # reference library entries
]


def _is_safe_image_path(image_path: Path) -> bool:
    """Check that a resolved image path falls inside an approved base directory.

    Prevents directory traversal — only images inside known upload/reference
    directories may be served.
    """
    resolved = image_path.resolve()
    return any(
        resolved == base or str(resolved).startswith(str(base) + "/")
        for base in _SAFE_IMAGE_BASES
    )


@router.get("/analysis/{analysis_id}/image")
def get_analysis_replay_image(
    analysis_id: str,
    request: Request,
    token: Optional[str] = Query(None),
):
    """Serve the image file associated with a stored analysis replay.

    Build 3.1 — safe image serving for Case Replay.

    Auth: accepts token via Authorization header OR ?token= query param.
    Query-param auth is needed because <img src> cannot send headers.

    Safety:
    - Image path is looked up from the database (not from client input)
    - Path is resolved and validated against approved base directories
    - Only known image MIME types are served
    - Returns 404 if the image is missing, path is outside safe bases,
      or the analysis record doesn't exist
    """
    # Authenticate: try header first, then query param
    from auth.security import decode_token as _decode, _dev_mode_active, _DEV_MODE_USER
    from db.database import get_user_by_id as _get_user

    user = None
    if _dev_mode_active():
        user = _DEV_MODE_USER
    else:
        # Try Authorization header
        auth_header = request.headers.get("authorization", "")
        bearer_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else None
        jwt_token = bearer_token or token  # fallback to query param
        if not jwt_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user_id = _decode(jwt_token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = _get_user(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # Dev email check (same as get_dev_user)
        from auth.dev_guard import _get_dev_emails
        allowed = _get_dev_emails()
        if allowed and (user.get("email", "").lower() not in allowed):
            raise HTTPException(status_code=403, detail="Lab access denied")
    with get_db() as conn:
        row = conn.execute(
            "SELECT image_path FROM analysis_results WHERE analysis_id = ?",
            (analysis_id,),
        ).fetchone()

    if not row or not row["image_path"]:
        raise HTTPException(status_code=404, detail="No image path for this analysis")

    image_path = Path(row["image_path"])

    # Resolve symlinks and normalize before safety check
    if not image_path.is_absolute():
        image_path = (DATA_DIR / image_path).resolve()
    else:
        image_path = image_path.resolve()

    if not _is_safe_image_path(image_path):
        raise HTTPException(
            status_code=404,
            detail="Image path is outside approved directories",
        )

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    suffix = image_path.suffix.lower()
    media_type = _REPLAY_IMAGE_MEDIA_TYPES.get(suffix, "application/octet-stream")

    return FileResponse(str(image_path), media_type=media_type)


def _generate_debug_overlay(raw: Dict[str, Any], image_path: Path) -> Optional[str]:
    """Run the extended vision pipeline and generate a debug overlay image.

    This is diagnostic-only — it does not change analysis outputs.
    Returns the URL path to the overlay image, or None on failure.
    """
    try:
        import numpy as np
        from engine.vision_passes import run_extended_pipeline
        from engine.vision_debug import generate_analysis_overlay

        img_bgr = raw.get("_debug_img_bgr")
        masks = raw.get("_debug_masks", {})
        face_box = raw.get("_debug_face_box")

        if img_bgr is None:
            return None

        # Extract masks
        person_mask = masks.get("person") if isinstance(masks, dict) else None
        skin_mask = masks.get("skin") if isinstance(masks, dict) else None
        background_mask = masks.get("background") if isinstance(masks, dict) else None

        # Existing catchlight + geometry data from the basic vision pipeline
        vision_data = raw.get("vision", {})
        existing_catchlights = vision_data.get("catchlights")
        existing_geometry = vision_data.get("pose")

        # Run the full extended pipeline (11 passes)
        pipeline_results = run_extended_pipeline(
            img_bgr,
            person_mask=person_mask,
            skin_mask=skin_mask,
            background_mask=background_mask,
            face_box=face_box,
            existing_catchlights=existing_catchlights,
            existing_geometry=existing_geometry,
        )

        # Generate overlay with unique filename
        overlay_filename = f"overlay_{image_path.stem}_{uuid.uuid4().hex[:8]}.jpg"
        overlay_path = Path("static/debug") / overlay_filename

        saved_path = generate_analysis_overlay(
            img_bgr,
            pipeline_results,
            face_box=face_box,
            person_mask=person_mask,
            output_path=str(overlay_path),
            vision_data=vision_data,
        )

        if saved_path:
            return f"/static/debug/{overlay_filename}"
        return None

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Debug overlay generation failed: %s", exc)
        return None


# ── Debug overlay layer regeneration ─────────────────────

class OverlayRegenerateBody(BaseModel):
    overlay_url: str = Field(..., description="URL of the existing overlay, e.g. /static/debug/overlay_foo_abc12345.jpg")
    layers: Optional[List[str]] = Field(default=None, description="Layer names to include. null/omitted = all layers. Empty list [] = no layers (clean image).")


@router.post("/debug-overlay/regenerate")
async def regenerate_debug_overlay(
    body: OverlayRegenerateBody,
    user: Dict = Depends(get_dev_user),
):
    """Regenerate a debug overlay with a filtered set of layers.

    Uses the sidecar JSON saved alongside the original overlay to avoid
    re-running the full analysis pipeline.

    Returns: { "debug_overlay_url": "/static/debug/overlay_foo_abc12345_layers.jpg" }

    Layer names: shadow, highlights, catchlights, background, pose,
                 specular, surface, light_roles, summary
    """
    from engine.vision_debug import generate_analysis_overlay, ALL_LAYERS

    # Extract stem from the overlay URL — e.g. "/static/debug/overlay_foo_abc12345.jpg"
    overlay_url = body.overlay_url.lstrip("/")
    overlay_path = Path(overlay_url)
    overlay_stem = overlay_path.stem  # e.g. "overlay_foo_abc12345"

    sidecar_path = Path("static/debug") / f"{overlay_stem}.json"
    if not sidecar_path.exists():
        raise HTTPException(status_code=404, detail="Overlay sidecar not found. Re-analyze with debug=true to regenerate.")

    try:
        import json as _json
        import numpy as _np
        import cv2 as _cv2

        sidecar = _json.loads(sidecar_path.read_text())
        pipeline_results = sidecar.get("pipeline_results", {})
        face_box_raw = sidecar.get("face_box")
        vision_catchlights = sidecar.get("vision_catchlights")
        sidecar_vision_data = {"catchlights": vision_catchlights} if vision_catchlights else None
        sidecar_intel_catchlights = sidecar.get("intel_catchlights") or []
        face_box = tuple(face_box_raw) if face_box_raw else None

        # Determine active layers
        # None → all layers; [] → no layers (clean source image); [...] → filtered subset
        if body.layers is None:
            active_layers = None  # all layers
        elif body.layers:
            active_layers = frozenset(body.layers) & ALL_LAYERS
        else:
            active_layers = frozenset()  # explicitly empty — clean source image

        # Load the clean source image saved at analyze time.
        # overlay_stem_src.jpg is written by the analyze endpoint alongside
        # the sidecar JSON — it's the original un-annotated photo.
        src_path = Path("static/debug") / f"{overlay_stem}_src.jpg"
        if not src_path.exists():
            raise HTTPException(
                status_code=404,
                detail=(
                    "Source image snapshot not found. "
                    "Layer toggling requires re-analyzing the photo with Debug Overlay enabled "
                    "(this generates the _src.jpg snapshot alongside the sidecar)."
                ),
            )
        source_img = _cv2.imread(str(src_path))
        if source_img is None:
            raise HTTPException(status_code=422, detail="Could not decode source image snapshot.")

        # Generate with selected layers — None=all, frozenset()=none, frozenset({...})=filtered
        if active_layers is None:
            layer_tag = "all"
        elif active_layers:
            layer_tag = "_".join(sorted(active_layers))[:40]
        else:
            layer_tag = "none"
        out_filename = f"{overlay_stem}_{layer_tag[:40]}.jpg"
        out_path = Path("static/debug") / out_filename

        saved = generate_analysis_overlay(
            source_img,
            pipeline_results,
            face_box=face_box,
            person_mask=None,   # mask not stored in sidecar (too large)
            output_path=str(out_path),
            layers=active_layers,
            vision_data=sidecar_vision_data,
            intel_catchlights=sidecar_intel_catchlights,
        )
        if not saved:
            raise HTTPException(status_code=500, detail="Overlay generation failed.")

        return {"debug_overlay_url": f"/static/debug/{out_filename}"}

    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Overlay regeneration failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Gold Set CRUD ─────────────────────────────────────────

@router.get("/gold-set")
async def list_gold_set(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: Dict = Depends(get_dev_user),
):
    """List gold set entries, optionally filtered by status."""
    entries = get_gold_set_entries(status=status, limit=limit)
    return {"entries": entries, "count": len(entries)}


# ── Gold Set QC (must be before {entry_id} to avoid path capture) ──

@router.get("/gold-set/qc")
async def gold_set_qc(user: Dict = Depends(get_dev_user)):
    """Compute quality-control buckets for gold set / benchmark entries.

    Reads the gold set manifest + benchmark_cases table + distillation review
    escalations. Returns structured QC data for the LAB QC surface.

    No mutations — read-only inspection surface.
    """
    import json as _json
    manifest_path = Path(__file__).resolve().parent.parent.parent / "data" / "gold_set" / "manifest.json"

    # ── Load manifest entries ──
    manifest_entries: list[dict] = []
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                manifest_data = _json.load(f)
            manifest_entries = manifest_data.get("entries", [])
        except Exception:
            pass

    # ── Load gold_set_issue escalations from distillation reviews ──
    escalated_images: set[str] = set()
    escalated_reviews: list[dict] = []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, image_path, expected_pattern, review_status, rationale, notes "
                "FROM distillation_candidate_reviews WHERE review_status = 'gold_set_issue'"
            ).fetchall()
            for r in rows:
                d = dict(r)
                escalated_images.add(d.get("image_path", ""))
                escalated_reviews.append(d)
    except Exception:
        pass

    # ── Load disagreement counts per image (via analysis_results join) ──
    disagreement_counts: dict[str, int] = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT a.image_path, COUNT(d.id) as cnt "
                "FROM vlm_disagreements d "
                "JOIN analysis_results a ON d.analysis_id = a.analysis_id "
                "WHERE d.agreement = 'conflicting' "
                "GROUP BY a.image_path"
            ).fetchall()
            for r in rows:
                disagreement_counts[dict(r)["image_path"]] = dict(r)["cnt"]
    except Exception:
        pass

    # ── Classify each manifest entry into QC buckets ──
    qc_items: list[dict] = []
    counts = {
        "qc_low_trust": 0,
        "qc_strict_acceptable_patterns": 0,
        "qc_ambiguous_geometry": 0,
        "qc_repeated_disagreement": 0,
        "qc_gold_set_issue_escalated": 0,
        "qc_stale_entry": 0,
        "total_entries": len(manifest_entries),
        "flagged_entries": 0,
    }

    for entry in manifest_entries:
        reasons: list[str] = []
        trust = entry.get("trust_score", 1.0)
        acceptable = entry.get("acceptable_patterns", [])
        expected = entry.get("expected_pattern", "")
        challenges = entry.get("known_challenges", [])
        image_path = entry.get("image_path", "")
        difficulty = entry.get("difficulty", "standard")

        # 1. Low trust
        if trust <= 0.6:
            reasons.append("qc_low_trust")
            counts["qc_low_trust"] += 1

        # 2. Strict acceptable patterns (only 1 acceptable pattern = rigid, fragile)
        if len(acceptable) <= 1:
            reasons.append("qc_strict_acceptable_patterns")
            counts["qc_strict_acceptable_patterns"] += 1

        # 3. Ambiguous geometry (many acceptable patterns = genuinely ambiguous)
        if len(acceptable) >= 5:
            reasons.append("qc_ambiguous_geometry")
            counts["qc_ambiguous_geometry"] += 1

        # 4. Repeated disagreement (VLM disagreed on this image multiple times)
        dis_count = disagreement_counts.get(image_path, 0)
        if dis_count == 0:
            # Try matching by filename suffix
            for path, cnt in disagreement_counts.items():
                if path.endswith(image_path) or image_path.endswith(path.rsplit("/", 1)[-1]):
                    dis_count = cnt
                    break
        if dis_count >= 2:
            reasons.append("qc_repeated_disagreement")
            counts["qc_repeated_disagreement"] += 1

        # 5. Gold set issue escalated (from distillation reviews)
        if image_path in escalated_images:
            reasons.append("qc_gold_set_issue_escalated")
            counts["qc_gold_set_issue_escalated"] += 1

        # 6. Stale — entries with known_challenges that suggest labeling difficulty
        if difficulty == "hard" or len(challenges) >= 3:
            reasons.append("qc_stale_entry")
            counts["qc_stale_entry"] += 1

        if reasons:
            counts["flagged_entries"] += 1
            qc_items.append({
                "id": entry.get("id", ""),
                "image_path": image_path,
                "expected_pattern": expected,
                "trust_score": trust,
                "acceptable_patterns": acceptable,
                "acceptable_count": len(acceptable),
                "difficulty": difficulty,
                "known_challenges": challenges,
                "notes": entry.get("notes", ""),
                "disagreement_count": dis_count,
                "qc_reasons": reasons,
                "qc_primary": reasons[0],
            })

    # Sort: most QC reasons first, then lowest trust
    qc_items.sort(key=lambda x: (-len(x["qc_reasons"]), x["trust_score"]))

    return {
        "counts": counts,
        "items": qc_items,
        "escalated_reviews": escalated_reviews,
    }


# ── Coverage Map (Build 4) ──────────────────────────────────────────────────

# Canonical pattern universe — source of truth from engine/enums.py LightingPattern
# Canonical pattern universe — source of truth from engine/enums.py LightingPattern
# Machine values (keys) are stable snake_case. Display labels (values) are UI-only.
_COVERAGE_PATTERNS = {
    # ── Core 14 ──────────────────────────────────────────────────────────────
    "loop":                 "Loop",
    "rembrandt":            "Rembrandt",
    "butterfly":            "Butterfly / Paramount",
    "clamshell":            "Clamshell",
    "split":                "Split",
    "broad":                "Broad",
    "short":                "Short",
    "high_key":             "High Key",
    "low_key":              "Low Key",
    "flat":                 "Flat",
    "ring_light":           "Ring Light",
    "rim":                  "Rim / Edge Light",
    "silhouette_key":       "Silhouette / Back Key",
    "projected":            "Projected / Interrupted Light",
    # ── Specialty tier ───────────────────────────────────────────────────────
    "triangle":             "Triangle (Hurley)",
    "shallow_loop":         "Shallow Loop",
    "window_portrait":      "Window Portrait",
    "bare_bulb_editorial":  "Bare Bulb Editorial",
    "strip_dramatic":       "Strip Light Dramatic",
    "short_fashion_key":    "Short Fashion Key",
    "soft_editorial_key":   "Soft Editorial Key",
    "editorial_rim_key":    "Editorial Rim + Key",
    "tabletop_soft_product":"Tabletop Soft Product",
    "bottle_backlight":     "Bottle Backlight",
    "athletic_rim_sculpt":  "Athletic Rim Sculpt",
    "window_negative_fill": "Window Negative Fill",
    "hybrid":               "Hybrid",
    "unknown":              "Unknown",
}

def _coverage_tier(signal_count: int) -> str:
    """Display-only tier. Does not affect model behavior."""
    if signal_count >= 20:
        return "strong"
    if signal_count >= 8:
        return "moderate"
    if signal_count >= 2:
        return "thin"
    return "absent"


@router.get("/coverage-map")
async def coverage_map(user: Dict = Depends(get_dev_user)):
    """Per-pattern coverage summary — read-only inspection surface.

    Data sources:
      - session_signals (live only, include_in_metrics=1) for signal counts + avg confidence + last timestamp
      - gold_set/manifest.json pattern_coverage for gold set counts
    Excludes seeded/internal signals via include_in_metrics filter.
    """
    import json as _json

    # ── 1. Signal counts per pattern (live production signals only) ──
    signal_stats: dict[str, dict] = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT pattern_id, "
                "       COUNT(*) as cnt, "
                "       AVG(confidence_score) as avg_conf, "
                "       MAX(created_at) as last_ts "
                "FROM session_signals "
                "WHERE include_in_metrics = 1 "
                "GROUP BY pattern_id"
            ).fetchall()
            for r in rows:
                d = dict(r)
                signal_stats[d["pattern_id"]] = {
                    "signal_count": d["cnt"],
                    "avg_confidence": round(d["avg_conf"], 3) if d["avg_conf"] is not None else None,
                    "last_signal_ts": d["last_ts"],
                }
    except Exception:
        pass

    # ── 2. Gold set counts from manifest ──
    gold_counts: dict[str, int] = {}
    manifest_path = Path(__file__).resolve().parent.parent.parent / "data" / "gold_set" / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                manifest_data = _json.load(f)
            _gc = manifest_data.get("pattern_coverage", {})
            gold_counts = _gc if isinstance(_gc, dict) else {}
        except Exception:
            pass

    # ── 3. Reference dataset counts from manifest ──
    ref_counts: dict[str, int] = {}
    ref_manifest_path = Path(__file__).resolve().parent.parent.parent / "data" / "reference_dataset" / "_manifest.json"
    if ref_manifest_path.exists():
        try:
            with open(ref_manifest_path) as f:
                ref_data = _json.load(f)
            ref_counts = ref_data.get("pattern_coverage", {})
        except Exception:
            pass

    # ── 4. Assemble per-pattern rows from canonical universe ──
    patterns: list[dict] = []
    for pid, pname in _COVERAGE_PATTERNS.items():
        stats = signal_stats.get(pid, {})
        sc = stats.get("signal_count", 0)
        patterns.append({
            "pattern_id":     pid,
            "pattern_name":   pname,
            "signal_count":   sc,
            "gold_set_count": gold_counts.get(pid, 0),
            "ref_count":      ref_counts.get(pid, 0),
            "avg_confidence": stats.get("avg_confidence"),
            "last_signal_ts": stats.get("last_signal_ts"),
            "coverage_tier":  _coverage_tier(sc),
        })

    # Sort: absent first, then thin, moderate, strong — within tier by signal_count asc
    tier_order = {"absent": 0, "thin": 1, "moderate": 2, "strong": 3}
    patterns.sort(key=lambda p: (tier_order.get(p["coverage_tier"], 9), p["signal_count"]))

    return {
        "counts_source_note": (
            "signal_count from session_signals WHERE include_in_metrics=1 (live production only). "
            "gold_set_count from data/gold_set/manifest.json. "
            "ref_count from data/reference_dataset/_manifest.json. "
            "Seeded/internal signals excluded."
        ),
        "tier_thresholds": {
            "strong": ">= 20 signals",
            "moderate": ">= 8 signals",
            "thin": ">= 2 signals",
            "absent": "0 signals",
        },
        "total_patterns": len(patterns),
        "patterns": patterns,
    }


@router.get("/gold-set/{entry_id}")
async def get_gold_set(entry_id: str, user: Dict = Depends(get_dev_user)):
    """Get a single gold set entry."""
    entry = get_gold_set_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Gold set entry not found")
    return entry


@router.post("/gold-set")
async def create_gold_set(body: GoldSetCreate, user: Dict = Depends(get_dev_user)):
    """Create a new gold set entry."""
    entry = create_gold_set_entry(
        image_path=body.image_path,
        expected_analysis=body.expected_analysis,
        notes=body.notes,
        status=body.status,
        created_by=user.get("email", "unknown"),
        setup_family=body.setup_family,
        provenance=body.provenance,
    )
    log_admin_change("gold_set", entry["id"], "create", {
        "by": user.get("email", "unknown"),
        "image_path": body.image_path,
        "status": body.status,
    })
    return entry


@router.put("/gold-set/{entry_id}")
async def update_gold_set(
    entry_id: str,
    body: GoldSetUpdate,
    user: Dict = Depends(get_dev_user),
):
    """Update a gold set entry."""
    existing = get_gold_set_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Gold set entry not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return existing

    entry = update_gold_set_entry(entry_id, **updates)
    log_admin_change("gold_set", entry_id, "update", {
        "by": user.get("email", "unknown"),
        "fields": list(updates.keys()),
    })
    return entry


@router.get("/gold-set/{entry_id}/image")
async def get_gold_set_image(entry_id: str, user: Dict = Depends(get_dev_user)):
    """Serve the image file associated with a gold set entry."""
    entry = get_gold_set_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Gold set entry not found")
    image_path = Path(entry.get("image_path", ""))
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    # Detect media type from suffix
    suffix = image_path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".heic": "image/heic", ".heif": "image/heif",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")
    return FileResponse(str(image_path), media_type=media_type)


@router.delete("/gold-set/{entry_id}")
async def delete_gold_set(entry_id: str, user: Dict = Depends(get_dev_user)):
    """Delete a gold set entry."""
    deleted = delete_gold_set_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Gold set entry not found")
    log_admin_change("gold_set", entry_id, "delete", {"by": user.get("email", "unknown")})
    return {"status": "deleted", "id": entry_id}


# ── Gold Set Evaluation ──────────────────────────────────

@router.post("/gold-set/evaluate")
async def evaluate_gold_set(
    limit: int = Query(50, ge=1, le=200),
    user: Dict = Depends(get_dev_user),
):
    """Run analysis pipeline on all approved gold set entries and compare results.

    Scaffold — returns structure ready for comparison logic.
    """
    entries = get_gold_set_entries(status="approved", limit=limit)
    results = []

    for entry in entries:
        image_path = entry.get("image_path", "")
        if not Path(image_path).exists():
            results.append({
                "entry_id": entry["id"],
                "image_path": image_path,
                "status": "skipped",
                "reason": "Image file not found",
            })
            continue

        try:
            from engine.orchestrator import analyze_image

            ar = analyze_image(image_path, run_extended=False, run_solver=False)
            if not ar.ok:
                raise RuntimeError("; ".join(ar.notes))

            actual_data = ar.reference_analysis.model_dump() if ar.reference_analysis else {}

            results.append({
                "entry_id": entry["id"],
                "image_path": image_path,
                "status": "analyzed",
                "expected": entry.get("expected_analysis", {}),
                "actual": actual_data,
            })
        except Exception as e:
            results.append({
                "entry_id": entry["id"],
                "image_path": image_path,
                "status": "error",
                "error": str(e),
            })

    return {
        "evaluated": len(results),
        "results": results,
        "evaluated_by": user.get("email"),
        "evaluated_at": time.time(),
    }


# ── Rule Candidates CRUD ─────────────────────────────────

@router.get("/candidates")
async def list_candidates(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: Dict = Depends(get_dev_user),
):
    """List rule candidates, optionally filtered by status."""
    candidates = get_rule_candidates(status=status, limit=limit)
    return {"candidates": candidates, "count": len(candidates)}


@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: str, user: Dict = Depends(get_dev_user)):
    """Get a single rule candidate."""
    candidate = get_rule_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Rule candidate not found")
    return candidate


@router.post("/candidates")
async def create_candidate(body: RuleCandidateCreate, user: Dict = Depends(get_dev_user)):
    """Create a new rule candidate."""
    candidate = create_rule_candidate(
        title=body.title,
        description=body.description,
        rationale=body.rationale,
        source_gold_set_id=body.source_gold_set_id,
        source_image_path=body.source_image_path,
        proposed_change=body.proposed_change,
        status=body.status,
        created_by=user.get("email", "unknown"),
    )
    log_admin_change("candidate", candidate["id"], "create", {
        "by": user.get("email", "unknown"),
        "title": body.title,
        "status": body.status,
    })
    return candidate


@router.put("/candidates/{candidate_id}")
async def update_candidate(
    candidate_id: str,
    body: RuleCandidateUpdate,
    user: Dict = Depends(get_dev_user),
):
    """Update a rule candidate."""
    existing = get_rule_candidate(candidate_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Rule candidate not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return existing

    candidate = update_rule_candidate(candidate_id, **updates)
    log_admin_change("candidate", candidate_id, "update", {
        "by": user.get("email", "unknown"),
        "fields": list(updates.keys()),
    })
    return candidate


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, user: Dict = Depends(get_dev_user)):
    """Delete a rule candidate."""
    deleted = delete_rule_candidate(candidate_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule candidate not found")
    log_admin_change("candidate", candidate_id, "delete", {"by": user.get("email", "unknown")})
    return {"status": "deleted", "id": candidate_id}


@router.post("/candidates/upload-image")
async def upload_candidate_image(
    file: UploadFile = File(...),
    user: Dict = Depends(get_dev_user),
) -> Dict[str, Any]:
    """Store an image attached to a rule candidate.

    Saves the file under UPLOAD_DIR/candidates/ using the canonical naming
    scheme and returns the server path.  No analysis is performed — this
    is a lightweight store-only endpoint for evidence images.
    """
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    dest_dir = UPLOAD_DIR / "candidates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    original_filename = file.filename or "photo.jpg"
    filename = canonical_upload_name(original_filename, origin="candidate")
    dest = dest_dir / filename
    with open(dest, "wb") as fh:
        fh.write(content)
    return {"path": str(dest), "original_filename": original_filename}


# ═══════════════════════════════════════════════════════════════════════════
# REFERENCE IMAGE INGESTION
# ═══════════════════════════════════════════════════════════════════════════


class ReferenceIngestMetadata(BaseModel):
    """Metadata for ingesting a reference image."""
    reference_id: str
    pattern_id: str
    photographer: str = ""
    dataset_tier: str = "community"
    entry_trust_score: float = 0.5
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    environment: Optional[str] = None
    light_count: Optional[int] = None
    key_direction_deg: Optional[float] = None
    key_height_relative: Optional[str] = None
    shadow_pattern: Optional[str] = None
    modifier_family: Optional[str] = None
    estimated_distance_ft: Optional[float] = None
    matched_setup_ids: Optional[List[str]] = None
    notes: Optional[str] = None
    # Legacy fields
    lighting_pattern: Optional[str] = None
    lights: Optional[List[Dict[str, Any]]] = None
    shadow_signature: Optional[Dict[str, str]] = None
    camera: Optional[Dict[str, Any]] = None
    use_cases: Optional[List[str]] = None
    lighting_notes: Optional[str] = None


REFERENCE_UPLOAD_DIR = DATA_DIR / "uploads" / "reference_ingest"
REFERENCE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/reference-library/ingest")
async def ingest_reference_image(
    image: UploadFile = File(...),
    metadata_json: str = Query(..., description="JSON string of ReferenceIngestMetadata"),
    overwrite: bool = Query(False, description="Overwrite existing files"),
    user: Dict = Depends(get_dev_user),
):
    """Ingest a reference image with validated metadata.

    Saves image to data/reference_library/<pattern_id>/, writes a sidecar
    JSON alongside it, and rebuilds the central reference_index.json.

    The metadata_json query parameter should be a JSON string matching
    the ReferenceIngestMetadata schema.
    """
    from engine.reference_ingestion import ingest_reference as _ingest
    from engine.reference_matcher import reload_references

    image_content = await _validate_upload(image)

    # Parse metadata
    try:
        meta_raw = json.loads(metadata_json)
        meta_model = ReferenceIngestMetadata(**meta_raw)
        metadata = meta_model.model_dump(exclude_none=True)
    except (json.JSONDecodeError, Exception) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid metadata JSON: {exc}")

    # Preserve original filename in metadata before ingestion
    original_filename = image.filename or "image.jpg"
    if "original_filename" not in metadata:
        metadata["original_filename"] = original_filename

    # Save uploaded image to temp location (temp name — cleaned up after ingest)
    ext = Path(original_filename).suffix.lower() or ".jpg"
    fname = canonical_upload_name(original_filename, origin="ref_tmp",
                                  pattern=metadata.get("pattern_id", "unknown"))
    tmp_path = REFERENCE_UPLOAD_DIR / fname

    with open(tmp_path, "wb") as f:
        f.write(image_content)

    try:
        result = _ingest(
            tmp_path,
            metadata,
            overwrite=overwrite,
        )

        # Reload matcher cache so scoring picks up new entry
        try:
            reload_references()
        except Exception:
            pass

        result["ingested_by"] = user.get("email")
        return result

    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")
    finally:
        # Clean up temp file (already copied to pattern folder)
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/reference-library/rebuild-index")
async def rebuild_reference_index(user: Dict = Depends(get_dev_user)):
    """Rebuild the central reference_index.json from sidecar files.

    Scans all pattern subfolders for *.json sidecar files, merges with
    legacy references.json entries, and writes data/reference_index.json.
    """
    from engine.reference_ingestion import rebuild_index as _rebuild
    from engine.reference_matcher import reload_references

    try:
        index = _rebuild()
        reload_references()
        return {
            "status": "ok",
            "total_entries": index.get("total_entries", 0),
            "image_backed_count": index.get("image_backed_count", 0),
            "legacy_count": index.get("legacy_count", 0),
            "rebuilt_by": user.get("email"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Index rebuild failed: {exc}")


@router.post("/reference-library/generate-legacy-sidecars")
async def generate_sidecars_for_legacy(
    dry_run: bool = Query(False),
    user: Dict = Depends(get_dev_user),
):
    """Generate sidecar JSON stubs for existing references.json entries.

    Creates pattern subfolders and sidecar metadata files for each legacy
    reference entry.  Use dry_run=True to preview without writing.
    """
    from engine.reference_ingestion import generate_legacy_sidecars as _generate
    from engine.reference_ingestion import rebuild_index as _rebuild
    from engine.reference_matcher import reload_references

    try:
        results = _generate(dry_run=dry_run)

        created = sum(1 for r in results if r["status"] in ("created", "would_create"))
        existing = sum(1 for r in results if r["status"] == "already_exists")

        response: Dict[str, Any] = {
            "status": "ok",
            "dry_run": dry_run,
            "created": created,
            "already_existed": existing,
            "results": results,
        }

        if not dry_run and created > 0:
            index = _rebuild()
            reload_references()
            response["index_total_entries"] = index.get("total_entries", 0)

        return response

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sidecar generation failed: {exc}")


@router.post("/reference-library/validate")
async def validate_reference_metadata(
    metadata: Dict[str, Any],
    user: Dict = Depends(get_dev_user),
):
    """Validate reference metadata without ingesting.

    Returns validation result with any errors found.
    """
    from engine.reference_ingestion import validate_metadata as _validate

    is_valid, errors = _validate(metadata)
    return {
        "valid": is_valid,
        "errors": errors,
        "reference_id": metadata.get("reference_id"),
        "pattern_id": metadata.get("pattern_id"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# REFERENCE LIBRARY MANAGEMENT (legacy CRUD)
# ═══════════════════════════════════════════════════════════════════════════

_REFERENCE_LIBRARY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reference_library" / "references.json"


def _load_reference_library() -> List[Dict[str, Any]]:
    """Load reference library from disk."""
    try:
        with open(_REFERENCE_LIBRARY_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_reference_library(entries: List[Dict[str, Any]]) -> None:
    """Save reference library to disk."""
    with open(_REFERENCE_LIBRARY_PATH, "w") as f:
        json.dump(entries, f, indent=2)


class ReferenceEntryCreate(BaseModel):
    reference_id: str
    photographer: str = ""
    lighting_pattern: str
    environment: str = "studio"
    lights: List[Dict[str, Any]] = Field(default_factory=list)
    shadow_signature: Dict[str, str] = Field(default_factory=dict)
    camera: Dict[str, Any] = Field(default_factory=dict)
    use_cases: List[str] = Field(default_factory=list)
    dataset_tier: str = "community"
    entry_trust_score: float = 0.5


class ReferenceEntryUpdate(BaseModel):
    photographer: Optional[str] = None
    lighting_pattern: Optional[str] = None
    environment: Optional[str] = None
    lights: Optional[List[Dict[str, Any]]] = None
    shadow_signature: Optional[Dict[str, str]] = None
    camera: Optional[Dict[str, Any]] = None
    use_cases: Optional[List[str]] = None
    dataset_tier: Optional[str] = None
    entry_trust_score: Optional[float] = None


@router.get("/reference-library")
async def list_reference_entries(
    tier: Optional[str] = Query(None, description="Filter by dataset_tier"),
    user: Dict = Depends(get_dev_user),
):
    """List all reference library entries, optionally filtered by tier."""
    entries = _load_reference_library()
    if tier:
        entries = [e for e in entries if e.get("dataset_tier") == tier]
    return {"entries": entries, "total": len(entries)}


@router.get("/reference-library/{reference_id}")
async def get_reference_entry(reference_id: str, user: Dict = Depends(get_dev_user)):
    """Get a single reference entry by ID."""
    entries = _load_reference_library()
    for e in entries:
        if e.get("reference_id") == reference_id:
            return e
    raise HTTPException(status_code=404, detail="Reference entry not found")


@router.post("/reference-library")
async def create_reference_entry(body: ReferenceEntryCreate, user: Dict = Depends(get_dev_user)):
    """Create a new reference library entry.

    Community entries start with trust_score=0.5.
    Only LAB can promote to gold tier.
    """
    entries = _load_reference_library()

    # Check for duplicate ID
    for e in entries:
        if e.get("reference_id") == body.reference_id:
            raise HTTPException(status_code=409, detail=f"Reference ID '{body.reference_id}' already exists")

    new_entry = body.model_dump()
    entries.append(new_entry)
    _save_reference_library(entries)

    # Reload matcher cache
    try:
        from engine.reference_matcher import reload_references
        reload_references()
    except Exception:
        pass

    return new_entry


@router.put("/reference-library/{reference_id}")
async def update_reference_entry(
    reference_id: str,
    body: ReferenceEntryUpdate,
    user: Dict = Depends(get_dev_user),
):
    """Update an existing reference entry.

    This is the ONLY way to promote an entry to gold tier.
    """
    entries = _load_reference_library()

    target = None
    for e in entries:
        if e.get("reference_id") == reference_id:
            target = e
            break

    if target is None:
        raise HTTPException(status_code=404, detail="Reference entry not found")

    updates = body.model_dump(exclude_none=True)
    target.update(updates)
    _save_reference_library(entries)

    # Reload matcher cache
    try:
        from engine.reference_matcher import reload_references
        reload_references()
    except Exception:
        pass

    return target


@router.delete("/reference-library/{reference_id}")
async def delete_reference_entry(reference_id: str, user: Dict = Depends(get_dev_user)):
    """Delete a reference entry."""
    entries = _load_reference_library()
    original_len = len(entries)
    entries = [e for e in entries if e.get("reference_id") != reference_id]

    if len(entries) == original_len:
        raise HTTPException(status_code=404, detail="Reference entry not found")

    _save_reference_library(entries)

    try:
        from engine.reference_matcher import reload_references
        reload_references()
    except Exception:
        pass

    return {"status": "deleted", "id": reference_id}


@router.post("/reference-library/from-reconstruction")
async def create_reference_from_reconstruction(
    reconstruction: Dict[str, Any],
    photographer: str = "",
    lighting_pattern: str = "",
    reference_id: Optional[str] = None,
    user: Dict = Depends(get_dev_user),
):
    """Convert a validated reconstruction into a new reference entry.

    Creates a community-tier entry from reconstruction output.
    LAB must review and promote to gold via PUT.
    """
    if not reference_id:
        reference_id = f"lab_{uuid.uuid4().hex[:8]}"

    # Build light config from reconstruction
    lights = []
    key_light = {
        "role": "key",
        "modifier": reconstruction.get("primary_modifier_hypothesis", "unknown"),
        "angle_deg": reconstruction.get("key_light_angle_deg", 0),
        "height_deg": 0,
        "distance_ft": reconstruction.get("estimated_source_distance_ft")
                       or reconstruction.get("modifier_distance_ft", 5),
    }
    # Map height string to degrees
    height_str = reconstruction.get("key_light_height", "eye_level")
    _height_map = {
        "below_eye_level": -10, "eye_level": 0,
        "above_eye_level": 20, "high": 40,
    }
    key_light["height_deg"] = _height_map.get(height_str, 0)
    lights.append(key_light)

    if reconstruction.get("fill_present"):
        lights.append({"role": "fill", "modifier": "unknown"})

    # Shadow signature
    shadow_sig = {}
    softness = reconstruction.get("shadow_softness")
    if softness is not None:
        if softness > 0.7:
            shadow_sig["nose_shadow"] = "minimal"
            shadow_sig["cheek_shadow"] = "minimal"
        elif softness > 0.4:
            shadow_sig["nose_shadow"] = "soft"
            shadow_sig["cheek_shadow"] = "moderate"
        else:
            shadow_sig["nose_shadow"] = "visible"
            shadow_sig["cheek_shadow"] = "strong"

    entry = {
        "reference_id": reference_id,
        "photographer": photographer,
        "lighting_pattern": lighting_pattern,
        "environment": reconstruction.get("environment_class", "studio"),
        "lights": lights,
        "shadow_signature": shadow_sig,
        "camera": {
            "height_relative": reconstruction.get("camera_height_relative_to_subject", "eye_level"),
        },
        "use_cases": [],
        "dataset_tier": "community",
        "entry_trust_score": 0.5,
    }

    entries = _load_reference_library()
    entries.append(entry)
    _save_reference_library(entries)

    try:
        from engine.reference_matcher import reload_references
        reload_references()
    except Exception:
        pass

    return entry


# ═══════════════════════════════════════════════════════════════════════════
# REFERENCE DATASET (image-backed, pipeline-processed references)
# ═══════════════════════════════════════════════════════════════════════════


class ReferenceDatasetIngestMeta(BaseModel):
    """Metadata for dataset reference image ingestion."""
    reference_id: str
    pattern_id: str
    photographer: str = ""
    dataset_tier: str = "community"
    entry_trust_score: float = 0.5
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    environment: Optional[str] = None
    light_count: Optional[int] = None
    key_direction_deg: Optional[float] = None
    key_height_relative: Optional[str] = None
    shadow_pattern: Optional[str] = None
    modifier_family: Optional[str] = None
    estimated_distance_ft: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    title: Optional[str] = None
    # Archetype-related fields
    style_family: Optional[str] = None          # beauty|editorial|dramatic|natural|high_key|low_key
    catchlight_pattern: Optional[str] = None    # single|dual|triangular|strip|ring
    underfill_ev: Optional[float] = None        # EV difference key vs fill
    separation_light_type: Optional[str] = None # hair|rim|kicker|none
    source_type_candidates: Optional[List[str]] = None  # ["continuous_led", "strobe"]
    light_technology: Optional[str] = None      # continuous_led|continuous_panel|strobe|flash|mixed
    master_profile_id: Optional[str] = None     # penn|karsh|leibovitz|hurley|etc


DATASET_UPLOAD_DIR = DATA_DIR / "uploads" / "reference_dataset"
DATASET_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/reference-dataset/ingest")
async def ingest_dataset_reference(
    image: UploadFile = File(...),
    metadata_json: str = Query(..., description="JSON string of metadata"),
    run_pipeline: bool = Query(True, description="Run full vision pipeline"),
    run_vlm: bool = Query(True, description="Run VLM reconstruction"),
    overwrite: bool = Query(False, description="Overwrite existing entry"),
    user: Dict = Depends(get_dev_user),
):
    """Ingest a reference image into the reference dataset.

    Runs the full extended vision pipeline, stores signals, VLM reconstruction,
    debug overlay, and metadata.

    The metadata_json query parameter should be a JSON string matching
    the ReferenceDatasetIngestMeta schema.
    """
    from engine.reference_dataset import ingest_reference_image as _ingest

    image_content = await _validate_upload(image)

    # Parse metadata
    try:
        meta_raw = json.loads(metadata_json)
        meta_model = ReferenceDatasetIngestMeta(**meta_raw)
        metadata = meta_model.model_dump(exclude_none=True)
    except (json.JSONDecodeError, Exception) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid metadata JSON: {exc}")

    # Preserve original filename in metadata (persisted to metadata.json by _ingest)
    original_filename = image.filename or "image.jpg"
    if "original_filename" not in metadata:
        metadata["original_filename"] = original_filename

    # Save uploaded image to temp location (temp name — cleaned up after ingest)
    ext = Path(original_filename).suffix.lower() or ".jpg"
    fname = canonical_upload_name(original_filename, origin="ds_tmp",
                                  pattern=metadata.get("pattern_id", "unknown"))
    tmp_path = DATASET_UPLOAD_DIR / fname

    with open(tmp_path, "wb") as f:
        f.write(image_content)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                _ingest,
                tmp_path,
                metadata,
                run_pipeline=run_pipeline,
                run_vlm=run_vlm,
                overwrite=overwrite,
            ),
        )
        result["ingested_by"] = user.get("email")
        return result

    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Dataset ingestion failed: {exc}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/reference-dataset")
async def list_dataset_entries(
    pattern_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="draft | approved | rejected"),
    tier: Optional[str] = Query(None, description="gold | community | synthetic"),
    user: Dict = Depends(get_dev_user),
):
    """List reference dataset entries with optional filters."""
    from engine.reference_dataset import list_entries

    entries = list_entries(pattern_id=pattern_id, status=status, tier=tier)
    return {"entries": entries, "count": len(entries)}


@router.get("/reference-dataset/version")
async def get_dataset_version_info(user: Dict = Depends(get_dev_user)):
    """Get dataset version information."""
    from engine.reference_dataset import get_dataset_version

    return get_dataset_version()


@router.get("/reference-dataset/manifest")
async def get_dataset_manifest(user: Dict = Depends(get_dev_user)):
    """Export full dataset manifest with statistics."""
    from engine.reference_dataset import export_dataset_manifest

    return export_dataset_manifest()


@router.get("/reference-dataset/{pattern_id}/{reference_id}")
async def get_dataset_entry(
    pattern_id: str,
    reference_id: str,
    include_signals: bool = Query(True),
    include_vlm: bool = Query(True),
    user: Dict = Depends(get_dev_user),
):
    """Get a single reference dataset entry with full data."""
    from engine.reference_dataset import get_entry

    entry = get_entry(
        pattern_id, reference_id,
        include_signals=include_signals,
        include_vlm=include_vlm,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset entry not found")
    return entry


@router.get("/reference-dataset/{pattern_id}/{reference_id}/image")
async def serve_dataset_image(
    pattern_id: str,
    reference_id: str,
    user: Dict = Depends(get_dev_user),
):
    """Serve the original reference image."""
    from fastapi.responses import FileResponse
    from engine.reference_dataset import DATASET_ROOT

    image_path = DATASET_ROOT / pattern_id / reference_id / "image.jpg"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(image_path), media_type="image/jpeg")


@router.get("/reference-dataset/{pattern_id}/{reference_id}/thumbnail")
async def serve_dataset_thumbnail(
    pattern_id: str,
    reference_id: str,
    user: Dict = Depends(get_dev_user),
):
    """Serve the thumbnail image."""
    from fastapi.responses import FileResponse
    from engine.reference_dataset import DATASET_ROOT

    thumb_path = DATASET_ROOT / pattern_id / reference_id / "thumbnail.jpg"
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(str(thumb_path), media_type="image/jpeg")


@router.get("/reference-dataset/{pattern_id}/{reference_id}/debug-overlay")
async def serve_dataset_debug_overlay(
    pattern_id: str,
    reference_id: str,
    user: Dict = Depends(get_dev_user),
):
    """Serve the debug overlay image."""
    from fastapi.responses import FileResponse
    from engine.reference_dataset import DATASET_ROOT

    overlay_path = DATASET_ROOT / pattern_id / reference_id / "debug_overlay.png"
    if not overlay_path.exists():
        raise HTTPException(status_code=404, detail="Debug overlay not found")
    return FileResponse(str(overlay_path), media_type="image/png")


@router.post("/reference-dataset/{pattern_id}/{reference_id}/approve")
async def approve_dataset_entry(
    pattern_id: str,
    reference_id: str,
    user: Dict = Depends(get_dev_user),
):
    """Approve a reference dataset entry."""
    from engine.reference_dataset import approve_entry

    try:
        meta = approve_entry(
            pattern_id, reference_id,
            approved_by=user.get("email", "unknown"),
        )
        log_admin_change("reference", f"{pattern_id}/{reference_id}", "approve", {
            "by": user.get("email", "unknown"),
        })
        return {"status": "approved", "metadata": meta}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reference-dataset/{pattern_id}/{reference_id}/reject")
async def reject_dataset_entry(
    pattern_id: str,
    reference_id: str,
    reason: str = Query("", description="Rejection reason"),
    user: Dict = Depends(get_dev_user),
):
    """Reject a reference dataset entry."""
    from engine.reference_dataset import reject_entry

    try:
        meta = reject_entry(pattern_id, reference_id, reason=reason)
        log_admin_change("reference", f"{pattern_id}/{reference_id}", "reject", {
            "by": user.get("email", "unknown"),
            "reason": reason,
        })
        return {"status": "rejected", "metadata": meta}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(100, ge=1, le=500),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    user: Dict = Depends(get_dev_user),
):
    """Unified audit log — all admin actions across gold set, candidates, references, etc."""
    entries = get_admin_changelog(limit=limit)
    if entity_type:
        entries = [e for e in entries if e["entity_type"] == entity_type]
    return {"entries": entries, "count": len(entries)}


@router.get("/alert-check")
async def check_alerts(
    hours: int = Query(24, ge=1, le=168),
    user: Dict = Depends(get_dev_user),
):
    """Evaluate production alert rules against current metrics. Persists state transitions."""
    from db.database import get_vlm_call_stats, log_alert_event, get_alert_events, get_db
    import json as _json

    stats = get_vlm_call_stats(hours=hours)

    # Count analyses needing review
    with get_db() as conn:
        cutoff = __import__('time').time() - hours * 3600
        total_analyses = conn.execute(
            "SELECT COUNT(*) FROM analysis_results WHERE created_at > ?", (cutoff,)
        ).fetchone()[0]
        # Count review flags from result_json
        review_rows = conn.execute(
            "SELECT result_json FROM analysis_results WHERE created_at > ?", (cutoff,)
        ).fetchall()
    review_count = 0
    paradox_count = 0
    for row in review_rows:
        try:
            rj = _json.loads(row["result_json"]) if row["result_json"] else {}
            if rj.get("needs_review"):
                review_count += 1
            notes = rj.get("notes") or []
            for n in notes:
                if isinstance(n, str) and "paradox" in n.lower():
                    paradox_count += 1
                    break
        except Exception:
            pass

    review_rate = review_count / max(total_analyses, 1)
    paradox_rate = paradox_count / max(total_analyses, 1)
    today_cost = stats.get("daily_cost", [{}])[0].get("cost_usd", 0) if stats.get("daily_cost") else 0

    # ── Production alert rules ──
    RULES = [
        {"id": "vlm_error_rate",   "label": "VLM Error Rate",    "value": stats.get("error_rate", 0),     "warn": 0.08, "alert": 0.15},
        {"id": "vlm_no_calls",     "label": "VLM Call Volume",   "value": stats.get("total", 0),          "warn": 5,    "alert": 0,    "invert": True},
        {"id": "vlm_p95_latency",  "label": "VLM p95 Latency",   "value": stats.get("p95_latency_ms"),    "warn": 3600, "alert": 6000},
        {"id": "vlm_avg_latency",  "label": "VLM Avg Latency",   "value": stats.get("avg_latency_ms"),    "warn": 2000, "alert": 3000},
        {"id": "daily_cost",       "label": "Daily VLM Cost",     "value": today_cost,                     "warn": 30,   "alert": 50},
        {"id": "review_rate",      "label": "Review Rate",        "value": round(review_rate, 4),          "warn": 0.05, "alert": 0.10},
        {"id": "paradox_rate",     "label": "Paradox Rate",       "value": round(paradox_rate, 4),          "warn": 0.01, "alert": 0.02},
        {"id": "total_analyses",   "label": "Analysis Volume",    "value": total_analyses,                  "warn": 1,    "alert": 0,    "invert": True},
    ]

    # Evaluate each rule
    results = []
    for rule in RULES:
        v = rule["value"]
        if v is None:
            state = "unknown"
        elif rule.get("invert"):
            # Lower is worse (e.g., call volume)
            state = "alert" if v <= rule["alert"] else "warn" if v <= rule["warn"] else "ok"
        else:
            state = "alert" if v >= rule["alert"] else "warn" if v >= rule["warn"] else "ok"

        results.append({
            "id": rule["id"], "label": rule["label"],
            "value": v, "state": state,
            "warn_threshold": rule["warn"], "alert_threshold": rule["alert"],
        })

    # Load previous states and persist transitions
    prev_events = get_alert_events(limit=100)
    prev_states = {}
    for ev in prev_events:
        if ev["rule_id"] not in prev_states:
            prev_states[ev["rule_id"]] = ev["new_state"]

    transitions = []
    for r in results:
        prev = prev_states.get(r["id"], "ok")
        if prev != r["state"] and r["state"] in ("warn", "alert"):
            log_alert_event(r["id"], prev, r["state"],
                           value=str(r["value"]), threshold=str(r["alert_threshold"]))
            transitions.append({"rule": r["label"], "from": prev, "to": r["state"], "value": r["value"]})

    return {
        "rules": results,
        "transitions": transitions,
        "total_analyses": total_analyses,
        "review_count": review_count,
        "paradox_count": paradox_count,
        "window_hours": hours,
    }


@router.get("/alert-history")
async def alert_history(
    limit: int = Query(50, ge=1, le=200),
    user: Dict = Depends(get_dev_user),
):
    """Return persisted alert event history."""
    from db.database import get_alert_events
    return {"events": get_alert_events(limit=limit)}


@router.get("/vlm-corrections")
async def vlm_corrections(user: Dict = Depends(get_dev_user)):
    """Summary of VLM overrides/enrichments vs CV — reveals systematic CV gaps."""
    from engine.vlm_improvement_log import read_improvement_summary
    return read_improvement_summary()


class ReferenceDatasetMetadataUpdate(BaseModel):
    """Partial metadata update for a reference dataset entry.

    Only user-owned fields are accepted.  System-managed fields
    (reference_id, pattern_id, approval_status, ingested_at, etc.)
    are stripped server-side even if submitted.
    """
    photographer: Optional[str] = None
    title: Optional[str] = None
    dataset_tier: Optional[str] = None          # gold | community | synthetic
    entry_trust_score: Optional[float] = None   # 0.0 – 1.0
    source_type: Optional[str] = None           # original_photo | screenshot | studio_test | found_online | book_scan | ai_generated
    source_url: Optional[str] = None
    environment: Optional[str] = None           # studio | natural | window_light | outdoor | mixed | unknown
    light_count: Optional[int] = None
    key_direction_deg: Optional[float] = None   # 0 – 360
    key_height_relative: Optional[str] = None   # below_eye_level | eye_level | above_eye_level | high | overhead
    shadow_pattern: Optional[str] = None
    modifier_family: Optional[str] = None
    estimated_distance_ft: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    # Archetype
    style_family: Optional[str] = None          # beauty | editorial | dramatic | natural | high_key | low_key
    catchlight_pattern: Optional[str] = None    # single | dual | triangular | strip | ring
    underfill_ev: Optional[float] = None
    separation_light_type: Optional[str] = None # hair | rim | kicker | none
    light_technology: Optional[str] = None      # continuous_led | continuous_panel | strobe | flash | mixed
    master_profile_id: Optional[str] = None


@router.patch("/reference-dataset/{pattern_id}/{reference_id}")
async def update_dataset_entry_metadata(
    pattern_id: str,
    reference_id: str,
    body: ReferenceDatasetMetadataUpdate,
    user: Dict = Depends(get_dev_user),
):
    """Partially update user-owned metadata fields for a reference dataset entry.

    Enum fields are validated server-side.  System fields are ignored.
    """
    from engine.reference_dataset import update_reference_metadata

    # Only send fields that were explicitly set (not None by default)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    try:
        updated = update_reference_metadata(pattern_id, reference_id, updates)
        return {"ok": True, "metadata": updated, "updated_by": user.get("email")}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}")


@router.post("/reference-dataset/{pattern_id}/{reference_id}/reprocess")
async def reprocess_dataset_entry(
    pattern_id: str,
    reference_id: str,
    run_vlm: bool = Query(True),
    user: Dict = Depends(get_dev_user),
):
    """Re-run the pipeline and VLM on an existing entry."""
    from engine.reference_dataset import reprocess_entry

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(reprocess_entry, pattern_id, reference_id, run_vlm=run_vlm),
        )
        result["reprocessed_by"] = user.get("email")
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reprocessing failed: {exc}")


# ── Monitoring Stats ───────────────────────────────────────────────────────────

@router.get("/monitoring-stats")
async def get_monitoring_stats(
    hours: int = Query(24, ge=1, le=720),
    user: Dict = Depends(get_dev_user),
):
    """
    Single endpoint for the Monitoring section: VLM sparkline, analysis funnel,
    and Stripe webhook health.  Returns all three datasets in one round trip.

    Bucketing: hourly for windows ≤ 48 h, daily for longer windows.
    """
    cutoff = time.time() - hours * 3600

    with get_db() as conn:
        # ── VLM sparkline ─────────────────────────────────────────────────────
        vlm_rows = conn.execute(
            "SELECT called_at, ok FROM vlm_call_metrics WHERE called_at > ? ORDER BY called_at DESC",
            (cutoff,),
        ).fetchall()

        now = time.time()
        # Use daily buckets for windows longer than 48 h to keep bar count sane
        if hours > 48:
            bucket_secs = 86400          # 1 day
            n_buckets   = max(hours // 24, 1)
            bucket_unit = "day"
        else:
            bucket_secs = 3600           # 1 hour
            n_buckets   = hours
            bucket_unit = "hour"

        ok_buckets: Dict[int, int] = {}
        err_buckets: Dict[int, int] = {}
        for r in vlm_rows:
            idx = int((now - r["called_at"]) // bucket_secs)
            if idx < n_buckets:
                if r["ok"]:
                    ok_buckets[idx] = ok_buckets.get(idx, 0) + 1
                else:
                    err_buckets[idx] = err_buckets.get(idx, 0) + 1

        sparkline = [
            {
                "hours_ago": h * (bucket_secs // 3600),
                "ok":    ok_buckets.get(h, 0),
                "err":   err_buckets.get(h, 0),
                "total": ok_buckets.get(h, 0) + err_buckets.get(h, 0),
            }
            for h in range(n_buckets)
        ]

        # ── Analysis funnel (VLM calls by caller, last N hours) ──────────────
        total_vlm   = len(vlm_rows)
        ok_vlm      = sum(1 for r in vlm_rows if r["ok"])
        err_vlm     = total_vlm - ok_vlm

        # Distinct sessions that ran at least one analysis
        session_rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_analysis_counts WHERE updated_at > ?",
            (cutoff,),
        ).fetchone()
        active_sessions = session_rows["cnt"] if session_rows else 0

        funnel = {
            "sessions_with_analysis": active_sessions,
            "vlm_calls_total":  total_vlm,
            "vlm_calls_ok":     ok_vlm,
            "vlm_calls_error":  err_vlm,
            "success_rate":     round(ok_vlm / total_vlm, 3) if total_vlm else None,
        }

        # ── Stripe webhook health ─────────────────────────────────────────────
        sub_rows = conn.execute(
            "SELECT id, customer_email, plan, billing_period, status, created_at "
            "FROM subscriptions ORDER BY created_at DESC LIMIT 10",
        ).fetchall()
        subs = [dict(r) for r in sub_rows]
        last_webhook_at = subs[0]["created_at"] if subs else None
        active_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM subscriptions WHERE status='active'"
        ).fetchone()["cnt"]

    stripe_health = {
        "webhook_secret_configured": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        "last_webhook_at":   last_webhook_at,
        "total_active_subs": active_count,
        "recent_subs":       subs[:5],
    }

    return {
        "window_hours": hours,
        "bucket_unit":  bucket_unit,
        "sparkline":    sparkline,
        "funnel":       funnel,
        "stripe":       stripe_health,
    }


# ── L1 Stream — recent analysis observability records ─────────────────────────

@router.get("/l1-stream")
async def get_l1_stream(
    limit: int = Query(100, ge=1, le=500),
    user_email: Optional[str] = Query(None),
    pattern: Optional[str] = Query(None),
    flags: Optional[str] = Query(None),  # "review" | "contradiction" | "paradox"
    search: Optional[str] = Query(None),  # partial match on analysis_id or image_path
    user: Dict = Depends(get_dev_user),
):
    """Return lightweight L1 telemetry for the most recent analyses.

    Supports server-side filtering by user_email, pattern, flags, and
    a free-text search across analysis_id and image_path.
    """
    import json as _j

    where_clauses = []
    params: list = []

    if user_email:
        where_clauses.append("user_email LIKE ?")
        params.append(f"%{user_email}%")
    if search:
        where_clauses.append("(analysis_id LIKE ? OR image_path LIKE ?)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT analysis_id, image_path, system_version, result_json, created_at, user_email "
            f"FROM analysis_results {where_sql} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()

    records = []
    for row in rows:
        try:
            rj = _j.loads(row["result_json"]) if row["result_json"] else {}
        except Exception:
            rj = {}

        pc = rj.get("pattern_candidates") or {}
        notes = rj.get("notes") or []

        paradoxes: list = []
        for note in notes:
            if isinstance(note, str) and note.startswith("signal_paradoxes detected:"):
                payload = note.split(":", 1)[1].strip()
                paradoxes = [p.strip() for p in payload.split(",") if p.strip()]
                break

        st = rj.get("stage_timings") or {}
        ecf = rj.get("edge_case_flags") or {}
        active_edge = [k for k, v in ecf.items() if v is True] if isinstance(ecf, dict) else []

        # Apply post-fetch pattern/flags filters (done in Python since stored in JSON)
        resolved_pattern = rj.get("authoritative_pattern") or "unknown"
        if pattern and pattern.lower() not in resolved_pattern.lower():
            continue
        has_review = bool(pc.get("needs_review", False))
        has_contradiction = bool(pc.get("contradictions"))
        if flags == "review" and not has_review:
            continue
        if flags == "contradiction" and not has_contradiction:
            continue
        if flags == "paradox" and not paradoxes:
            continue

        records.append({
            "analysis_id":      row["analysis_id"],
            "user_email":       row["user_email"],
            "image_path":       row["image_path"],
            "system_version":   row["system_version"],
            "created_at":       row["created_at"],
            "pattern":          resolved_pattern,
            "confidence":       rj.get("pattern_confidence"),
            "confidence_label": rj.get("pattern_confidence_label"),
            "source":           rj.get("authoritative_pattern_source"),
            "needs_review":     has_review,
            "contradictions":   pc.get("contradictions") or [],
            "active_paradoxes": paradoxes,
            "active_edge_cases": active_edge,
            "total_time_s":     st.get("total"),
        })

    return {"count": len(records), "records": records}


# ── Server Logs ───────────────────────────────────────────────────────────────

@router.get("/server-logs")
async def get_server_logs(
    limit: int = Query(200, ge=1, le=1000),
    level: Optional[str] = Query(None),   # DEBUG | INFO | WARNING | ERROR | CRITICAL
    search: Optional[str] = Query(None, max_length=200),
    user_email: Optional[str] = Query(None, alias="user_email", max_length=200),
    session_id: Optional[str] = Query(None, alias="session_id", max_length=200),
    logger_name: Optional[str] = Query(None, alias="logger", max_length=200),
    since: Optional[float] = Query(None, description="Unix timestamp lower bound"),
    until: Optional[float] = Query(None, description="Unix timestamp upper bound"),
    user: Dict = Depends(get_dev_user),
):
    """Return recent in-process log records from the memory buffer.

    Records are newest-first.  The buffer holds the last 1000 lines emitted
    by any logger in the process (noisy HTTP access logs suppressed).

    New filters: user_email, session_id, logger (prefix match), since/until (Unix ts).
    """
    from engine.log_buffer import get_records
    records = get_records(
        limit=limit,
        level=level or None,
        search=search or None,
        user_email=user_email or None,
        session_id=session_id or None,
        logger_name=logger_name or None,
        since=since,
        until=until,
    )
    return {"records": records, "count": len(records)}


@router.delete("/l1-stream")
async def clear_l1_stream(user: Dict = Depends(get_dev_user)):
    """Delete all analysis results from the L1 stream."""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM analysis_results").fetchone()[0]
        conn.execute("DELETE FROM analysis_results")
        conn.commit()
    return {"ok": True, "deleted": count}


@router.delete("/server-logs")
async def clear_server_logs(user: Dict = Depends(get_dev_user)):
    """Clear the in-memory server log buffer."""
    from engine.log_buffer import clear_records
    clear_records()
    return {"ok": True}


@router.get("/server-logs/export")
async def export_server_logs(
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    user_email: Optional[str] = Query(None, max_length=200),
    session_id: Optional[str] = Query(None, max_length=200),
    logger_name: Optional[str] = Query(None, alias="logger", max_length=200),
    since: Optional[float] = Query(None),
    until: Optional[float] = Query(None),
    user: Dict = Depends(get_dev_user),
):
    """Export full log buffer as downloadable JSON (up to 1000 records)."""
    from engine.log_buffer import get_records
    records = get_records(
        limit=1000,
        level=level or None,
        search=search or None,
        user_email=user_email or None,
        session_id=session_id or None,
        logger_name=logger_name or None,
        since=since,
        until=until,
    )
    import io
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse

    def _generate():
        yield "[\n"
        for i, r in enumerate(records):
            ts_str = datetime.fromtimestamp(r["ts"], tz=timezone.utc).isoformat()
            line = json.dumps({**r, "ts_iso": ts_str}, default=str)
            yield ("  " + line + (",\n" if i < len(records) - 1 else "\n"))
        yield "]\n"

    ts_label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return StreamingResponse(
        _generate(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="ngw_logs_{ts_label}.json"'},
    )


# ── API Metrics ────────────────────────────────────────────────────────────────

@router.get("/api-metrics")
async def get_api_metrics(
    hours: int = Query(24, ge=1, le=720),
    user: Dict = Depends(get_dev_user),
):
    """
    Return aggregated VLM call metrics for the last N hours.
    Includes call count, error rate, avg/p95 latency, hourly buckets, and recent calls.
    Also reports whether VLM is currently configured so the UI can show a clear state.
    """
    from db.database import get_vlm_call_stats
    from engine.vlm import vlm_available, _VLM_PROVIDER, _VLM_MODEL, _vlm_probe_result
    stats = get_vlm_call_stats(hours=hours)
    stats["vlm_configured"] = vlm_available()
    stats["vlm_provider"]   = _VLM_PROVIDER
    stats["vlm_model"]      = _VLM_MODEL or None
    # Probe status: None = not probed, {"ok": True/False, ...}
    stats["vlm_probe_ok"]   = _vlm_probe_result["ok"] if _vlm_probe_result else None
    stats["vlm_probe_detail"] = _vlm_probe_result.get("detail") if _vlm_probe_result else None
    return stats


# ── Failure Triage (LAB Build 2) ───────────────────────────────────────────────
#
# DATA QUALITY NOTES:
#   - vlm_disagreements stores VLM hint vs. resolved value per field, per analysis.
#   - There is NO predicted_pattern / ground_truth_pattern column.
#     Instead: field_name (e.g. 'pattern'), vlm_value (VLM's suggestion),
#              resolved_value (what the pipeline resolved to), agreement
#              ('confirmed' | 'conflicting' | 'vlm_only').
#   - "Overconfident miss" = agreement='conflicting' AND vlm_confidence >= threshold
#     (VLM was confident but disagreed with CV resolver — a candidate failure case).
#   - "Underconfident hit" = agreement='confirmed' AND vlm_confidence < threshold
#     (VLM agreed with CV but was uncharacteristically uncertain).
#   - There is NO join path from vlm_disagreements to image_ground_truth
#     (vlm_disagreements has analysis_id; image_ground_truth has image_path only).
#   - There is NO image_path column on vlm_disagreements — the image path
#     is not stored in that table.
#   - "ground_truth_pattern" in responses = resolved_value (CV-resolved, not human-labeled).
#   - "confidence" in responses = vlm_confidence (VLM's confidence, not CV confidence).
#   - No status/dismissed column on vlm_disagreements — dismiss is frontend-only in v1.


class TriageSendToGoldSetBody(BaseModel):
    image_path: str
    predicted_pattern: str
    ground_truth_pattern: str
    confidence: float
    analysis_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("/failure-triage/overconfident")
async def failure_triage_overconfident(
    limit:     int   = Query(20, ge=1, le=100),
    threshold: float = Query(0.65, ge=0.0, le=1.0),
    user:      Dict  = Depends(get_dev_user),
):
    """Return VLM disagreement cases where VLM was confident but conflicted with CV resolver.

    DATA QUALITY NOTE: These are NOT human-verified failures.  They represent cases where
    the VLM hint disagreed with the rule-based CV resolver at high confidence.  The resolver
    may be wrong in some cases — treat these as candidate review items, not confirmed errors.

    Columns returned:
      - id:                   vlm_disagreements.id
      - analysis_id:          analysis run identifier
      - field_name:           which field disagreed (e.g. 'pattern')
      - predicted_pattern:    vlm_value  (what VLM predicted)
      - ground_truth_pattern: resolved_value (what CV resolver decided — NOT human-labeled)
      - confidence:           vlm_confidence
      - pipeline_version:     pipeline version string
      - created_at:           epoch timestamp
      - descriptor:           "High confidence miss"
    """
    from db.database import get_db
    params: list = [threshold, limit]
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, analysis_id, field_name, vlm_value, vlm_confidence,
                      resolved_value, resolved_source, agreement,
                      disagreement_magnitude, pipeline_version, created_at
               FROM vlm_disagreements
               WHERE agreement = 'conflicting'
                 AND vlm_confidence >= ?
               ORDER BY vlm_confidence DESC
               LIMIT ?""",
            params,
        ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id":                   r["id"],
            "analysis_id":          r["analysis_id"],
            "field_name":           r["field_name"],
            "predicted_pattern":    r["vlm_value"],
            "ground_truth_pattern": r["resolved_value"],   # CV-resolved, not human-labeled
            "confidence":           r["vlm_confidence"],
            "resolved_source":      r["resolved_source"],
            "disagreement_magnitude": r["disagreement_magnitude"],
            "pipeline_version":     r["pipeline_version"],
            "created_at":           r["created_at"],
            "descriptor":           "High confidence miss",
        })
    return {
        "total":     len(items),
        "threshold": threshold,
        "items":     items,
        "data_note": (
            "ground_truth_pattern = CV-resolved value, not human-labeled. "
            "No image_path available in vlm_disagreements table. "
            "Dismiss is frontend-only in v1 (no dismissed column in schema)."
        ),
    }


@router.get("/failure-triage/underconfident")
async def failure_triage_underconfident(
    limit:     int   = Query(20, ge=1, le=100),
    threshold: float = Query(0.45, ge=0.0, le=1.0),
    user:      Dict  = Depends(get_dev_user),
):
    """Return VLM cases where VLM agreed with CV resolver but at low confidence.

    DATA QUALITY NOTE: These are cases where VLM confirmed the CV resolver's result
    but appeared uncertain.  They may indicate boundary cases worth adding to the gold set
    for coverage, but they are NOT confirmed failures.

    Uses the same vlm_disagreements table with agreement='confirmed' AND
    vlm_confidence < threshold.  Sorted confidence ASC (least confident first).
    """
    from db.database import get_db
    params: list = [threshold, limit]
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, analysis_id, field_name, vlm_value, vlm_confidence,
                      resolved_value, resolved_source, agreement,
                      disagreement_magnitude, pipeline_version, created_at
               FROM vlm_disagreements
               WHERE agreement = 'confirmed'
                 AND vlm_confidence IS NOT NULL
                 AND vlm_confidence < ?
               ORDER BY vlm_confidence ASC
               LIMIT ?""",
            params,
        ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id":                   r["id"],
            "analysis_id":          r["analysis_id"],
            "field_name":           r["field_name"],
            "predicted_pattern":    r["vlm_value"],
            "ground_truth_pattern": r["resolved_value"],   # CV-resolved, matches VLM here
            "confidence":           r["vlm_confidence"],
            "resolved_source":      r["resolved_source"],
            "disagreement_magnitude": r["disagreement_magnitude"],
            "pipeline_version":     r["pipeline_version"],
            "created_at":           r["created_at"],
            "descriptor":           "Low confidence hit",
        })
    return {
        "total":     len(items),
        "threshold": threshold,
        "items":     items,
        "data_note": (
            "agreement='confirmed' means VLM agreed with CV resolver. "
            "Low vlm_confidence here suggests boundary / uncertain case. "
            "No image_path available in vlm_disagreements table. "
            "Dismiss is frontend-only in v1."
        ),
    }


@router.post("/failure-triage/send-to-gold-set", status_code=201)
async def failure_triage_send_to_gold_set(
    body: TriageSendToGoldSetBody,
    user: Dict = Depends(get_dev_user),
):
    """Create a DRAFT gold set entry from a triage item.

    Status is always set to 'draft' — requires explicit review/approval before
    being used for evaluation.  Never auto-approves.
    """
    # Build expected_analysis from the triage data — captures the intended correction.
    expected_analysis: Dict[str, Any] = {
        "pattern":             body.ground_truth_pattern,
        "triage_source":       "failure_triage",
        "vlm_predicted":       body.predicted_pattern,
        "vlm_confidence":      body.confidence,
    }
    if body.analysis_id:
        expected_analysis["source_analysis_id"] = body.analysis_id

    notes_parts = []
    if body.notes:
        notes_parts.append(body.notes)
    notes_parts.append(
        f"Queued from Failure Triage — predicted={body.predicted_pattern!r}, "
        f"resolved={body.ground_truth_pattern!r}, confidence={body.confidence:.3f}"
    )

    entry = create_gold_set_entry(
        image_path=body.image_path,
        expected_analysis=expected_analysis,
        notes=" | ".join(notes_parts),
        status="draft",   # NEVER auto-approve
        created_by=user.get("email", "triage"),
    )
    return {"created": True, "id": entry["id"], "status": entry["status"]}


# ── Layer 4: Calibration surface ─────────────────────────────────────────────

@router.get("/calibration/suggestions")
def calibration_suggestions(
    days: int = Query(30, ge=7, le=180),
    user: Dict = Depends(get_dev_user),
):
    """Return per-pattern recalibration suggestions.

    Surfaces patterns where avg_confidence exceeds success_rate by > 10pp,
    with >= 5 live sessions. Each suggestion includes a suggested_floor
    that can be approved via POST /calibration/apply.
    """
    from db.signals import get_recalibration_hints, get_confidence_calibration
    hints = get_recalibration_hints(days=days)
    calibration = get_confidence_calibration(days=days)
    return {
        "days": days,
        "suggestions": hints,
        "calibration": calibration,
    }


@router.get("/calibration/current")
def calibration_current(user: Dict = Depends(get_dev_user)):
    """Return current confidence_overrides.json contents (active floors)."""
    overrides_path = Path(__file__).resolve().parent.parent.parent / "engine" / "confidence_overrides.json"
    if not overrides_path.exists():
        return {"overrides": {}, "path": str(overrides_path), "exists": False}
    try:
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception:
        overrides = {}
    return {"overrides": overrides, "path": str(overrides_path), "exists": True}


class CalibrationApplyBody(BaseModel):
    floors: Dict[str, float] = Field(..., description="pattern_id → confidence floor value")
    notes: str = ""


@router.post("/calibration/apply")
def calibration_apply(
    body: CalibrationApplyBody,
    user: Dict = Depends(get_dev_user),
):
    """Apply reviewed confidence floors to confidence_overrides.json.

    Each floor entry is merged into the existing overrides file. Floors reduce
    over-confident predictions — they never inflate. Engine restart required.

    SAFETY: This only writes the file. The resolver loads it on startup.
    No automatic engine restart is performed.
    """
    overrides_path = Path(__file__).resolve().parent.parent.parent / "engine" / "confidence_overrides.json"
    overrides: dict = {}
    if overrides_path.exists():
        try:
            overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        except Exception:
            overrides = {}

    reviewer = user.get("email", "lab")
    applied = []
    for pattern_id, floor_val in body.floors.items():
        if floor_val < 0.0 or floor_val > 1.0:
            continue  # skip invalid
        overrides[pattern_id] = {
            "confidence_floor": round(floor_val, 3),
            "applied_at":      time.time(),
            "applied_by":      reviewer,
            "reason":          "lab_calibration_review",
            "notes":           body.notes or "",
            "previous_floor":  overrides.get(pattern_id, {}).get("confidence_floor"),
        }
        applied.append(pattern_id)

    try:
        overrides_path.parent.mkdir(parents=True, exist_ok=True)
        overrides_path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write overrides: {exc}")

    return {
        "applied": True,
        "patterns": applied,
        "total_overrides": len(overrides),
        "restart_required": True,
        "message": (
            f"Applied confidence floors for {len(applied)} pattern(s). "
            "Engine restart required for changes to take effect."
        ),
    }
