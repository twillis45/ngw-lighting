from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import numpy as np

from engine.constants import (
    BG_ENV,
    CATCHLIGHT,
    PALETTE,
    POSE,
    SEGMENTATION,
    SKIN,
)

import logging as _logging
import platform as _platform
import os as _os

_vp_logger = _logging.getLogger(__name__)

try:
    import cv2
    import mediapipe as mp
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore
    mp = None  # type: ignore

_MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "mp_models"

# ── MediaPipe delegate selection ──────────────────────────────────────
# GPU delegate crashes on macOS headless (NSOpenGLPixelFormat unavailable).
# Use GPU only on Linux with a display or when explicitly requested.
_MP_MAX_DIM = int(_os.environ.get("NGW_MP_MAX_DIM", "2048"))
_MP_MIN_DIM = int(_os.environ.get("NGW_MP_MIN_DIM", "2048"))

def _mp_delegate():
    """Choose best MediaPipe delegate for this platform."""
    if mp is None:
        return None
    force = _os.environ.get("NGW_MP_DELEGATE", "").lower()
    if force == "gpu":
        return mp.tasks.BaseOptions.Delegate.GPU
    if force == "cpu":
        return mp.tasks.BaseOptions.Delegate.CPU
    # macOS has broken OpenGL in headless server contexts
    if _platform.system() == "Darwin":
        return mp.tasks.BaseOptions.Delegate.CPU
    # Linux with display — try GPU
    if _platform.system() == "Linux" and _os.environ.get("DISPLAY"):
        return mp.tasks.BaseOptions.Delegate.GPU
    return mp.tasks.BaseOptions.Delegate.CPU


# -------------------------
# Simple palette helper
# -------------------------

BASIC_COLOR_NAMES = [
    ("black", (0, 0, 0)),
    ("white", (255, 255, 255)),
    ("gray", (128, 128, 128)),
    ("red", (220, 20, 60)),
    ("orange", (255, 140, 0)),
    ("yellow", (255, 215, 0)),
    ("green", (34, 139, 34)),
    ("cyan", (0, 206, 209)),
    ("blue", (30, 144, 255)),
    ("purple", (138, 43, 226)),
    ("magenta", (255, 0, 255)),
    ("brown", (139, 69, 19)),
    ("beige", (245, 245, 220)),
]


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _dist2(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _nearest_basic_name(rgb: Tuple[int, int, int]) -> str:
    best = ("unknown", 10**18)
    for name, ref in BASIC_COLOR_NAMES:
        d = _dist2(rgb, ref)
        if d < best[1]:
            best = (name, d)
    return best[0]


def _kmeans_palette(pixels_rgb: np.ndarray, k: int = 5) -> List[Dict[str, Any]]:
    """
    pixels_rgb: Nx3 uint8
    Returns dominant colors with pct.
    """
    if pixels_rgb.size == 0:
        return []

    # downsample to keep it fast
    if pixels_rgb.shape[0] > 20000:
        idx = np.random.choice(pixels_rgb.shape[0], 20000, replace=False)
        pixels_rgb = pixels_rgb[idx]

    Z = pixels_rgb.astype(np.float32)

    # cv2.kmeans expects float32
    K = int(max(1, min(k, 8)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _compact, labels, centers = cv2.kmeans(Z, K, None, criteria, 5, cv2.KMEANS_PP_CENTERS)

    labels = labels.flatten()
    counts = np.bincount(labels, minlength=K).astype(np.float64)
    total = counts.sum() if counts.sum() > 0 else 1.0

    out = []
    for i in np.argsort(counts)[::-1]:
        rgb = centers[i].clip(0, 255).astype(np.uint8)
        rgb_t = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        out.append(
            {
                "rgb": [rgb_t[0], rgb_t[1], rgb_t[2]],
                "hex": _rgb_to_hex(rgb_t),
                "name": _nearest_basic_name(rgb_t),
                "pct": round(100.0 * (counts[i] / total), 2),
            }
        )
    return out


# -------------------------
# Masks: person, face, skin, clothing, background
# -------------------------

def _ycbcr_skin_mask(img_bgr: np.ndarray) -> np.ndarray:
    """
    Conservative YCbCr skin mask. Returns boolean mask HxW.
    """
    ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
    # OpenCV order: Y, Cr, Cb
    Y = ycrcb[:, :, 0]
    Cr = ycrcb[:, :, 1]
    Cb = ycrcb[:, :, 2]

    # conservative bounds
    mask = ((Cb >= SKIN.YCBCR_CB_MIN) & (Cb <= SKIN.YCBCR_CB_MAX) &
            (Cr >= SKIN.YCBCR_CR_MIN) & (Cr <= SKIN.YCBCR_CR_MAX) &
            (Y >= SKIN.YCBCR_Y_MIN) & (Y <= SKIN.YCBCR_Y_MAX))
    return mask


def _safe_box(x0: int, y0: int, x1: int, y1: int, w: int, h: int) -> Tuple[int, int, int, int]:
    x0 = max(0, min(x0, w - 1))
    y0 = max(0, min(y0, h - 1))
    x1 = max(1, min(x1, w))
    y1 = max(1, min(y1, h))
    if x1 <= x0 + 1:
        x1 = min(w, x0 + 2)
    if y1 <= y0 + 1:
        y1 = min(h, y0 + 2)
    return x0, y0, x1, y1


def _make_mp_image(img_rgb: np.ndarray):
    """Create a MediaPipe Image from an RGB numpy array."""
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)


def _pose_guess(img_bgr: np.ndarray) -> Dict[str, Any]:
    """
    Very basic pose inference:
    - standing/sitting/unknown from hip-knee-ankle geometry visibility and y ordering
    - angle: front/profile-ish from shoulder width
    """
    if mp is None:
        return {"ok": False, "error": "mediapipe not installed"}

    model_path = _MODEL_DIR / "pose_landmarker_lite.task"
    if not model_path.exists():
        return {"ok": False, "error": "pose model not found"}

    h, w = img_bgr.shape[:2]
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_image = _make_mp_image(img_rgb)

    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
            delegate=_mp_delegate(),
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
    )
    landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(opts)
    try:
        res = landmarker.detect(mp_image)
    finally:
        landmarker.close()

    if not res.pose_landmarks:
        return {"ok": False, "reason": "no_pose_detected"}

    lm = res.pose_landmarks[0]

    def L(i: int) -> Tuple[float, float, float]:
        return lm[i].x * w, lm[i].y * h, lm[i].visibility

    # landmark indices (mediapipe)
    # shoulders: 11,12 ; hips: 23,24 ; knees: 25,26 ; ankles: 27,28
    lsx, lsy, lsv = L(11)
    rsx, rsy, rsv = L(12)
    lhx, lhy, lhv = L(23)
    rhx, rhy, rhv = L(24)
    lkx, lky, lkv = L(25)
    rkx, rky, rkv = L(26)
    lax, lay, lav = L(27)
    rax, ray, rav = L(28)

    shoulder_vis = np.mean([lsv, rsv])
    lower_vis = np.mean([lhv, rhv, lkv, rkv, lav, rav])
    vis = np.mean([lsv, rsv, lhv, rhv, lkv, rkv, lav, rav])
    shoulder_w = abs(lsx - rsx)
    angle = "front-ish" if shoulder_w > (0.18 * w) else "profile-ish"

    # Detect framing from landmark visibility.
    # Headshots show shoulders but not lower body; half-body may show hips.
    if shoulder_vis > 0.3 and lower_vis < 0.15:
        framing = "headshot"
    elif shoulder_vis > 0.3 and np.mean([lhv, rhv]) > 0.3 and np.mean([lkv, rkv]) < 0.2:
        framing = "half_body"
    else:
        framing = "full_body"

    # Standing vs sitting heuristic:
    # If hips are above knees and knees above ankles with decent visibility -> standing likely
    # If knees/hips are close in y (knees high) or ankles missing -> sitting likely
    standing_score = 0
    sitting_score = 0

    # Full landmark path (hip + knee + ankle all reasonably visible)
    if lhv > 0.3 and lkv > 0.3 and lav > 0.25:
        if lhy < lky < lay:
            standing_score += 1
        if abs(lhy - lky) < 0.08 * h:
            sitting_score += 1
    if rhv > 0.3 and rkv > 0.3 and rav > 0.25:
        if rhy < rky < ray:
            standing_score += 1
        if abs(rhy - rky) < 0.08 * h:
            sitting_score += 1

    # Partial landmark path: hip + knee visible but ankle missing or low
    # If knees are near hip height, that's a sitting signal even without ankles
    if lhv > 0.25 and lkv > 0.25 and lav < 0.25:
        if abs(lhy - lky) < 0.10 * h:
            sitting_score += 1
    if rhv > 0.25 and rkv > 0.25 and rav < 0.25:
        if abs(rhy - rky) < 0.10 * h:
            sitting_score += 1

    # Knee-above-hip heuristic: if knees are higher than (or near) hips
    # in the frame, that's a strong seated/reclined signal
    if lhv > 0.2 and lkv > 0.2 and lky <= lhy:
        sitting_score += 1
    if rhv > 0.2 and rkv > 0.2 and rky <= rhy:
        sitting_score += 1

    if standing_score >= 1 and sitting_score == 0:
        pose_label = "standing"
    elif sitting_score >= 1:
        pose_label = "sitting"
    elif framing == "headshot":
        pose_label = "headshot"
    elif framing == "half_body":
        pose_label = "upper_body"
    else:
        pose_label = "unknown"

    return {
        "ok": True,
        "pose": pose_label,
        "framing": framing,
        "angle": angle,
        "visibility": float(vis),
        "notes": [
            "Pose is best-effort from landmarks; seated/leaning/cropped frames can confuse it.",
        ],
    }


def _pose_from_mask(person_mask: np.ndarray, img_bgr: np.ndarray) -> Dict[str, Any]:
    """Fallback pose/framing inference from the segmentation mask shape.

    When MediaPipe's pose landmarker fails (e.g. heavy B&W processing, extreme
    shadows), the person segmentation mask still gives us the subject's
    silhouette.  We use its bounding box, aspect ratio, and vertical extent
    to infer framing and a rough pose guess.
    """
    h, w = person_mask.shape[:2]
    total_px = h * w

    # Find mask bounding box via row/column projection
    rows = np.any(person_mask, axis=1)
    cols = np.any(person_mask, axis=0)
    if not np.any(rows) or not np.any(cols):
        return {"ok": False, "reason": "empty_mask"}

    row_min, row_max = np.where(rows)[0][[0, -1]]
    col_min, col_max = np.where(cols)[0][[0, -1]]

    mask_h = row_max - row_min + 1
    mask_w = col_max - col_min + 1
    aspect = mask_h / max(mask_w, 1)
    v_extent = mask_h / h  # how much of the image height the mask spans
    h_extent = mask_w / w
    v_center = (row_min + row_max) / 2 / h  # 0=top, 1=bottom

    # -- Framing from vertical extent --
    if v_extent > 0.75:
        framing = "full_body"
    elif v_extent > 0.50:
        framing = "half_body"
    else:
        framing = "headshot"

    # -- Pose from mask shape --
    # Seated: mask is wide relative to height (aspect < 1.3), or the bottom
    # of the mask is wide (legs extending forward), or the mask center of
    # mass is in the lower half.
    # Standing: tall narrow silhouette (aspect > 1.6)
    pose_label = "unknown"
    notes = ["Pose inferred from segmentation mask shape (landmarks unavailable)."]

    # Check if the mask is wider in the lower half (legs extending forward
    # while upper body is narrower → seated)
    mid_y = (row_min + row_max) // 2
    upper_width = int(np.sum(np.any(person_mask[:mid_y], axis=0)))
    lower_width = int(np.sum(np.any(person_mask[mid_y:], axis=0)))
    lower_wider = lower_width > upper_width * 1.15 if upper_width > 0 else False

    if framing == "headshot":
        pose_label = "headshot"
    elif lower_wider and v_extent > 0.5:
        # Lower half wider than upper → legs extending forward → seated
        pose_label = "sitting"
        notes.append(f"Lower body wider than upper ({lower_width} vs {upper_width}px) — seated/reclined.")
    elif aspect < 1.2 and v_extent > 0.5:
        pose_label = "sitting"
        notes.append(f"Mask aspect ratio ({aspect:.1f}) suggests seated/reclined pose.")
    elif aspect > 1.8 and v_extent > 0.7:
        pose_label = "standing"
        notes.append(f"Tall narrow silhouette (aspect {aspect:.1f}) suggests standing.")
    elif v_center > 0.55 and v_extent > 0.6:
        pose_label = "sitting"
        notes.append("Mask center of mass is low, suggesting seated pose.")
    elif aspect > 1.5:
        pose_label = "standing"
    else:
        notes.append(f"Mask aspect {aspect:.1f}, vertical extent {v_extent:.0%} — pose ambiguous.")

    # -- Angle from horizontal distribution --
    # If the mask is much wider than ~40% of the image, subject is more
    # front-facing; narrow mask suggests profile.
    angle = "front-ish" if h_extent > 0.35 else "profile-ish"

    return {
        "ok": True,
        "pose": pose_label,
        "framing": framing,
        "angle": angle,
        "visibility": float(np.mean(person_mask)),
        "source": "mask_fallback",
        "notes": notes,
    }


def _detect_background_environment(
    img_bgr: np.ndarray,
    background_mask: np.ndarray,
    is_grayscale: bool = False,
) -> Dict[str, Any]:
    """Detect background environment characteristics (outdoor, foliage, sunlight).

    Analyzes texture variance, edge density, and (for colour images) green
    channel dominance in the background region.
    """
    h, w = img_bgr.shape[:2]
    bg_pixels = np.sum(background_mask)
    if bg_pixels < BG_ENV.MIN_BG_PIXELS:
        return {"ok": False, "reason": "insufficient_background"}

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    bg_gray = gray.copy()
    bg_gray[~background_mask] = 0

    # Full background stats
    bg_vals = gray[background_mask]
    texture_std = float(np.std(bg_vals))
    mean_bg = float(np.mean(bg_vals))
    dark_ratio = float(np.sum(bg_vals < BG_ENV.DARK_BRIGHTNESS) / max(len(bg_vals), 1))

    # Edge density in background
    edges = cv2.Canny(bg_gray, BG_ENV.CANNY_LOW, BG_ENV.CANNY_HIGH)
    edge_ratio = float(np.sum(edges[background_mask] > 0) / max(bg_pixels, 1))

    # Also analyze the BRIGHT portion of the background separately.
    # In images with strong directional light the background can be mostly
    # black with pockets of illuminated detail (foliage, architecture, etc).
    bright_bg_mask = background_mask & (gray > BG_ENV.BRIGHT_BG_THRESHOLD)
    bright_bg_count = int(np.sum(bright_bg_mask))
    bright_std = 0.0
    bright_edge_ratio = 0.0
    if bright_bg_count > BG_ENV.MIN_BRIGHT_BG_PIXELS:
        bright_vals = gray[bright_bg_mask]
        bright_std = float(np.std(bright_vals))
        bright_edge_ratio = float(
            np.sum(edges[bright_bg_mask] > 0) / max(bright_bg_count, 1)
        )

    hints = []
    environment = "unknown"

    # High texture + high edges → outdoor / organic detail
    if texture_std > BG_ENV.TEXTURE_STD_ORGANIC and edge_ratio > BG_ENV.EDGE_RATIO_ORGANIC:
        hints.append("organic_texture")
        environment = "outdoor"
    # Bright-region analysis: even if the overall background is dark,
    # the illuminated portions may show organic texture
    elif bright_std > BG_ENV.BRIGHT_STD_FOLIAGE and bright_edge_ratio > BG_ENV.BRIGHT_EDGE_RATIO_OUTDOOR:
        hints.append("organic_texture")
        environment = "outdoor"

    # Check for foliage (green channel dominance) in colour images
    if not is_grayscale:
        bg_b, bg_g, bg_r = cv2.split(img_bgr)
        green_vals = bg_g[background_mask].astype(float)
        red_vals = bg_r[background_mask].astype(float)
        blue_vals = bg_b[background_mask].astype(float)
        green_dom = np.mean(green_vals) - 0.5 * (np.mean(red_vals) + np.mean(blue_vals))
        if green_dom > BG_ENV.GREEN_DOMINANCE:
            hints.append("foliage")
            environment = "outdoor"
    else:
        # In B&W, use bright-region texture + edge patterns as foliage proxy
        if bright_std > BG_ENV.BW_BRIGHT_STD_FOLIAGE and bright_edge_ratio > BG_ENV.BW_BRIGHT_EDGE_FOLIAGE:
            hints.append("possible_foliage")
            if environment == "unknown":
                environment = "outdoor"

    # Strong directional light: mix of very dark and textured bright areas
    if dark_ratio > BG_ENV.DARK_RATIO_DIRECTIONAL and bright_bg_count > BG_ENV.MIN_BRIGHT_BG_PIXELS and bright_std > BG_ENV.BW_BRIGHT_STD_FOLIAGE:
        hints.append("directional_light")
        if environment == "outdoor":
            hints.append("natural_sunlight")

    # Very uniform, dark background → studio
    if texture_std < BG_ENV.TEXTURE_STD_STUDIO and mean_bg < BG_ENV.MEAN_DARK_STUDIO and bright_bg_count < BG_ENV.MIN_BRIGHT_BG_PIXELS:
        environment = "studio"
        hints.append("dark_controlled_background")
    elif texture_std < BG_ENV.TEXTURE_STD_EVEN_STUDIO and dark_ratio < BG_ENV.DARK_RATIO_EVEN_STUDIO:
        environment = "studio"
        hints.append("even_background")

    return {
        "ok": True,
        "environment": environment,
        "hints": hints,
        "texture_std": round(texture_std, 1),
        "edge_ratio": round(edge_ratio, 4),
        "mean_brightness": round(mean_bg, 1),
    }


def _subject_description(pose_info: Dict[str, Any]) -> str:
    """Build a short human-readable subject description from pose detection results."""
    if not isinstance(pose_info, dict) or not pose_info.get("ok"):
        return "unknown"
    pose = pose_info.get("pose", "unknown")
    angle = pose_info.get("angle", "unknown")
    framing = pose_info.get("framing", "unknown")

    desc_parts = []
    # Framing / pose
    label = {
        "headshot": "Headshot portrait",
        "upper_body": "Upper-body portrait",
        "standing": "Standing portrait",
        "sitting": "Seated portrait",
    }.get(pose)
    if label:
        desc_parts.append(label)
    elif framing == "headshot":
        desc_parts.append("Headshot portrait")
    elif framing == "half_body":
        desc_parts.append("Half-body portrait")
    else:
        desc_parts.append("Portrait")

    # Angle
    if angle == "front-ish":
        desc_parts.append("facing camera")
    elif angle == "profile-ish":
        desc_parts.append("three-quarter or profile angle")

    return ", ".join(desc_parts)


def _detect_catchlights(img_bgr: np.ndarray, face_box: Optional[Tuple[int, int, int, int]]) -> Dict[str, Any]:
    """Detect catchlights (bright reflections) in the eyes using FaceMesh iris landmarks."""
    if mp is None or cv2 is None:
        return {"ok": False, "reason": "dependencies_missing"}

    import math

    model_path = _MODEL_DIR / "face_landmarker.task"
    if not model_path.exists():
        return {"ok": False, "reason": "face_landmarker model not found"}

    h, w = img_bgr.shape[:2]
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    # ── Face crop strategy ───────────────────────────────────────────────
    # When a face_box is available from the prior face_detector.tflite run,
    # crop to the face region before running FaceLandmarker.  Face mesh
    # models perform better when the face fills more of the input — cropping
    # removes distracting backgrounds and strong lighting gradients that can
    # prevent the model from finding landmarks on the full image.
    # If the crop-based run also fails, fall back to the full image, then to
    # a face_box geometric estimate (last resort).
    _lm_crop_x0, _lm_crop_y0 = 0, 0
    _lm_cw, _lm_ch = w, h

    if face_box is not None:
        _pad = 0.25                          # 25% padding (was 20% — more context helps dark skin)
        _fb_x0, _fb_y0, _fb_x1, _fb_y1 = face_box
        _fb_w = _fb_x1 - _fb_x0
        _fb_h = _fb_y1 - _fb_y0
        _lm_crop_x0 = max(0, _fb_x0 - int(_fb_w * _pad))
        _lm_crop_y0 = max(0, _fb_y0 - int(_fb_h * _pad))
        _lm_crop_x1 = min(w, _fb_x1 + int(_fb_w * _pad))
        _lm_crop_y1 = min(h, _fb_y1 + int(_fb_h * _pad))
        _img_for_lm = img_rgb[_lm_crop_y0:_lm_crop_y1, _lm_crop_x0:_lm_crop_x1]
        _lm_cw = _lm_crop_x1 - _lm_crop_x0
        _lm_ch = _lm_crop_y1 - _lm_crop_y0
        # CLAHE contrast boost for dark-skin faces: MediaPipe FaceLandmarker
        # struggles with low-contrast crops (dark skin + dark background).
        # CLAHE lifts local contrast in shadows without blowing highlights,
        # giving the landmark model more gradient signal to work with.
        # Only applied when the crop is dark (mean luminance < 80).
        _lm_gray = cv2.cvtColor(_img_for_lm, cv2.COLOR_RGB2GRAY)
        if _lm_gray.mean() < 80:
            _clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            _lm_lab = cv2.cvtColor(_img_for_lm, cv2.COLOR_RGB2LAB)
            _lm_lab[:, :, 0] = _clahe.apply(_lm_lab[:, :, 0])
            _img_for_lm = cv2.cvtColor(_lm_lab, cv2.COLOR_LAB2RGB)
    else:
        _img_for_lm = img_rgb

    opts = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
            delegate=_mp_delegate(),
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_faces=1,
        # Lower threshold so strong frontal lighting (e.g. Hurley triangle)
        # doesn't wash out face gradients below the default 0.5 cutoff.
        min_face_detection_confidence=0.3,
    )

    def _run_landmarker(mp_img) -> Any:
        lmk = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
        try:
            return lmk.detect(mp_img)
        finally:
            lmk.close()

    res = _run_landmarker(_make_mp_image(_img_for_lm))

    # If the face-crop run failed and we used a crop, try the full image
    if not res.face_landmarks and face_box is not None:
        _vp_logger.info(
            "[catchlights] FaceLandmarker failed on face crop — retrying full image"
        )
        res = _run_landmarker(_make_mp_image(img_rgb))
        _lm_crop_x0, _lm_crop_y0 = 0, 0
        _lm_cw, _lm_ch = w, h

    _estimated_geometry = False
    if not res.face_landmarks:
        # Both attempts failed.  If we have a face_box, use anthropometric
        # proportions to estimate iris centers so analyze_eye() can still run.
        if face_box is None:
            return {"ok": False, "reason": "no_face_mesh_detected"}
        fb_x0, fb_y0, fb_x1, fb_y1 = face_box
        fb_w = max(fb_x1 - fb_x0, 1)
        fb_h = max(fb_y1 - fb_y0, 1)
        _est_r        = max(fb_w * 0.075, 8.0)
        _est_eye_y    = float(fb_y0 + fb_h * 0.40)
        left_center   = (float(fb_x0 + fb_w * 0.30), _est_eye_y)
        right_center  = (float(fb_x0 + fb_w * 0.70), _est_eye_y)
        left_r        = _est_r
        right_r       = _est_r
        _left_open    = True
        _right_open   = True
        _face_yaw     = 0.0
        _estimated_geometry = True
        _vp_logger.info(
            "[catchlights] FaceLandmarker found no landmarks (both attempts) — "
            "falling back to face_box iris estimation (fb=%s)", face_box
        )
    else:
        lm = res.face_landmarks[0]

        def px(idx: int) -> Tuple[float, float]:
            # Remap from crop-relative normalized coords to full-image pixels.
            return (lm[idx].x * _lm_cw + _lm_crop_x0,
                    lm[idx].y * _lm_ch + _lm_crop_y0)

        # Iris landmarks: left 468-472 (468=center), right 473-477 (473=center)
        left_center = px(468)
        right_center = px(473)

        # Estimate iris radius from ring landmarks
        def iris_radius(center_idx: int, ring_indices: list) -> float:
            cx, cy = px(center_idx)
            dists = [math.hypot(px(i)[0] - cx, px(i)[1] - cy) for i in ring_indices]
            return max(np.mean(dists), 3.0)

        left_r = iris_radius(468, [469, 470, 471, 472])
        right_r = iris_radius(473, [474, 475, 476, 477])

        # ── Eye-open check ─────────────────────────────────────────────────
        # MediaPipe places iris landmarks even for CLOSED eyes. When eyes are
        # closed, the eyelid skin and makeup create specular highlights in the
        # iris crop region that the algorithm incorrectly registers as catchlights.
        #
        # Detect eye-open state by measuring the vertical aperture between upper
        # and lower eyelid landmarks relative to iris radius:
        #   Left eye:  upper mid=159, lower mid=145
        #   Right eye: upper mid=386, lower mid=374
        # If aperture < EYE_OPEN_RATIO × iris_radius, skip that eye.
        #
        # Threshold: 0.35 × iris_radius. Open iris aperture is typically
        # 0.8–1.2 × iris_radius; squinting is 0.4–0.6; closed is <0.3.
        _EYE_OPEN_RATIO = 0.35

        def _eye_is_open(upper_idx: int, lower_idx: int, iris_r: float) -> bool:
            """Return True if the eye aperture suggests the eye is open."""
            _, uy = px(upper_idx)
            _, ly = px(lower_idx)
            aperture = abs(ly - uy)
            return aperture >= _EYE_OPEN_RATIO * iris_r

        _left_open = _eye_is_open(159, 145, left_r)
        _right_open = _eye_is_open(386, 374, right_r)

    def clock_position(dx: float, dy: float) -> str:
        angle_rad = math.atan2(-dy, dx)  # negate dy (image y-axis inverted)
        angle_deg = math.degrees(angle_rad)
        raw_clock_30 = ((90 - angle_deg) % 360) / 30
        clock = round(raw_clock_30) % 12
        if clock == 0:
            clock = 12
        _vp_logger.debug("[catchlight-pos] dx=%.2f dy=%.2f angle=%.1f raw_30=%.2f → %d o'clock",
                         dx, dy, angle_deg, raw_clock_30, clock)
        return f"{clock} o'clock"

    # Detect B&W-like images: low saturation across the frame.
    # B&W dramatic images compress tonal range, so catchlight thresholds
    # need to be relaxed (V>200 is too aggressive for B&W contrast).
    _hsv_full = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    _mean_sat = float(np.mean(_hsv_full[:, :, 1]))
    _is_bw_like = _mean_sat < CATCHLIGHT.BW_SATURATION_CUTOFF  # very low saturation → effectively B&W

    def analyze_eye(center: Tuple[float, float], radius: float, eye_label: str) -> list:
        cx, cy = center
        crop_r = int(radius * CATCHLIGHT.IRIS_CROP_RADIUS_MULT)
        x0, y0 = int(cx - crop_r), int(cy - crop_r)
        x1, y1 = int(cx + crop_r), int(cy + crop_r)
        x0, y0, x1, y1 = _safe_box(x0, y0, x1, y1, w, h)

        crop = img_bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return []

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        v_chan = hsv[:, :, 2]
        s_chan = hsv[:, :, 1]

        # Bright, low-saturation spots = catchlights.
        # Adaptive threshold: use the crop's own brightness histogram so
        # extreme low-key images (where catchlights peak at V=130–150)
        # aren't missed by a fixed global cutoff.  The threshold is the
        # higher of:
        #   a) The static per-mode floor (V_THRESHOLD_BW or _COLOR)
        #   b) 70% of the crop's 99th-percentile V value
        # This means "the brightest ~1% of the iris crop is always a
        # candidate" while still rejecting noise in bright/normal images.
        _v_floor = CATCHLIGHT.V_THRESHOLD_BW if _is_bw_like else CATCHLIGHT.V_THRESHOLD_COLOR
        _v_p99 = float(np.percentile(v_chan, 99)) if v_chan.size > 0 else 255
        _v_mean = float(np.mean(v_chan)) if v_chan.size > 0 else 128
        # Adaptive threshold: three regimes based on iris-crop brightness.
        #
        # 1. Bright peak (p99 > 200): the iris area has bright skin AND a
        #    catchlight.  Use 92% of p99 to isolate just the catchlight
        #    peak, rejecting the surrounding V~170-200 skin that would
        #    otherwise merge into one giant contour.
        #
        # 2. Dark crop (v_mean < 80): extreme low-key — catchlights are
        #    faint.  Lower to 70% of p99 so V~130-150 specs aren't missed.
        #
        # 3. Normal: use the static per-mode floor.
        if _v_p99 > 200:
            v_threshold = max(_v_floor, _v_p99 * 0.92)
        elif _v_mean < 80:
            v_threshold = max(80, _v_p99 * 0.70)
        else:
            v_threshold = _v_floor
        # Adaptive saturation cap: in dark eye crops (low-key / dramatic),
        # catchlights pick up skin tone and ambient color → S > 80.
        s_max = CATCHLIGHT.S_MAX if _v_mean >= 100 else min(180, CATCHLIGHT.S_MAX + int((100 - _v_mean) * 1.2))
        mask = ((v_chan > v_threshold) & (s_chan < s_max)).astype(np.uint8) * 255
        _vp_logger.debug("[catchlight] eye=%s v_mean=%.0f v_p99=%.0f v_thresh=%.0f s_max=%d iris_r=%.1f",
                         eye_label, _v_mean, _v_p99, v_threshold, s_max, radius)

        # Clean noise — skip morph open when iris is small (< 25px radius)
        # because catchlights are only 2-3px across and the erosion step
        # destroys them. Downstream filters handle noise rejection.
        if radius >= 25:
            if _is_bw_like:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CATCHLIGHT.MORPH_KERNEL_BW, CATCHLIGHT.MORPH_KERNEL_BW))
            else:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CATCHLIGHT.MORPH_KERNEL_COLOR, CATCHLIGHT.MORPH_KERNEL_COLOR))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        elif _v_mean > 150:
            # Small irises in bright images: the bright background reflects
            # into the iris, creating large merged contours that swallow
            # individual catchlights.  Light erosion breaks these apart so
            # distinct catchlight peaks can be found as separate contours.
            _ero_k = max(2, int(radius * 0.15))
            _ero_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_ero_k, _ero_k))
            mask = cv2.erode(mask, _ero_kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        _vp_logger.debug("[catchlight] eye=%s contours=%d morph_skipped=%s",
                         eye_label, len(contours), radius < 25)

        crop_area = crop.shape[0] * crop.shape[1]
        results = []
        # Lower minimum area for B&W — hard sources (gobo/fresnel) create
        # tiny point catchlights that are only 3-4 pixels
        min_area = CATCHLIGHT.MIN_AREA_BW if _is_bw_like else CATCHLIGHT.MIN_AREA_COLOR
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > CATCHLIGHT.MAX_AREA_RATIO * crop_area:
                continue

            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            ccx = M["m10"] / M["m00"]
            ccy = M["m01"] / M["m00"]

            # Position relative to iris center (in crop coords)
            iris_cx_local = cx - x0
            iris_cy_local = cy - y0
            dx = ccx - iris_cx_local
            dy = ccy - iris_cy_local

            # ── Iris proximity filter ─────────────────────────────────────
            # Reject contours whose centroid is too far from the iris center.
            # Genuine catchlights appear on the iris surface (≤ 1.0× radius);
            # lash-line shimmer from mascara/makeup sits at the lash edge
            # (~1.3–2.0× radius).  1.25× is the cut-off.
            # This eliminates false catchlights from dramatic makeup (heavy
            # mascara, metallic eye shadow, specular lashes) in B&W images
            # without touching real light-source reflections.
            _dist = math.hypot(dx, dy)
            _prox_base = (CATCHLIGHT.IRIS_PROXIMITY_MAX_MULT_BW if _is_bw_like
                          else CATCHLIGHT.IRIS_PROXIMITY_MAX_MULT)
            # Relax proximity for small irises (< 30px) — MediaPipe iris
            # center detection is less precise at low resolution, so genuine
            # catchlights can appear at 1.5-1.8× radius.
            _prox_limit = _prox_base + (0.4 if radius < 30 else 0)
            _vp_logger.debug("[catchlight] eye=%s cnt area=%.0f prox=%.2f (limit=%.2f)",
                             eye_label, area, _dist / radius if radius > 0 else 999, _prox_limit)
            if _dist > _prox_limit * radius:
                continue

            # ── Size ratio filter ─────────────────────────────────────────
            # Reject blobs whose enclosing circle approaches the iris size —
            # these are skin speculars, cornea reflections, or hair highlights,
            # not modifier catchlights.
            (_, enc_r_pre) = cv2.minEnclosingCircle(cnt)
            _size_ratio_pre = enc_r_pre / radius if radius > 0 else 999
            _size_cap = (CATCHLIGHT.SIZE_RATIO_MAX_BW if _is_bw_like
                         else CATCHLIGHT.SIZE_RATIO_MAX_COLOR)
            # Relax size cap for small irises — at low resolution, catchlight
            # blobs spread beyond their true boundaries via interpolation.
            if radius < 30:
                _size_cap += 0.25
            _vp_logger.debug("[catchlight] eye=%s cnt sr=%.2f (cap=%.2f)",
                             eye_label, _size_ratio_pre, _size_cap)
            if _size_ratio_pre > _size_cap:
                continue

            # Shape classification: ring, round, octagonal, strip, square, rectangular
            enc_r = enc_r_pre  # reuse from size ratio filter above
            enc_area = math.pi * enc_r * enc_r
            circularity = area / enc_area if enc_area > 0 else 0

            # Bounding rect for aspect ratio
            _brx, _bry, _brw, _brh = cv2.boundingRect(cnt)
            _aspect = max(_brw, _brh) / max(min(_brw, _brh), 1)

            # Contour vertex count (approxPolyDP)
            _epsilon = 0.03 * cv2.arcLength(cnt, True)
            _approx = cv2.approxPolyDP(cnt, _epsilon, True)
            _vertices = len(_approx)

            # Hollowness check for ring vs filled round:
            # A ring light catchlight is a donut — bright ring with dark center.
            cnt_mask_shape = np.zeros(crop.shape[:2], dtype=np.uint8)
            cv2.drawContours(cnt_mask_shape, [cnt], 0, 255, -1)
            _center_val = 0.0
            _edge_val = 0.0
            if enc_r > 3:
                # Sample center region (inner 40% radius)
                _cmask_center = np.zeros(crop.shape[:2], dtype=np.uint8)
                cv2.circle(_cmask_center, (int(ccx), int(ccy)), max(1, int(enc_r * 0.4)), 255, -1)
                _center_pixels = v_chan[(_cmask_center > 0) & (cnt_mask_shape > 0)]
                # Sample edge ring (outer 30%)
                _cmask_outer = np.zeros(crop.shape[:2], dtype=np.uint8)
                cv2.circle(_cmask_outer, (int(ccx), int(ccy)), max(1, int(enc_r * 0.85)), 255, -1)
                _edge_pixels = v_chan[(cnt_mask_shape > 0) & (_cmask_outer == 0)]
                if len(_center_pixels) > 0:
                    _center_val = float(np.mean(_center_pixels))
                if len(_edge_pixels) > 0:
                    _edge_val = float(np.mean(_edge_pixels))

            _is_hollow = (_edge_val > 0 and _center_val > 0 and
                          _center_val < _edge_val * 0.65 and enc_r > 4)

            # Classify shape
            # Aspect thresholds:
            #   strip  >= 1.8  (Hurley-style vertical strip boxes are ~1.8–3.0+)
            #   square <  1.3  (near-equal sides)
            #   rectangular: everything between 1.3–1.8
            if circularity > CATCHLIGHT.CIRCULARITY_ROUND and _is_hollow:
                shape = "ring"          # donut — ring light
            elif circularity > CATCHLIGHT.CIRCULARITY_ROUND:
                if _vertices >= 7 and _vertices <= 9 and circularity < 0.85:
                    shape = "octagonal"  # octabox — near-round with 8 vertices
                else:
                    shape = "round"      # beauty dish, umbrella, round softbox
            elif _aspect >= 1.8:
                shape = "strip"          # strip box — elongated (Hurley, strip softbox)
            elif _aspect < 1.3 and circularity < CATCHLIGHT.CIRCULARITY_ROUND:
                shape = "square"         # square softbox
            else:
                shape = "rectangular"    # standard softbox (1.3–1.8 aspect)

            # Intensity
            cnt_mask = cnt_mask_shape  # reuse the mask we already drew
            intensity = float(np.mean(v_chan[cnt_mask > 0]) / 255.0)

            _pos_str = clock_position(dx, dy)
            _sr = round(enc_r / radius, 3) if radius > 0 else None
            _vp_logger.debug("[catchlight-detail] eye=%s pos=%s int=%.3f shape=%s sr=%.3f area=%.0f",
                             eye_label, _pos_str, intensity, shape, _sr or 0, area)

            # Elevation ratio: how far above/below iris center the catchlight sits.
            # Normalized by iris radius. Negative = above eye (light is high),
            # positive = below (light is low/uplight). 0 = eye level.
            # This is a direct physical signal of light height relative to the eye.
            _elev_ratio = round(-dy / radius, 3) if radius > 0 else 0.0  # negate: up in image = high light

            results.append({
                "eye": eye_label,
                "position": _pos_str,
                "intensity": round(intensity, 2),
                "shape": shape,
                # size_ratio: catchlight enclosing-circle radius / iris radius (0–1+)
                # <0.1 = point/hard source, 0.1–0.3 = medium, >0.3 = large diffuse source
                "size_ratio": round(enc_r / radius, 3) if radius > 0 else None,
                # elevation_ratio: catchlight vertical position in iris.
                # >0.5 = high (above eye), ~0 = eye level, <-0.3 = low/uplight.
                # Directly encodes light height relative to the subject's eyes.
                "elevation_ratio": _elev_ratio,
                # Pixel coordinates for overlay — absolute position in full image
                "abs_cx": int(x0 + ccx),
                "abs_cy": int(y0 + ccy),
                "enc_r_px": round(enc_r, 1),
            })

        # ── Peak-finding fallback for bright eye crops ─────────────────
        # When the contour-based detector finds < 3 catchlights AND the
        # eye crop is bright (v_mean > 150), the bright background likely
        # merged individual catchlights into one large contour.  Fall back
        # to local maxima detection: find the N brightest peaks on the V
        # channel within the iris area, separated by at least 0.4× radius.
        # This catches positioned catchlights in Hurley triangle setups
        # where contour detection fails due to bg washout.
        # Compute proximity limit for peak-finding (same formula as contour filter)
        _pk_prox_base = (CATCHLIGHT.IRIS_PROXIMITY_MAX_MULT_BW if _is_bw_like
                         else CATCHLIGHT.IRIS_PROXIMITY_MAX_MULT)
        _pk_prox_limit = _pk_prox_base + (0.4 if radius < 30 else 0)
        if len(results) < 3 and _v_mean > 150 and radius > 5:
            _pk_region = v_chan.copy().astype(float)
            # Mask outside iris area
            _pk_mask = np.zeros_like(_pk_region, dtype=np.uint8)
            _iris_cx_l = int(cx - x0)
            _iris_cy_l = int(cy - y0)
            cv2.circle(_pk_mask, (_iris_cx_l, _iris_cy_l), int(radius * 1.2), 255, -1)
            _pk_region[_pk_mask == 0] = 0
            # Find local maxima using cv2.dilate (equivalent to maximum_filter)
            _pk_size = max(3, int(radius * 0.4))
            _pk_kernel = np.ones((_pk_size, _pk_size), dtype=np.uint8)
            _pk_max = cv2.dilate(_pk_region.astype(np.uint8), _pk_kernel)
            _pk_thresh = max(v_threshold, _v_p99 * 0.85)
            _pk_locs = np.argwhere(
                (_pk_region == _pk_max) &
                (_pk_region > _pk_thresh) &
                (_pk_mask > 0)
            )
            # Deduplicate peaks within 0.4× radius
            _pk_deduped = []
            _pk_min_sep = radius * 0.4
            for py, px in _pk_locs:
                too_close = any(
                    math.hypot(px - ex, py - ey) < _pk_min_sep
                    for ex, ey in _pk_deduped
                )
                if not too_close:
                    _pk_deduped.append((px, py))
            # Add peaks not already covered by contour results
            for pkx, pky in _pk_deduped:
                _pk_dx = pkx - _iris_cx_l
                _pk_dy = pky - _iris_cy_l
                _pk_dist = math.hypot(_pk_dx, _pk_dy)
                if _pk_dist > _pk_prox_limit * radius:
                    continue
                # Check if this peak is near an existing contour result
                _pk_dup = any(
                    math.hypot((r["abs_cx"] - x0) - pkx, (r["abs_cy"] - y0) - pky) < radius * 0.3
                    for r in results
                )
                if _pk_dup:
                    continue
                _pk_pos = clock_position(float(_pk_dx), float(_pk_dy))
                _pk_int = float(_pk_region[int(pky), int(pkx)] / 255.0)
                _pk_elev = round(-_pk_dy / radius, 3) if radius > 0 else 0.0
                results.append({
                    "eye": eye_label,
                    "position": _pk_pos,
                    "intensity": round(_pk_int, 2),
                    "shape": "point",  # peak-detected, no contour shape info
                    "size_ratio": 0.05,  # minimal — point source
                    "elevation_ratio": _pk_elev,
                    "abs_cx": int(x0 + pkx),
                    "abs_cy": int(y0 + pky),
                    "enc_r_px": 2.0,
                })
                _vp_logger.debug("[catchlight-peak] eye=%s pos=%s int=%.3f at (%d,%d)",
                                 eye_label, _pk_pos, _pk_int, int(pkx), int(pky))

        return results

    # Only analyze an eye if it appears to be open.
    # Closed eyes produce eyelid specular highlights that are misread as
    # catchlights. When an eye is closed we skip it entirely so it doesn't
    # pollute the light-count inference.
    left_catchlights = analyze_eye(left_center, left_r, "left") if _left_open else []
    right_catchlights = analyze_eye(right_center, right_r, "right") if _right_open else []
    all_catchlights = left_catchlights + right_catchlights

    # ── Filter lower-hemisphere catchlights ───────────────────────────
    # Positions 4–8 o'clock are below the iris horizontal axis.  Most are
    # costume reflections (medals, jewellery, eyeglass rims), but 5–7 o'clock
    # catchlights can be legitimate fill lights in clamshell / beauty setups.
    # Strategy:
    #   • Keep lower catchlights at 5-7 o'clock if they have reasonable
    #     intensity relative to the upper key (fill detection).
    #   • Drop lower catchlights at 4 or 8 o'clock (lateral = costume).
    #   • When ONLY lower-hemisphere catchlights exist with no upper,
    #     discard — lone lower catchlight is almost certainly a reflection.
    _LOWER_HEMISPHERE_CLOCKS = {4, 5, 6, 7, 8}
    _FILL_CLOCKS = {5, 6, 7}  # legitimate fill positions (below center)

    def _is_lower(c: dict) -> bool:
        try:
            return int(c["position"].split()[0]) in _LOWER_HEMISPHERE_CLOCKS
        except (ValueError, IndexError):
            return False

    def _is_fill_candidate(c: dict) -> bool:
        """Lower catchlight at 5-7 o'clock with reasonable intensity = possible fill."""
        try:
            clk = int(c["position"].split()[0])
            return clk in _FILL_CLOCKS
        except (ValueError, IndexError):
            return False

    _upper_cls = [c for c in all_catchlights if not _is_lower(c)]
    _lower_cls  = [c for c in all_catchlights if     _is_lower(c)]

    if _upper_cls and _lower_cls:
        # Keep lower catchlights that look like fill lights (5-7 o'clock).
        # Drop everything at 4 and 8 o'clock — these are costume/eyelash artifacts.
        _kept_lower = []
        for c in _lower_cls:
            # 5-7 o'clock fill zone: always keep when upper catchlights are present.
            # A horizontal tube/strip below the face produces a legitimate lower
            # catchlight (Hurley triangle fill) — the fill is intentionally dimmer
            # than the key lights, so an intensity gate would filter it out.
            if _is_fill_candidate(c):
                c["fill_candidate"] = True
                _kept_lower.append(c)
        all_catchlights = _upper_cls + _kept_lower
        _kept_lower_set = {id(c) for c in _kept_lower}
        left_catchlights = [c for c in left_catchlights if not _is_lower(c) or id(c) in _kept_lower_set]
        right_catchlights = [c for c in right_catchlights if not _is_lower(c) or id(c) in _kept_lower_set]
    elif _lower_cls and not _upper_cls:
        # Only lower-hemisphere catchlights.  Previously discarded entirely
        # as "costume reflections", but at small iris sizes (<30px) the clock
        # position can be off by 2-3 hours, so a real upper catchlight may
        # register at 4 o'clock.  Keep them — the proximity + size_ratio
        # filters already reject genuine costume artifacts.
        _small_iris = min(left_r, right_r) < 30
        if _small_iris:
            pass  # keep all — position unreliable at this resolution
        else:
            all_catchlights   = []
            left_catchlights  = []
            right_catchlights = []

    # ── Face yaw + geometry ───────────────────────────────────────────
    if not _estimated_geometry:
        # Full landmark path — precise yaw from nose/edge geometry.
        _nose_tip = px(1)          # nose tip
        _left_edge = px(234)       # left face contour
        _right_edge = px(454)      # right face contour
        _nose_to_left = math.hypot(_nose_tip[0] - _left_edge[0], _nose_tip[1] - _left_edge[1])
        _nose_to_right = math.hypot(_nose_tip[0] - _right_edge[0], _nose_tip[1] - _right_edge[1])
        _face_width = math.hypot(_left_edge[0] - _right_edge[0], _left_edge[1] - _right_edge[1])
        if _face_width > 0:
            _face_yaw = round((_nose_to_left - _nose_to_right) / _face_width, 3)
        else:
            _face_yaw = 0.0

        _face_geometry = {
            "forehead_top": px(10),
            "nose_bridge": px(6),
            "nose_tip": px(1),
            "chin": px(152),
            "left_eye_center": left_center,
            "right_eye_center": right_center,
            "left_face_edge": px(234),
            "right_face_edge": px(454),
            "face_yaw": _face_yaw,
            "image_size": (w, h),
        }
    else:
        # Estimated from face_box — yaw unknown, geometry approximate.
        _face_geometry = {
            "left_eye_center": left_center,
            "right_eye_center": right_center,
            "face_yaw": 0.0,
            "image_size": (w, h),
            "estimated_from_face_box": True,
        }

    if not all_catchlights:
        return {"ok": True, "count": 0, "catchlights": [], "face_yaw": _face_yaw,
                "face_geometry": _face_geometry, "inferred": {
            "keyLightPosition": "not detected",
            "likelyModifier": "unknown",
            "lightCount": 0,
        }}

    # Infer key light position from average clock position
    clock_numbers = []
    for c in all_catchlights:
        num = int(c["position"].split()[0])
        clock_numbers.append(num)
    avg_clock = round(np.mean(clock_numbers))
    if avg_clock == 0:
        avg_clock = 12

    position_map = {
        12: "directly above",
        11: "above, slightly left",
        10: "above left",
        9: "hard left",
        1: "above, slightly right",
        2: "above right",
        3: "hard right",
        8: "left, slightly below",
        4: "right, slightly below",
        7: "below left",
        5: "below right",
        6: "directly below",
    }
    key_pos = position_map.get(avg_clock, f"{avg_clock} o'clock")

    # Modifier from dominant shape
    shapes = [c["shape"] for c in all_catchlights]
    round_count = shapes.count("round")
    rect_count = shapes.count("rectangular")
    if round_count > rect_count:
        likely_mod = "beauty dish or round source"
    elif rect_count > round_count:
        likely_mod = "softbox or rectangular modifier"
    else:
        likely_mod = "mixed modifiers"

    # Light count from max catchlights per eye
    light_count = max(len(left_catchlights), len(right_catchlights))

    return {
        "ok": True,
        "count": light_count,
        "catchlights": all_catchlights,
        "face_yaw": _face_yaw,
        "face_geometry": _face_geometry,
        "inferred": {
            "keyLightPosition": key_pos,
            "likelyModifier": likely_mod,
            "lightCount": light_count,
        },
    }


def _image_detail(img_bgr) -> float:
    """Variance of the Laplacian — how much structure the image actually has.

    Size-normalised: without it a large photograph scores higher than a small
    one purely for being large, which is not what the number is meant to mean.
    Returns 0.0 rather than raising on anything unexpected; a metric that can
    fail the whole pipeline is worse than one that abstains.
    """
    try:
        g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
        if max(g.shape) > 1024:
            _s = 1024.0 / max(g.shape)
            g = cv2.resize(g, (int(g.shape[1] * _s), int(g.shape[0] * _s)))
        return float(cv2.Laplacian(g, cv2.CV_64F).var())
    except Exception:
        return 0.0


def analyze_image_regions(image_path: str, *, return_masks: bool = False) -> Dict[str, Any]:
    if cv2 is None or mp is None:
        return {"ok": False, "error": "opencv-python and mediapipe are required"}

    import time as _time
    _t_pipe_start = _time.perf_counter()

    img = cv2.imread(image_path)
    if img is None:
        return {"ok": False, "error": f"Could not read image: {image_path}"}

    h, w = img.shape[:2]

    # ── Resize images to optimal range for MediaPipe ───────────────────
    # Too large (>_MP_MAX_DIM): wastes CPU, no benefit. Downscale, INTER_AREA.
    # Too small (<_MP_MIN_DIM): eye regions too tiny for catchlight detection,
    #   face landmarks imprecise. Upscale, INTER_CUBIC.
    #
    # BOTH constants are 2048 (NGW_MP_MAX_DIM / NGW_MP_MIN_DIM), so there is no
    # leave-alone band: every image that is not exactly 2048 on its long edge
    # gets resized. This comment said 1920 and 1024, describing a band that has
    # not existed for some time — corrected 2026-09-02. It matters because that
    # phantom band is what makes the coordinate-space bug in b6 look like an
    # edge case: 33 of the 34 corpus images are upscaled, not a handful.
    # The names are used here rather than repeated numbers so the comment
    # cannot drift from the constants again.
    _scale = 1.0
    # b8: measure structure on the ORIGINAL image. Computing it after the
    # MediaPipe upscale collapses it ~70x — INTER_CUBIC interpolates detail
    # away, so clamshell_clean reads 242 before and 3.55 after. The first
    # version of this floor did exactly that and declined two real reads.
    _detail_orig = _image_detail(img)
    if _MP_MAX_DIM > 0 and max(h, w) > _MP_MAX_DIM:
        _scale = _MP_MAX_DIM / max(h, w)
        _new_w, _new_h = int(w * _scale), int(h * _scale)
        _vp_logger.info("[vision_pipeline] Downscaling %dx%d → %dx%d for MediaPipe", w, h, _new_w, _new_h)
        img = cv2.resize(img, (_new_w, _new_h), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    elif _MP_MIN_DIM > 0 and max(h, w) < _MP_MIN_DIM:
        _scale = _MP_MIN_DIM / max(h, w)
        _new_w, _new_h = int(w * _scale), int(h * _scale)
        _vp_logger.info("[vision_pipeline] Upscaling %dx%d → %dx%d for catchlight detection", int(_new_w / _scale), int(_new_h / _scale), _new_w, _new_h)
        img = cv2.resize(img, (_new_w, _new_h), interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]

    # Person segmentation
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_image = _make_mp_image(img_rgb)
    _delegate = _mp_delegate()

    seg_model = _MODEL_DIR / "selfie_segmenter.tflite"
    if not seg_model.exists():
        return {"ok": False, "error": "selfie_segmenter model not found"}

    # ── Face detection — run BEFORE segmenter to avoid MediaPipe model
    # state interference that can cause detection failures on dark skin.
    face_box = None
    face_detection_score: float = 0.0
    fd_model = _MODEL_DIR / "face_detector.tflite"
    if fd_model.exists():
        fd_opts = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(fd_model),
                delegate=_mp_delegate(),
            ),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            min_detection_confidence=SEGMENTATION.FACE_DETECTOR_CONFIDENCE,
        )
        detector = mp.tasks.vision.FaceDetector.create_from_options(fd_opts)
        try:
            fd_res = detector.detect(mp_image)
        finally:
            detector.close()
        if fd_res.detections:
            det = fd_res.detections[0]
            face_detection_score = det.categories[0].score if det.categories else 0.0
            bb = det.bounding_box
            x0 = bb.origin_x
            y0 = bb.origin_y
            x1 = bb.origin_x + bb.width
            y1 = bb.origin_y + bb.height
            x0, y0, x1, y1 = _safe_box(x0, y0, x1, y1, w, h)
            face_box = (x0, y0, x1, y1)

    seg_opts = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(seg_model),
            delegate=_mp_delegate(),
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        output_confidence_masks=True,
    )
    segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(seg_opts)
    try:
        seg_res = segmenter.segment(mp_image)
    finally:
        segmenter.close()

    if not seg_res.confidence_masks:
        return {"ok": False, "reason": "no_segmentation_mask"}

    # Selfie segmenter: last mask is person confidence (index 1 for 2-class model)
    masks = seg_res.confidence_masks
    person_conf = masks[-1].numpy_view().copy() if len(masks) > 1 else masks[0].numpy_view().copy()
    if person_conf.ndim == 3:
        person_conf = person_conf[:, :, 0]
    person_mask = (person_conf > SEGMENTATION.PERSON_MASK_CONFIDENCE)
    # clean mask a bit
    person_u8 = (person_mask.astype(np.uint8) * 255)
    person_u8 = cv2.medianBlur(person_u8, SEGMENTATION.PERSON_MASK_BLUR_KERNEL)
    person_mask = (person_u8 > 0)

    # Face detection moved BEFORE segmenter — see above.

    # Skin mask: use YCbCr mask, optionally constrained to face box
    skin_mask = _ycbcr_skin_mask(img)
    if face_box:
        x0, y0, x1, y1 = face_box
        face_only = np.zeros((h, w), dtype=bool)
        face_only[y0:y1, x0:x1] = True
        skin_mask = skin_mask & face_only

    skin_mask = skin_mask & person_mask

    # P2c: B&W fallback — YCbCr skin detection fails on B&W images because
    # the Cb/Cr channels carry no chroma information.  When the image is
    # grayscale-like and skin_mask is empty but person_mask has content,
    # treat the person mask as a rough skin proxy (better than 0% skin).
    _is_gs_check = bool(
        np.std(
            img.astype(float).mean(axis=2)
            - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(float)
        ) < SKIN.COLOR_VARIANCE_BW
    )
    _skin_ratio_raw = float(np.mean(skin_mask)) if skin_mask.any() else 0.0
    _person_ratio_raw = float(np.mean(person_mask)) if person_mask.any() else 0.0
    if _skin_ratio_raw < SKIN.RATIO_BW_FALLBACK and _person_ratio_raw > SKIN.PERSON_RATIO_BW_FALLBACK and _is_gs_check:
        # B&W luma proxy: select mid-tone pixels within the face box.
        # YCbCr chroma detection is blind on B&W, but luminance IS available.
        # Mid-luma face pixels (BW_LUMA_MIN–BW_LUMA_MAX) approximate skin —
        # they exclude hair/clothing darks and blown highlights.
        # Falls back to full person_mask when no face box is available.
        _bw_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if face_box:
            _fb_x0, _fb_y0, _fb_x1, _fb_y1 = face_box
            _face_only = np.zeros((h, w), dtype=bool)
            _face_only[_fb_y0:_fb_y1, _fb_x0:_fb_x1] = True
            _luma_range = (_bw_gray >= SKIN.BW_LUMA_MIN) & (_bw_gray <= SKIN.BW_LUMA_MAX)
            _luma_proxy = _face_only & _luma_range & person_mask
            skin_mask = _luma_proxy if _luma_proxy.any() else (person_mask & _face_only)
        else:
            skin_mask = person_mask.copy()

    # Clothing mask (rough): person minus skin
    clothing_mask = person_mask & (~skin_mask)

    # Background mask
    background_mask = ~person_mask

    def pixels_from_mask(mask: np.ndarray) -> np.ndarray:
        pts = img[mask]
        if pts.size == 0:
            return np.empty((0, 3), dtype=np.uint8)
        # convert BGR -> RGB for palette
        pts_rgb = pts[:, ::-1]
        return pts_rgb

    skin_px = pixels_from_mask(skin_mask)
    cloth_px = pixels_from_mask(clothing_mask)
    bg_px = pixels_from_mask(background_mask)

    # Palettes
    skin_pal = _kmeans_palette(skin_px, k=PALETTE.SKIN_CLUSTERS) if skin_px.shape[0] >= SKIN.MIN_SKIN_PIXELS_PALETTE else []
    cloth_pal = _kmeans_palette(cloth_px, k=PALETTE.CLOTHING_CLUSTERS) if cloth_px.shape[0] >= SKIN.MIN_CLOTHING_PIXELS_PALETTE else []
    bg_pal = _kmeans_palette(bg_px, k=PALETTE.BG_CLUSTERS) if bg_px.shape[0] >= SKIN.MIN_BG_PIXELS_PALETTE else []

    # Pose — try landmarks first, fall back to mask shape
    pose_info = _pose_guess(img)
    if not pose_info.get("ok"):
        pose_info = _pose_from_mask(person_mask, img)

    # Background environment detection
    is_gs = bool(np.std(img.astype(float).mean(axis=2) - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(float)) < SKIN.COLOR_VARIANCE_BW)
    bg_environment = _detect_background_environment(img, background_mask, is_grayscale=is_gs)

    # Catchlights — detection runs on the (possibly upscaled) image.
    # Normalize all pixel coordinates back to original image space so
    # they match image_dimensions in the API response.
    catchlight_info = _detect_catchlights(img, face_box)
    if _scale != 1.0 and catchlight_info.get("ok"):
        for _cl in catchlight_info.get("catchlights", []):
            _cl["abs_cx"] = round(_cl["abs_cx"] / _scale)
            _cl["abs_cy"] = round(_cl["abs_cy"] / _scale)
            if "enc_r_px" in _cl:
                _cl["enc_r_px"] = round(_cl["enc_r_px"] / _scale, 1)
        _fg = catchlight_info.get("face_geometry", {})
        for _fk in ("left_eye_center", "right_eye_center", "nose_tip",
                     "chin", "forehead_top", "nose_bridge",
                     "left_face_edge", "right_face_edge"):
            if _fk in _fg and _fg[_fk] is not None:
                _fg[_fk] = (round(_fg[_fk][0] / _scale, 1), round(_fg[_fk][1] / _scale, 1))
        if "image_size" in _fg:
            _fg["image_size"] = (round(_fg["image_size"][0] / _scale), round(_fg["image_size"][1] / _scale))

    # Skin tone guess from skin pixels luma (Y from YCrCb)
    skin_tone = {"ok": False, "reason": "no_skin_pixels"}
    if skin_px.shape[0] >= SKIN.MIN_PIXELS_TONE:
        ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
        Y = ycrcb[:, :, 0]
        ys = Y[skin_mask]
        mean_y = float(np.mean(ys)) if ys.size else 0.0
        if mean_y <= SKIN.DEEP_LUMA:
            tone = "deep"
        elif mean_y <= SKIN.MEDIUM_LUMA:
            tone = "medium"
        else:
            tone = "light"
        ratio = float(skin_px.shape[0] / float(h * w))
        conf = "high" if ratio >= SKIN.CONFIDENCE_HIGH_RATIO else ("medium" if ratio >= SKIN.CONFIDENCE_MEDIUM_RATIO else "low")

        # B&W guard: In grayscale images the luma is driven by exposure and
        # grading, not by actual skin pigmentation.  A fair-skinned subject
        # shot in dark low-key B&W can have mean_y=73 → misclassified as
        # "deep".  When the image is B&W, downgrade confidence to "low" and
        # add a warning so downstream consumers know the estimate is
        # unreliable.  We keep the luma-based guess (it's still useful as a
        # brightness reference) but mark it explicitly as BW-degraded.
        bw_degraded = False
        if is_gs:
            conf = "low"
            bw_degraded = True

        skin_tone = {
            "ok": True,
            "skin_tone_guess": tone,
            "mean_skin_luma_y": mean_y,
            "skin_pixel_ratio": ratio,
            "confidence": conf,
            "bw_degraded": bw_degraded,
            "limits": [
                "Exposure/WB can shift results; treat as a starting guess.",
                "Strong gels/makeup can break inference.",
            ] + (["B&W image — skin tone derived from luma only; actual pigmentation unknown."] if bw_degraded else []),
        }

    result = {
        "ok": True,
        # ── b8: is there enough image structure for a lighting read to be
        # POSSIBLE at all? Variance of the Laplacian, size-normalised so a big
        # image is not automatically "detailed". Reported here; the decline is
        # decided at the orchestrator exit alongside the b5 floor.
        #
        # Measured 2026-08-29 — real photographs 54.4 to 2885 (n=34); a plain
        # gradient 0.57, a portrait blurred past recognition 1.36, flat grey /
        # white / black 0.00. A 40x gap. Pure NOISE scores 48756 and is not
        # caught here at all — it is caught by the b5 confidence floor, so the
        # two mechanisms are complementary rather than redundant.
        "image_detail": _detail_orig,
        "region_attribution": {
            "enabled": True,
            "masks": {
                "person_ratio": float(np.mean(person_mask)),
                "skin_ratio": float(np.mean(skin_mask)),
                "clothing_ratio": float(np.mean(clothing_mask)),
                "background_ratio": float(np.mean(background_mask)),
                "_image_h": int(h),
                "_image_w": int(w),
            },
            "palettes": {
                "skin_palette": skin_pal,
                "clothing_palette": cloth_pal,
                "background_palette": bg_pal,
            },
            "face_box": list(face_box) if face_box else None,
            "face_detection_score": round(face_detection_score, 4) if face_box else None,
            "notes": [
                "Skin/clothing/background palettes come from actual masked pixels (not guesses).",
                "Clothing mask is 'person minus skin' (hair may be included).",
            ],
        },
        "pose": pose_info,
        "background_environment": bg_environment,
        "catchlights": catchlight_info,
        "skin_tone": skin_tone,
        "subject": {
            "description": _subject_description(pose_info),
            "gender": "unknown",
            "pose": pose_info.get("pose", "unknown") if isinstance(pose_info, dict) else "unknown",
            "framing": pose_info.get("framing", "unknown") if isinstance(pose_info, dict) else "unknown",
            "needs_user_confirmation": True,
            "prompt": "Confirm: gender/presentation (optional), pose type, wardrobe colors, and intended mood.",
        },
    }

    # When requested, include raw masks and image for cue extraction.
    # These are prefixed with underscore to signal internal use — they
    # should be stripped before serializing to API responses.
    if return_masks:
        result["_masks"] = {
            "person": person_mask,
            "skin": skin_mask,
            "clothing": clothing_mask,
            "background": background_mask,
        }
        result["_img_bgr"] = img

    _vp_logger.info("[vision_pipeline] analyze_image_regions: %.1fs (%dx%d)", _time.perf_counter() - _t_pipe_start, w, h)
    return result
