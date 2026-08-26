"""Extended vision analysis passes for lighting reconstruction.

Each pass extracts specific physical signals from the image using OpenCV.
These passes extend the existing vision pipeline (vision_pipeline.py and
cue_extraction.py) — they do NOT replace it.

Pipeline order:
    geometry_pass                → pose/camera geometry (existing in vision_pipeline.py)
    pose_solver_pass             → pose geometry & interference detection
    surface_class_pass           → material/surface classification
    shadow_pass                  → shadow vector, softness, edge gradient
    highlight_pass               → highlight regions, rolloff, specularity
    catchlight_pass              → enhanced catchlight detection (extends existing)
    background_pass              → background gradient analysis
    specular_surface_pass        → specular highlights on surfaces
    ── NEW SIGNAL PASSES ──
    light_direction_field_pass   → local light direction vectors
    inverse_square_solver_pass   → distance from brightness falloff
    solar_geometry_pass          → sun detection via parallel shadows
    window_geometry_pass         → window light via gradients/reflections
    bounce_geometry_pass         → environmental bounce sources
    reflection_geometry_pass     → specular reflection region mapping
    shadow_penumbra_pass         → shadow softness → source size
    occlusion_shadow_pass        → foliage/environmental patterns
    color_temperature_pass       → multi-CCT detection
    environment_light_pass       → studio/window/sun/overcast/mixed
    ── NEW SYNTHESIS PASSES ──
    modifier_shape_solver_pass   → reflection shape → modifier type
    lighting_hypothesis_engine   → candidate setup generation (replaces light_role_pass)
    physics_consistency_engine   → score hypotheses against physics
    ── EXISTING ENHANCED ──
    reconstruction_pass          → combines all signals into corrected estimates
    pattern_matcher              → match to named lighting patterns
    reference_matcher            → match to reference image library
    lighting_knowledge_library   → enriched pattern matching with physics
    ngw_validation_pass          → consistency checks (pose/surface/physics aware)

IMPORTANT: These passes extract observable signals ONLY.
The NGW rule engine determines final lighting setup, modifier, and equipment.
The pose_solver_pass does NOT determine lighting — it only explains pose
geometry, identifies self-shadow/occlusion, and corrects signal interpretation.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

from engine.constants import CATCHLIGHT

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 0. POSE SOLVER PASS
# ═══════════════════════════════════════════════════════════════════════════

# Body region mapping for occlusion detection
_BODY_REGIONS = [
    "torso_left", "torso_right", "waist_left", "waist_right",
    "neck_lower", "under_chin", "shoulder_left", "shoulder_right",
]

# MediaPipe PoseLandmarker indices (when available)
_LM_NOSE = 0
_LM_LEFT_SHOULDER = 11
_LM_RIGHT_SHOULDER = 12
_LM_LEFT_HIP = 23
_LM_RIGHT_HIP = 24
_LM_LEFT_ELBOW = 13
_LM_RIGHT_ELBOW = 14
_LM_LEFT_WRIST = 15
_LM_RIGHT_WRIST = 16
_LM_LEFT_KNEE = 25
_LM_RIGHT_KNEE = 26
_LM_LEFT_EAR = 7
_LM_RIGHT_EAR = 8


def _angle_between_points(
    p1: Tuple[float, float], p2: Tuple[float, float]
) -> float:
    """Return angle in degrees of line p1→p2 from horizontal."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.degrees(math.atan2(dy, dx))


def _midpoint(p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
    return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)


def _estimate_rotation_from_width_ratio(
    left_dist: float, right_dist: float
) -> float:
    """Estimate rotation degrees from asymmetric segment lengths.

    When a person is rotated, one side appears shorter due to foreshortening.
    Returns signed degrees: negative = turned left, positive = turned right.
    """
    total = left_dist + right_dist
    if total < 1e-6:
        return 0.0
    ratio = (right_dist - left_dist) / total
    # Map ratio [-1, 1] → degrees [-90, 90] (approximate)
    return ratio * 90.0


def _detect_arm_occlusion(
    landmarks: Dict[int, Tuple[float, float]],
    h: int, w: int,
) -> List[str]:
    """Detect which body regions arms may be occluding."""
    occluded = []

    l_shoulder = landmarks.get(_LM_LEFT_SHOULDER)
    r_shoulder = landmarks.get(_LM_RIGHT_SHOULDER)
    l_elbow = landmarks.get(_LM_LEFT_ELBOW)
    r_elbow = landmarks.get(_LM_RIGHT_ELBOW)
    l_wrist = landmarks.get(_LM_LEFT_WRIST)
    r_wrist = landmarks.get(_LM_RIGHT_WRIST)
    l_hip = landmarks.get(_LM_LEFT_HIP)
    r_hip = landmarks.get(_LM_RIGHT_HIP)

    # Torso center x-range
    if l_shoulder and r_shoulder:
        torso_left_x = min(l_shoulder[0], r_shoulder[0])
        torso_right_x = max(l_shoulder[0], r_shoulder[0])
        torso_mid_x = (torso_left_x + torso_right_x) / 2

        # Check if left arm crosses torso
        for pt in [l_elbow, l_wrist]:
            if pt and torso_left_x < pt[0] < torso_right_x:
                # Arm is in front of torso
                if pt[0] > torso_mid_x:
                    occluded.append("torso_right")
                else:
                    occluded.append("torso_left")

        # Check if right arm crosses torso
        for pt in [r_elbow, r_wrist]:
            if pt and torso_left_x < pt[0] < torso_right_x:
                if pt[0] < torso_mid_x:
                    occluded.append("torso_left")
                else:
                    occluded.append("torso_right")

        # Check if wrist is near waist/hip
        if l_hip and r_hip:
            hip_y = (l_hip[1] + r_hip[1]) / 2
            for wrist, side in [(l_wrist, "left"), (r_wrist, "right")]:
                if wrist and abs(wrist[1] - hip_y) < (h * 0.1):
                    occluded.append(f"waist_{side}")

    return list(set(occluded))


def _detect_leg_occlusion(
    landmarks: Dict[int, Tuple[float, float]],
    h: int, w: int,
) -> List[str]:
    """Detect leg crossing or occlusion."""
    occluded = []
    l_knee = landmarks.get(_LM_LEFT_KNEE)
    r_knee = landmarks.get(_LM_RIGHT_KNEE)
    l_hip = landmarks.get(_LM_LEFT_HIP)
    r_hip = landmarks.get(_LM_RIGHT_HIP)

    if l_knee and r_knee and l_hip and r_hip:
        # Check if knees have crossed (left knee right of right knee)
        if l_knee[0] > r_knee[0] + (w * 0.03):
            occluded.append("leg_crossing")

    return occluded


def _detect_self_shadow_regions(
    chin_pitch: str,
    torso_rotation: float,
    arm_occlusion: List[str],
) -> List[str]:
    """Predict regions likely to have pose-induced self-shadow."""
    regions = []

    # Chin down → under-chin shadow
    if chin_pitch in ("down", "slightly_down"):
        regions.append("under_chin")

    # Torso rotation → shadow on receding side
    if abs(torso_rotation) > 15:
        if torso_rotation > 0:
            regions.append("torso_left")  # turned right → left side recedes
        else:
            regions.append("torso_right")

    # Arm occlusion creates shadows
    for region in arm_occlusion:
        if region.startswith("torso_") or region.startswith("waist_"):
            regions.append(region)

    # Neck shadow from jaw/chin angle
    if chin_pitch in ("down", "slightly_down"):
        regions.append("neck_lower")

    return list(set(regions))


def _compute_pose_complexity(
    torso_rotation: float,
    head_rotation: float,
    shoulder_angle: float,
    hip_angle: float,
    arm_occlusion: List[str],
    self_shadow: List[str],
) -> float:
    """Compute a 0.0–1.0 pose complexity score.

    Higher = more complex pose = less reliable naive lighting inference.
    """
    factors = []

    # Torso rotation: 0°=simple, 45°+=complex
    factors.append(min(1.0, abs(torso_rotation) / 45.0))

    # Head rotation: 0°=simple, 30°+=complex
    factors.append(min(1.0, abs(head_rotation) / 30.0))

    # Shoulder angle: 0°=level, 20°+=complex
    factors.append(min(1.0, abs(shoulder_angle) / 20.0))

    # Hip angle asymmetry
    factors.append(min(1.0, abs(hip_angle) / 20.0))

    # Arm occlusion: each region adds complexity
    factors.append(min(1.0, len(arm_occlusion) * 0.3))

    # Self-shadow regions
    factors.append(min(1.0, len(self_shadow) * 0.25))

    return round(float(np.mean(factors)), 3)


def pose_solver_pass(
    img_bgr: np.ndarray,
    geometry: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Estimate how pose affects visible light and shadow distribution.

    Detects body geometry (rotation, lean, angles) and identifies regions
    where pose creates misleading lighting cues (self-shadow, occlusion).

    This pass does NOT determine lighting — it only explains pose geometry
    and corrects signal interpretation for downstream passes.

    Returns:
        torso_rotation_deg, head_rotation_deg, shoulder_line_angle_deg,
        hip_line_angle_deg, chin_pitch, chin_yaw_deg, subject_lean,
        arm_occlusion_regions, leg_occlusion_regions,
        body_surface_normals_estimate,
        pose_shadow_interference, pose_highlight_interference,
        occluded_regions, self_shadow_regions,
        pose_complexity_score, pose_confidence_adjustment
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    geo = geometry or {}

    # Try to use MediaPipe PoseLandmarker for precise measurements
    landmarks: Dict[int, Tuple[float, float]] = {}
    try:
        import mediapipe as mp_lib
        _model_dir = Path(__file__).resolve().parent.parent / "data" / "mp_models"
        pose_model = _model_dir / "pose_landmarker_lite.task"

        if pose_model.exists():
            pose_opts = mp_lib.tasks.vision.PoseLandmarkerOptions(
                base_options=mp_lib.tasks.BaseOptions(model_asset_path=str(pose_model)),
                running_mode=mp_lib.tasks.vision.RunningMode.IMAGE,
            )
            landmarker = mp_lib.tasks.vision.PoseLandmarker.create_from_options(pose_opts)
            try:
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=img_rgb)
                pose_result = landmarker.detect(mp_image)
                if pose_result.pose_landmarks:
                    lms = pose_result.pose_landmarks[0]
                    for idx, lm in enumerate(lms):
                        landmarks[idx] = (lm.x * w, lm.y * h)
            finally:
                landmarker.close()
    except Exception as exc:
        logger.debug("MediaPipe pose detection failed, using fallbacks: %s", exc)

    # ── Torso rotation ──
    torso_rotation = 0.0
    l_shoulder = landmarks.get(_LM_LEFT_SHOULDER)
    r_shoulder = landmarks.get(_LM_RIGHT_SHOULDER)

    if l_shoulder and r_shoulder:
        # Measure apparent width of each shoulder-to-center segment
        mid = _midpoint(l_shoulder, r_shoulder)
        left_dist = math.hypot(l_shoulder[0] - mid[0], l_shoulder[1] - mid[1])
        right_dist = math.hypot(r_shoulder[0] - mid[0], r_shoulder[1] - mid[1])
        torso_rotation = _estimate_rotation_from_width_ratio(left_dist, right_dist)
    elif geo.get("torso_rotation_deg") is not None:
        torso_rotation = float(geo["torso_rotation_deg"])

    # ── Head rotation ──
    head_rotation = 0.0
    l_ear = landmarks.get(_LM_LEFT_EAR)
    r_ear = landmarks.get(_LM_RIGHT_EAR)
    nose = landmarks.get(_LM_NOSE)

    if l_ear and r_ear and nose:
        ear_mid = _midpoint(l_ear, r_ear)
        left_ear_dist = math.hypot(nose[0] - l_ear[0], nose[1] - l_ear[1])
        right_ear_dist = math.hypot(nose[0] - r_ear[0], nose[1] - r_ear[1])
        head_rotation = _estimate_rotation_from_width_ratio(left_ear_dist, right_ear_dist)
    elif geo.get("head_rotation_deg") is not None:
        head_rotation = float(geo["head_rotation_deg"])

    # ── Shoulder line angle ──
    shoulder_angle = 0.0
    if l_shoulder and r_shoulder:
        shoulder_angle = _angle_between_points(l_shoulder, r_shoulder)
    elif geo.get("shoulder_line_angle") is not None:
        shoulder_angle = float(geo["shoulder_line_angle"])

    # ── Hip line angle ──
    hip_angle = 0.0
    l_hip = landmarks.get(_LM_LEFT_HIP)
    r_hip = landmarks.get(_LM_RIGHT_HIP)
    if l_hip and r_hip:
        hip_angle = _angle_between_points(l_hip, r_hip)

    # ── Chin pitch and yaw ──
    chin_pitch = "neutral"
    chin_yaw = 0.0
    if face_box is not None and nose:
        _, fy0, _, fy1 = face_box
        face_h = fy1 - fy0
        nose_relative_y = (nose[1] - fy0) / max(face_h, 1)
        if nose_relative_y > 0.55:
            chin_pitch = "slightly_down"
        elif nose_relative_y > 0.65:
            chin_pitch = "down"
        elif nose_relative_y < 0.35:
            chin_pitch = "up"
        elif nose_relative_y < 0.45:
            chin_pitch = "slightly_up"

        # Yaw from nose offset from face center
        fx0, _, fx1, _ = face_box
        face_w = fx1 - fx0
        nose_relative_x = (nose[0] - fx0) / max(face_w, 1)
        chin_yaw = (nose_relative_x - 0.5) * 60.0  # rough: ±30°
    elif face_box is not None:
        # Estimate from face box alone — check vertical center of brightness
        fx0, fy0, fx1, fy1 = face_box
        face_gray = cv2.cvtColor(img_bgr[fy0:fy1, fx0:fx1], cv2.COLOR_BGR2GRAY)
        if face_gray.size > 0:
            col_means = np.mean(face_gray, axis=0)
            if len(col_means) > 5:
                peak_x = float(np.argmax(col_means)) / len(col_means)
                chin_yaw = (peak_x - 0.5) * 40.0

    # ── Subject lean ──
    subject_lean = "none"
    if l_shoulder and r_shoulder and l_hip and r_hip:
        shoulder_mid = _midpoint(l_shoulder, r_shoulder)
        hip_mid = _midpoint(l_hip, r_hip)
        lean_x = shoulder_mid[0] - hip_mid[0]
        lean_threshold = w * 0.03
        if lean_x > lean_threshold:
            subject_lean = "camera_right"
        elif lean_x < -lean_threshold:
            subject_lean = "camera_left"
        # Check forward/back from vertical alignment shift
        lean_y = shoulder_mid[1] - hip_mid[1]
        if abs(lean_y) < h * 0.15:  # shoulders unusually close to hips → forward lean
            subject_lean = "toward_camera"

    # ── Arm & leg occlusion ──
    arm_occlusion = _detect_arm_occlusion(landmarks, h, w)
    leg_occlusion = _detect_leg_occlusion(landmarks, h, w)

    # ── Body surface normals estimate ──
    chest_axis = torso_rotation * 0.9  # chest follows torso closely
    abdomen_axis = torso_rotation * 0.7  # abdomen slightly less
    face_axis = head_rotation * 0.8

    body_normals = {
        "chest_axis_deg": round(chest_axis, 1),
        "abdomen_axis_deg": round(abdomen_axis, 1),
        "face_axis_deg": round(face_axis, 1),
    }

    # ── Pose-induced interference ──
    self_shadow_regions = _detect_self_shadow_regions(
        chin_pitch, torso_rotation, arm_occlusion,
    )

    occluded_regions = list(set(arm_occlusion + leg_occlusion))

    pose_shadow_interference = len(self_shadow_regions) > 0
    pose_highlight_interference = abs(torso_rotation) > 20 or abs(head_rotation) > 15

    # ── Pose complexity score ──
    complexity = _compute_pose_complexity(
        torso_rotation, head_rotation, shoulder_angle,
        hip_angle, arm_occlusion, self_shadow_regions,
    )

    # Confidence adjustment rule
    if complexity > 0.6:
        confidence_adjustment = "reduce_lighting_confidence"
    elif complexity > 0.35:
        confidence_adjustment = "moderate_caution"
    else:
        confidence_adjustment = "normal"

    return {
        "ok": True,
        "torso_rotation_deg": round(torso_rotation, 1),
        "head_rotation_deg": round(head_rotation, 1),
        "shoulder_line_angle_deg": round(shoulder_angle, 1),
        "hip_line_angle_deg": round(hip_angle, 1),
        "chin_pitch": chin_pitch,
        "chin_yaw_deg": round(chin_yaw, 1),
        "subject_lean": subject_lean,
        "arm_occlusion_regions": arm_occlusion,
        "leg_occlusion_regions": leg_occlusion,
        "body_surface_normals_estimate": body_normals,
        "pose_shadow_interference": pose_shadow_interference,
        "pose_highlight_interference": pose_highlight_interference,
        "occluded_regions": occluded_regions,
        "self_shadow_regions": self_shadow_regions,
        "pose_complexity_score": complexity,
        "pose_confidence_adjustment": confidence_adjustment,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1B. CAMERA GEOMETRY PASS
# ═══════════════════════════════════════════════════════════════════════════


def camera_geometry_pass(
    face_geometry: Optional[Dict[str, Any]] = None,
    pose_solver: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Estimate camera height and horizontal angle from face mesh landmarks.

    Camera height: uses perspective foreshortening of facial vertical
    proportions.  When the camera is above eye level, the forehead region
    appears compressed and the chin region expands (and vice versa).
    Metric: where the nose tip falls between forehead top and chin (0–1).

    Camera horizontal angle: combines the face yaw (from face mesh
    landmarks 1/234/454) with torso rotation (from PoseLandmarker)
    to distinguish head turns from camera offset.

    Parameters
    ----------
    face_geometry : dict
        Landmark positions from ``_detect_catchlights()``:
        forehead_top, nose_bridge, nose_tip, chin, left/right_eye_center,
        face_yaw, image_size.
    pose_solver : dict
        Output from ``pose_solver_pass()``: torso_rotation_deg,
        head_rotation_deg, etc.

    Returns
    -------
    dict
        camera_height: "above" | "at_eye_level" | "below"
        camera_horizontal_angle: "straight_on" | "slight_left" | "slight_right"
            | "profile_left" | "profile_right"
        height_confidence / angle_confidence: 0.0–1.0
        measurements: raw metric values for debugging
    """
    if not face_geometry:
        return {"ok": False, "error": "no face geometry data"}

    forehead = face_geometry.get("forehead_top")
    nose_tip = face_geometry.get("nose_tip")
    chin     = face_geometry.get("chin")

    if not all([forehead, nose_tip, chin]):
        return {"ok": False, "error": "missing key landmarks (forehead/nose/chin)"}

    # ── Camera height ────────────────────────────────────────────────
    # t = where nose_tip falls between forehead and chin (0=forehead, 1=chin).
    # Standard facial proportions: nose tip ≈ 0.55 of the forehead-chin span.
    # Camera above → forehead compressed, nose pushed toward chin → t > 0.66
    # Camera below → chin compressed, nose pushed toward forehead → t < 0.46
    #
    # NOTE: thresholds widened from 0.62/0.48 after benchmark comparison
    # against gpt-4.1 / gpt-4o / o4-mini.  Butterfly lighting (key directly
    # above) pushes nose_t to ~0.63 via shadow displacement even when the
    # camera is at eye level.  0.66 absorbs that without losing real "above"
    # detection (true above-angle images push nose_t > 0.70).
    total_height = chin[1] - forehead[1]
    if total_height < 10:
        return {"ok": False, "error": "face too small for geometry estimation"}

    nose_t = (nose_tip[1] - forehead[1]) / total_height

    if nose_t > 0.66:
        camera_height = "above"
        height_confidence = min(0.9, 0.5 + (nose_t - 0.66) * 5)
    elif nose_t < 0.46:
        camera_height = "below"
        height_confidence = min(0.9, 0.5 + (0.46 - nose_t) * 5)
    else:
        camera_height = "at_eye_level"
        # Higher confidence nearer the center of the neutral band
        height_confidence = max(0.4, 0.7 - abs(nose_t - 0.56) * 3)

    # ── Camera horizontal angle ──────────────────────────────────────
    # face_yaw convention (from vision_pipeline.py):
    #   positive → nose toward camera-right → subject's right side visible
    #              → camera to subject's LEFT
    #   negative → nose toward camera-left  → subject's left side visible
    #              → camera to subject's RIGHT
    #
    # VLM label convention: "slight_left" = camera to viewer's left.
    # Since VLM describes the camera position from the viewer's perspective,
    # and face_yaw > 0 means the face points to our right (camera is to
    # subject's left, which is VIEWER'S LEFT when looking at the photo):
    #   face_yaw > 0  → "slight_left" / "profile_left"
    #   face_yaw < 0  → "slight_right" / "profile_right"
    face_yaw = face_geometry.get("face_yaw", 0.0)
    torso_rot = 0.0
    if pose_solver and pose_solver.get("ok"):
        torso_rot = pose_solver.get("torso_rotation_deg", 0.0) or 0.0

    yaw_deg = face_yaw * 90  # approximate face yaw in degrees

    # Combine face and torso rotation.  When both rotate the same direction,
    # the effective camera offset is stronger (whole body angled, not just head).
    # When torso is frontal but head turned, it's a head pose — still an effective
    # camera angle for lighting purposes, but lower confidence.
    combined = yaw_deg
    torso_aligned = False
    if abs(torso_rot) > 5 and (yaw_deg > 0) == (torso_rot > 0):
        combined = (yaw_deg + torso_rot * 0.5) / 1.5  # weighted blend
        torso_aligned = True

    abs_combined = abs(combined)
    if abs_combined < 15:
        # Dead zone widened from 8° → 12° → 15° after VLM comparison:
        # face_yaw picks up subtle asymmetries that all three VLMs classify
        # as "straight_on".  Head turns under ~15° are natural posing micro-
        # adjustments, not meaningful camera offset.  At 15° we match VLM
        # consensus on 80% of benchmark images while still catching real
        # camera angles (>18°).
        camera_horizontal = "straight_on"
        angle_confidence = 0.8
    elif abs_combined < 30:
        camera_horizontal = "slight_left" if combined > 0 else "slight_right"
        angle_confidence = 0.7 if torso_aligned else 0.55
    else:
        camera_horizontal = "profile_left" if combined > 0 else "profile_right"
        angle_confidence = 0.65 if torso_aligned else 0.45

    return {
        "ok": True,
        "camera_height": camera_height,
        "camera_horizontal_angle": camera_horizontal,
        "height_confidence": round(height_confidence, 3),
        "angle_confidence": round(angle_confidence, 3),
        "measurements": {
            "nose_t": round(nose_t, 4),
            "face_yaw_raw": round(face_yaw, 4),
            "face_yaw_deg": round(yaw_deg, 1),
            "torso_rotation_deg": round(torso_rot, 1),
            "combined_angle_deg": round(combined, 1),
            "torso_aligned": torso_aligned,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1A. SURFACE CLASS PASS
# ═══════════════════════════════════════════════════════════════════════════

# Valid surface class identifiers
_SURFACE_CLASSES = [
    "face_skin", "body_skin", "hair", "matte_fabric", "semi_gloss_fabric",
    "satin_silk", "leather", "metallic", "glass", "chrome_like",
    "skin_sheen", "matte_skin",
    "background_paper", "background_painted_wall", "unknown",
]

# HSV hue ranges for coarse skin detection (hue 0-180 in OpenCV)
_SKIN_HUE_RANGE = (5, 25)   # orange-ish
_SKIN_SAT_MIN = 30
_SKIN_VAL_MIN = 50

# Texture energy thresholds (Laplacian variance)
_TEXTURE_SMOOTH_THRESH = 200.0    # below = smooth/glossy
_TEXTURE_ROUGH_THRESH = 800.0     # above = rough/matte


def _classify_region_texture(
    img_bgr: np.ndarray,
    mask: np.ndarray,
) -> Tuple[str, float]:
    """Classify a masked region by texture + colour into a surface class.

    Returns ``(surface_class, confidence)``.
    """
    if cv2 is None:
        return "unknown", 0.0

    pixels = mask.sum()
    if pixels < 50:
        return "unknown", 0.0

    # HSV analysis
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h_ch = hsv[:, :, 0][mask > 0]
    s_ch = hsv[:, :, 1][mask > 0]
    v_ch = hsv[:, :, 2][mask > 0]

    mean_hue = float(np.mean(h_ch))
    mean_sat = float(np.mean(s_ch))
    mean_val = float(np.mean(v_ch))

    # Skin detection
    skin_mask_region = (
        (h_ch >= _SKIN_HUE_RANGE[0]) & (h_ch <= _SKIN_HUE_RANGE[1])
        & (s_ch >= _SKIN_SAT_MIN) & (v_ch >= _SKIN_VAL_MIN)
    )
    skin_ratio = float(skin_mask_region.sum()) / max(1, len(h_ch))

    if skin_ratio > 0.4:
        # Sub-classify skin by texture smoothness
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        masked_gray = np.where(mask > 0, gray, 0).astype(np.uint8)
        lap = cv2.Laplacian(masked_gray, cv2.CV_64F)
        lap_var = float(np.var(lap[mask > 0])) if pixels > 0 else 0.0
        if lap_var > _TEXTURE_SMOOTH_THRESH:
            return "skin_sheen", 0.7
        return "face_skin", 0.8

    # Texture analysis on non-skin region
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    masked_gray = np.where(mask > 0, gray, 0).astype(np.uint8)
    lap = cv2.Laplacian(masked_gray, cv2.CV_64F)
    lap_var = float(np.var(lap[mask > 0])) if pixels > 0 else 0.0

    # Specular pixel percentage (bright + low sat)
    bright_thresh = max(220, int(np.percentile(v_ch, 97))) if len(v_ch) > 10 else 220
    specular_pix = ((v_ch > bright_thresh) & (s_ch < 60)).sum()
    specular_ratio = float(specular_pix) / max(1, len(v_ch))

    # Chrome / glass / metallic
    if specular_ratio > 0.15 and mean_sat < 40:
        return "chrome_like", 0.7
    if specular_ratio > 0.10 and mean_sat < 50:
        return "glass", 0.6
    if specular_ratio > 0.05 and mean_sat < 60:
        return "metallic", 0.55

    # Dark + low-saturation = likely hair
    if mean_val < 80 and mean_sat < 60:
        return "hair", 0.65

    # Texture-based fabric classification
    if lap_var < _TEXTURE_SMOOTH_THRESH:
        if mean_sat > 80:
            return "satin_silk", 0.6
        return "matte_fabric", 0.55
    elif lap_var < _TEXTURE_ROUGH_THRESH:
        if mean_sat > 60:
            return "semi_gloss_fabric", 0.55
        return "matte_fabric", 0.5
    else:
        # High texture + brown hue range
        if 10 <= mean_hue <= 25 and mean_sat > 40:
            return "leather", 0.5
        return "matte_fabric", 0.4

    return "unknown", 0.3  # pragma: no cover


def _classify_background_region(
    img_bgr: np.ndarray,
    mask: np.ndarray,
) -> Tuple[str, float]:
    """Classify background texture as paper, painted wall, or unknown."""
    if cv2 is None:
        return "unknown", 0.0

    pixels = mask.sum()
    if pixels < 100:
        return "unknown", 0.0

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    bg_vals = gray[mask > 0]
    std = float(np.std(bg_vals))

    if std < 10:
        return "background_paper", 0.8
    elif std < 25:
        return "background_painted_wall", 0.6
    return "unknown", 0.4


def _compute_surface_complexity(
    dominant_surfaces: List[Dict[str, Any]],
    reflection_dominant_regions: List[str],
) -> float:
    """Compute 0.0-1.0 surface complexity score.

    Higher when many different surface classes are present, especially
    when reflective and diffuse surfaces are mixed.
    """
    classes = {s["surface_class"] for s in dominant_surfaces if s.get("surface_class")}
    classes.discard("unknown")

    score = 0.0

    # Distinct surface classes (normalised to ~0.4 for 4+ classes)
    n = len(classes)
    if n >= 4:
        score += 0.4
    elif n >= 2:
        score += n * 0.1

    # Reflection-dominant regions
    if reflection_dominant_regions:
        score += 0.2

    # Mix of specular + diffuse
    reflective = {"metallic", "chrome_like", "glass", "skin_sheen"}
    diffuse = {"matte_fabric", "matte_skin", "background_paper", "background_painted_wall"}
    has_reflective = bool(classes & reflective)
    has_diffuse = bool(classes & diffuse)
    if has_reflective and has_diffuse:
        score += 0.15

    # Chrome/glass specifically
    if classes & {"chrome_like", "glass"}:
        score += 0.25

    return min(1.0, score)


def surface_class_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    background_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Classify dominant visible surfaces into material regions.

    Uses HSV colour analysis + texture analysis (Laplacian variance) to
    classify regions.  Does NOT replace specular_surface_pass or
    highlight_pass — those still extract raw signals.  This pass provides
    material context for reconstruction to correct signal interpretation.

    Returns:
        ok: bool
        dominant_surfaces: list of {region, surface_class, confidence}
        global_surface_bias: the most common surface class by area
        surface_complexity_score: 0.0-1.0
        surface_confidence_adjustment: "normal" | "moderate_caution" | "reduce_confidence"
        reflection_dominant_regions: list of region names dominated by reflection
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    if h < 20 or w < 20:
        return {"ok": False, "error": "image too small for surface analysis"}

    dominant_surfaces: List[Dict[str, Any]] = []
    reflection_dominant_regions: List[str] = []

    # Build person mask if not provided
    if person_mask is not None:
        pmask = person_mask.astype(bool)
    else:
        pmask = np.ones((h, w), dtype=bool)

    # ── Face region ─────────────────────────────────────────────────────
    if face_box is not None:
        fx1, fy1, fx2, fy2 = face_box
        fx1, fy1 = max(0, fx1), max(0, fy1)
        fx2, fy2 = min(w, fx2), min(h, fy2)
        face_mask = np.zeros((h, w), dtype=bool)
        face_mask[fy1:fy2, fx1:fx2] = True
        face_mask &= pmask

        cls, conf = _classify_region_texture(img_bgr, face_mask.astype(np.uint8))
        # Override to face_skin family if skin-like
        if cls in ("face_skin", "skin_sheen", "matte_skin"):
            dominant_surfaces.append({"region": "face", "surface_class": cls, "confidence": conf})
        else:
            dominant_surfaces.append({"region": "face", "surface_class": "face_skin", "confidence": 0.5})
    else:
        face_mask = np.zeros((h, w), dtype=bool)

    # ── Hair region (above face within person mask) ─────────────────────
    if face_box is not None:
        fy1 = max(0, face_box[1])
        hair_mask = np.zeros((h, w), dtype=bool)
        hair_mask[:fy1, :] = True
        hair_mask &= pmask
        if hair_mask.sum() > 50:
            cls, conf = _classify_region_texture(img_bgr, hair_mask.astype(np.uint8))
            if cls == "hair" or (cls == "unknown" and conf < 0.5):
                cls = "hair"
                conf = max(conf, 0.5)
            dominant_surfaces.append({"region": "hair", "surface_class": cls, "confidence": conf})

    # ── Body upper (below face to mid-person) ───────────────────────────
    if face_box is not None:
        fy2 = min(h, face_box[3])
        mid_y = (fy2 + h) // 2
        body_upper_mask = np.zeros((h, w), dtype=bool)
        body_upper_mask[fy2:mid_y, :] = True
        body_upper_mask &= pmask
        body_upper_mask &= ~face_mask
    else:
        mid_y = h // 2
        body_upper_mask = np.zeros((h, w), dtype=bool)
        body_upper_mask[:mid_y, :] = True
        body_upper_mask &= pmask

    if body_upper_mask.sum() > 50:
        cls, conf = _classify_region_texture(img_bgr, body_upper_mask.astype(np.uint8))
        dominant_surfaces.append({"region": "body_upper", "surface_class": cls, "confidence": conf})
        # Check for reflection-dominant
        if cls in ("chrome_like", "glass", "metallic"):
            reflection_dominant_regions.append("body_upper")

    # ── Body lower ──────────────────────────────────────────────────────
    body_lower_mask = np.zeros((h, w), dtype=bool)
    body_lower_mask[mid_y:, :] = True
    body_lower_mask &= pmask

    if body_lower_mask.sum() > 50:
        cls, conf = _classify_region_texture(img_bgr, body_lower_mask.astype(np.uint8))
        dominant_surfaces.append({"region": "body_lower", "surface_class": cls, "confidence": conf})
        if cls in ("chrome_like", "glass", "metallic"):
            reflection_dominant_regions.append("body_lower")

    # ── Background ──────────────────────────────────────────────────────
    if background_mask is not None:
        bg_mask = background_mask.astype(bool)
    else:
        # Use outer 20% strips as background proxy
        bg_mask = np.zeros((h, w), dtype=bool)
        margin_x = max(1, w // 5)
        bg_mask[:, :margin_x] = True
        bg_mask[:, w - margin_x:] = True
        bg_mask &= ~pmask

    if bg_mask.sum() > 100:
        cls, conf = _classify_background_region(img_bgr, bg_mask.astype(np.uint8))
        dominant_surfaces.append({"region": "background", "surface_class": cls, "confidence": conf})

    # ── Global surface bias ─────────────────────────────────────────────
    class_counts: Dict[str, int] = {}
    for s in dominant_surfaces:
        c = s["surface_class"]
        class_counts[c] = class_counts.get(c, 0) + 1
    global_surface_bias = max(class_counts, key=class_counts.get) if class_counts else "unknown"

    # ── Complexity & confidence adjustment ──────────────────────────────
    complexity = _compute_surface_complexity(dominant_surfaces, reflection_dominant_regions)

    if complexity > 0.6:
        adj = "reduce_confidence"
    elif complexity > 0.3:
        adj = "moderate_caution"
    else:
        adj = "normal"

    return {
        "ok": True,
        "dominant_surfaces": dominant_surfaces,
        "global_surface_bias": global_surface_bias,
        "surface_complexity_score": round(complexity, 3),
        "surface_confidence_adjustment": adj,
        "reflection_dominant_regions": reflection_dominant_regions,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. SHADOW PASS
# ═══════════════════════════════════════════════════════════════════════════

def shadow_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Extract detailed shadow signals from the image.

    Returns:
        shadow_vector_deg: Direction shadow falls (0-360). Convention matches VLM:
            0° = shadow falls straight down (butterfly / key directly above).
            90° = shadow falls to camera-right.
            180° = shadow falls straight up (unusual; back-lit).
            270° = shadow falls to camera-left (typical loop with key at camera-right).
        shadow_vertical_angle_deg: Vertical angle of shadow
        shadow_softness: 0.0 (razor sharp) → 1.0 (fully diffused)
        shadow_length_ratio: Nose shadow length / nose length
        shadow_edge_gradient: How gradual the shadow transition is (0-1)
        shadow_visible_on: Facial zones with measurable shadow coverage
            (subset of: nose, cheek_left, cheek_right, jaw_left, jaw_right, neck)
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Work within person region if available
    if person_mask is not None:
        roi_mask = person_mask.astype(np.uint8) * 255
    else:
        roi_mask = np.ones((h, w), dtype=np.uint8) * 255

    # Focus on face region if available
    if face_box is not None:
        x0, y0, x1, y1 = face_box
        face_roi_mask = np.zeros((h, w), dtype=np.uint8)
        face_roi_mask[y0:y1, x0:x1] = 255
        analysis_mask = cv2.bitwise_and(roi_mask, face_roi_mask)
    else:
        analysis_mask = roi_mask

    masked_gray = cv2.bitwise_and(gray, analysis_mask)

    # -- Shadow vector via gradient analysis --
    # Compute image gradients in the masked region
    grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=5)
    grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=5)

    # Mask to valid pixels
    valid = analysis_mask > 0
    if not np.any(valid):
        return {"ok": False, "error": "no valid pixels for shadow analysis"}

    # ── Shadow boundary refinement — nose-level ROI ────────────────────────────
    # Computing gradients over ALL face edges (hair, eye outline, lips) corrupts
    # the mean direction because hair and clothing edges dominate the top-25% pool.
    # Fix: focus on the NOSE-LEVEL region (rows 45–72% of face height) where the
    # key cast shadow lies, then restrict to shadow-boundary pixels only.
    # Hair shadows (top of face) and jaw/neck shadows (bottom) are excluded —
    # they contain spurious edges that pull the mean away from the actual shadow.
    if face_box is not None:
        _sv_x0, _sv_y0, _sv_x1, _sv_y1 = face_box
        _sv_fh = _sv_y1 - _sv_y0
        # Nose shadow zone: rows 45–72% of face height
        _sv_r0 = _sv_y0 + int(0.45 * _sv_fh)
        _sv_r1 = _sv_y0 + int(0.72 * _sv_fh)
        _sv_face_nose = gray[_sv_r0:_sv_r1, _sv_x0:_sv_x1].astype(float)
        if _sv_face_nose.size > 0:
            # Use overall face mean for thresholding (not just nose sub-region)
            _sv_face_full = gray[_sv_y0:_sv_y1, _sv_x0:_sv_x1].astype(float)
            _sv_mean = float(np.mean(_sv_face_full))
            _sv_shadow_m = (_sv_face_nose < _sv_mean * 0.82).astype(np.uint8)
            if np.sum(_sv_shadow_m) > 20:
                _sv_ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
                _sv_dilated = cv2.dilate(_sv_shadow_m, _sv_ker)
                # Shadow boundary = pixels just outside the shadow mask
                _sv_boundary = (_sv_dilated.astype(bool)) & (~_sv_shadow_m.astype(bool))
                _sv_full = np.zeros((h, w), dtype=bool)
                _sv_full[_sv_r0:_sv_r1, _sv_x0:_sv_x1] = _sv_boundary
                _valid_shadow = valid & _sv_full
                if np.sum(_valid_shadow) > 15:
                    valid = _valid_shadow  # refined: nose-level shadow-edge pixels only

    gx = grad_x[valid]
    gy = grad_y[valid]

    # Weighted mean gradient direction (weighted by magnitude)
    magnitudes = np.sqrt(gx**2 + gy**2)
    strong = magnitudes > np.percentile(magnitudes, 75)  # top 25% edges

    if np.sum(strong) < 10:
        shadow_vector = None
        shadow_vertical = None
    else:
        mean_gx = np.mean(gx[strong])
        mean_gy = np.mean(gy[strong])
        # Convert to degrees matching VLM convention:
        # 0° = shadow falls straight down (key directly above = butterfly).
        # The gradient points toward the bright side; shadow falls opposite.
        # atan2(gx, -gy) gives clock-from-top; adding 180° shifts so 0=down.
        angle_rad = math.atan2(mean_gx, -mean_gy)
        shadow_vector = (math.degrees(angle_rad) + 180.0 + 360.0) % 360.0
        # Vertical component
        shadow_vertical = abs(math.degrees(math.atan2(mean_gy, mean_gx)))
        shadow_vertical = min(shadow_vertical, 90.0)

    # -- Shadow softness via edge gradient analysis --
    # Use Canny with two thresholds to detect hard vs soft edges
    edges_hard = cv2.Canny(masked_gray, 100, 200)
    edges_soft = cv2.Canny(masked_gray, 30, 80)

    hard_count = np.sum(edges_hard[valid] > 0)
    soft_count = np.sum(edges_soft[valid] > 0)

    if soft_count > 0:
        # Ratio of hard edges to all edges → inverse is softness
        hardness_ratio = hard_count / soft_count
        shadow_softness = max(0.0, min(1.0, 1.0 - hardness_ratio))
    else:
        shadow_softness = 0.5  # default

    # -- Shadow length ratio --
    # Measure the vertical extent of nose cast shadow relative to estimated nose length.
    # Convention matches VLM: nose shadow length / nose length, nose length ≈ 15% face height.
    # Strategy: scan rows 50–72% of face height on the shadow side (whichever half is darker),
    # count rows below (face_mean * 0.88), divide by nose_est.
    shadow_length_ratio = None
    if face_box is not None:
        x0, y0, x1, y1 = face_box
        face_gray = gray[y0:y1, x0:x1].astype(float)
        if face_gray.size > 0:
            face_h = y1 - y0
            face_w_sl = x1 - x0
            face_mean_sl = float(np.mean(face_gray))
            shadow_thr_sl = face_mean_sl * 0.88
            nose_est = max(1, int(face_h * 0.15))
            # Determine shadow side: left or right half of face, whichever is darker
            mid = face_w_sl // 2
            left_mean = float(np.mean(face_gray[:, :mid]))
            right_mean = float(np.mean(face_gray[:, mid:]))
            c_start, c_end = (0, mid) if left_mean < right_mean else (mid, face_w_sl)
            # Scan under-nose rows on shadow side
            r_start = int(face_h * 0.50)
            r_end = int(face_h * 0.72)
            shadow_rows = 0
            for row in range(r_start, min(r_end, face_h)):
                row_mean = float(np.mean(face_gray[row, c_start:c_end]))
                if row_mean < shadow_thr_sl:
                    shadow_rows += 1
            shadow_length_ratio = max(0.0, min(2.0, shadow_rows / nose_est))

    # -- Shadow edge gradient --
    # Measure transition zone width between light and dark areas
    if np.any(valid):
        values = gray[valid].astype(float)
        median_val = np.median(values)
        # Shadow pixels vs highlight pixels
        shadow_px = values[values < median_val * 0.7]
        highlight_px = values[values > median_val * 1.3]

        if len(shadow_px) > 10 and len(highlight_px) > 10:
            # Transition zone: pixels between shadow and highlight thresholds
            transition_lo = median_val * 0.7
            transition_hi = median_val * 1.3
            transition_px = values[(values >= transition_lo) & (values <= transition_hi)]
            transition_ratio = len(transition_px) / len(values)
            shadow_edge_gradient = min(1.0, transition_ratio * 3.0)
        else:
            shadow_edge_gradient = 0.5
    else:
        shadow_edge_gradient = 0.5

    # -- Shadow visible on (cascade zone detection) --
    # Detect which facial zones carry measurable shadow, matching VLM's shadow_visible_on field.
    # Zones: nose, cheek_left, cheek_right, jaw_left, jaw_right, neck.
    # A zone is "in shadow" if its mean brightness is < face_mean * 0.82 (18% darker than average).
    shadow_visible_on: List[str] = []
    if face_box is not None:
        x0, y0, x1, y1 = face_box
        fh = y1 - y0
        fw = x1 - x0
        face_region = gray[y0:y1, x0:x1].astype(float)
        # Use the brighter horizontal half as the skin-tone reference so the
        # threshold tracks actual reflectance rather than the shadow-depressed
        # whole-face mean. This keeps zone thresholds stable across skin tones
        # and lighting ratios (loop fill-side shadow pulls the whole-face mean
        # down ~10–15%, causing the cheek threshold to miss subtler shadows).
        if face_region.size > 0:
            _col_means = np.mean(face_region, axis=0)
            _half = max(1, len(_col_means) // 2)
            face_mean_brightness = float(max(np.mean(_col_means[:_half]), np.mean(_col_means[_half:])))
        else:
            face_mean_brightness = 128.0
        shadow_thresh = face_mean_brightness * 0.82

        # Zone definitions as (row_start, row_end, col_start, col_end, threshold_mult).
        # "nose" is handled separately — the cast shadow falls on the SHADOW SIDE of the face
        # (the side with lower mean brightness).  Both left and right sub-zones are checked
        # and "nose" is added if either is in shadow.
        # Cheeks use 0.92 (8% darker): loop fill-side cheek shadow is compressed by fill to
        # only 5–8% below face mean — too subtle for the 0.88 jaw/neck threshold.
        # Jaw/neck use 0.88 (12% darker): these deeper shadow zones are more pronounced.
        shadow_thresh = face_mean_brightness * 0.88  # retained for nose/neck below
        zone_defs = {
            "cheek_left":  (0.30, 0.60, 0.00, 0.42, 0.92),
            "cheek_right": (0.30, 0.60, 0.58, 1.00, 0.92),
            "jaw_left":    (0.62, 0.85, 0.05, 0.48, 0.88),
            "jaw_right":   (0.62, 0.85, 0.52, 0.95, 0.88),
        }
        for zone_name, (r0, r1, c0, c1, thresh_mult) in zone_defs.items():
            ry0 = int(r0 * fh)
            ry1 = int(r1 * fh)
            cx0 = int(c0 * fw)
            cx1 = int(c1 * fw)
            patch = face_region[ry0:ry1, cx0:cx1]
            zone_thresh = face_mean_brightness * thresh_mult
            if patch.size > 20 and float(np.mean(patch)) < zone_thresh:
                shadow_visible_on.append(zone_name)

        # Nose: check left and right sub-zones of under-nose area (rows 55–72%, split at center)
        nose_left  = face_region[int(0.55*fh):int(0.72*fh), :fw//2]
        nose_right = face_region[int(0.55*fh):int(0.72*fh), fw//2:]
        if ((nose_left.size > 20 and float(np.mean(nose_left)) < shadow_thresh) or
                (nose_right.size > 20 and float(np.mean(nose_right)) < shadow_thresh)):
            shadow_visible_on.insert(0, "nose")  # nose first in the list

        # Neck: region just below the face box
        neck_y0 = y1
        neck_y1 = min(gray.shape[0], y1 + fh // 5)
        if neck_y1 > neck_y0:
            neck_region = gray[neck_y0:neck_y1, x0:x1].astype(float)
            if neck_region.size > 20 and float(np.mean(neck_region)) < shadow_thresh:
                shadow_visible_on.append("neck")

    return {
        "ok": True,
        "shadow_vector_deg": round(shadow_vector, 1) if shadow_vector is not None else None,
        "shadow_vertical_angle_deg": round(shadow_vertical, 1) if shadow_vertical is not None else None,
        "shadow_softness": round(shadow_softness, 3),
        "shadow_length_ratio": round(shadow_length_ratio, 3) if shadow_length_ratio is not None else None,
        "shadow_edge_gradient": round(shadow_edge_gradient, 3),
        "shadow_visible_on": shadow_visible_on,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. HIGHLIGHT PASS
# ═══════════════════════════════════════════════════════════════════════════

_HIGHLIGHT_REGIONS = ["face", "cheekbone", "forehead", "shoulder", "clavicle", "torso"]


def highlight_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    shadow_vector_deg: Optional[float] = None,
) -> Dict[str, Any]:
    """Detect highlight regions and extract highlight signals.

    Returns:
        highlight_width_ratio: Width of lit side / total face width
        highlight_rolloff_rate: How quickly intensity falls off (0-1)
        highlight_edge_gradient: Highlight edge transition smoothness
        highlight_axis_deg: Angle of highlight band relative to vertical (0=vertical, 90=horizontal).
            Convention matches VLM.  Derived geometrically from shadow_vector_deg when available:
            90° × |cos(sv_rad)|.  Butterfly/on-axis → 90°; side key → 0°; loop (sv≈90°) → ~0–15°.
        highlight_specularity: 0.0 (matte diffuse) → 1.0 (mirror specular).
            Measured as the fraction of face highlight pixels that also carry sharp edges.
            Matte skin: broad highlights with smooth falloff → low value.
            Specular: tight hotspot with hard edge → high value.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Use person mask if available
    if person_mask is not None:
        pmask = person_mask.astype(np.uint8)
    else:
        pmask = np.ones((h, w), dtype=np.uint8)

    # Analyze face region for highlight width
    if face_box is not None:
        x0, y0, x1, y1 = face_box
        face_gray = gray[y0:y1, x0:x1]
        face_w = x1 - x0
    else:
        # Use center crop as approximation
        cx, cy = w // 2, h // 3
        fw, fh = w // 3, h // 3
        x0, y0 = max(0, cx - fw//2), max(0, cy - fh//2)
        x1, y1 = min(w, cx + fw//2), min(h, cy + fh//2)
        face_gray = gray[y0:y1, x0:x1]
        face_w = x1 - x0

    if face_gray.size == 0:
        return {"ok": False, "error": "no face region for highlight analysis"}

    # -- Highlight width ratio --
    # Compute column-wise mean brightness to find the highlight band
    col_means = np.mean(face_gray, axis=0).astype(float)
    if len(col_means) < 5:
        return {"ok": False, "error": "face region too small"}

    overall_mean = np.mean(col_means)
    highlight_threshold = overall_mean * 1.15  # 15% brighter than average
    highlight_cols = col_means > highlight_threshold
    highlight_width_ratio = float(np.sum(highlight_cols)) / len(col_means)

    # -- Highlight rolloff rate --
    # Measure how quickly brightness drops from peak
    if len(col_means) >= 5:
        peak_idx = int(np.argmax(col_means))
        peak_val = col_means[peak_idx]

        # Find distance to where brightness drops to 50% of peak-to-mean delta
        delta = peak_val - overall_mean
        if delta > 5:
            half_brightness = peak_val - delta * 0.5
            # Check both sides
            distances = []
            for direction in [-1, 1]:
                idx = peak_idx
                while 0 <= idx < len(col_means):
                    if col_means[idx] < half_brightness:
                        distances.append(abs(idx - peak_idx))
                        break
                    idx += direction
            if distances:
                avg_dist = np.mean(distances)
                # Normalize: short distance = fast rolloff (high value)
                rolloff = 1.0 - min(1.0, avg_dist / (len(col_means) * 0.5))
            else:
                rolloff = 0.3
        else:
            rolloff = 0.5  # flat/even lighting
    else:
        rolloff = 0.5

    # -- Highlight edge gradient --
    # Smoothness of the highlight boundary
    if len(col_means) >= 5:
        gradient = np.abs(np.diff(col_means))
        mean_gradient = float(np.mean(gradient))
        max_gradient = float(np.max(gradient)) if len(gradient) > 0 else 1.0
        edge_gradient = min(1.0, mean_gradient / max(max_gradient, 1.0))
    else:
        edge_gradient = 0.5

    # -- Highlight axis --
    # Convention matches VLM: 0° = perfectly vertical highlight band (side key at 90° off-axis),
    # 90° = perfectly horizontal band (butterfly / key directly above).
    # Primary method: fitEllipse on the top-quartile highlight region of the face — directly
    #   measures the tilt of the bright band without depending on shadow_vector accuracy.
    # Fallback: derive geometrically from shadow_vector_deg when no face box is available.
    #   highlight_axis = 90° × |cos(shadow_vector_deg_rad)|
    highlight_axis_deg = None
    if face_box is not None:
        x0_h, y0_h, x1_h, y1_h = face_box
        face_gray_h = gray[y0_h:y1_h, x0_h:x1_h]
        if face_gray_h.size > 0:
            thresh_val = int(np.percentile(face_gray_h, 75))
            _, hl_bin = cv2.threshold(face_gray_h, thresh_val, 255, cv2.THRESH_BINARY)
            contours_h, _ = cv2.findContours(hl_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours_h:
                largest_h = max(contours_h, key=cv2.contourArea)
                if len(largest_h) >= 5:
                    (_, _), (_, _), fit_angle = cv2.fitEllipse(largest_h)
                    highlight_axis_deg = float(abs(90.0 - fit_angle))
    if highlight_axis_deg is None and shadow_vector_deg is not None:
        highlight_axis_deg = round(90.0 * abs(math.cos(math.radians(shadow_vector_deg))), 1)

    # -- Specularity --
    # Convention matches VLM: 0.0 = fully matte/diffuse, 1.0 = mirror specular.
    # Two-component blend:
    #   edge_component (40%): bright ∩ sharp / bright — captures hard specular hotspots.
    #   peak_component (60%): (p90 / p50 − 1) / 2 — captures surface reflectance including
    #       the natural skin sheen floor (~0.15–0.25) present even on matte skin.
    # Combined: specularity = 0.4 × edge + 0.6 × peak.
    specularity = 0.2  # neutral default
    if face_box is not None:
        x0_s, y0_s, x1_s, y1_s = face_box
        face_gray_s = gray[y0_s:y1_s, x0_s:x1_s].astype(np.float32)
        if face_gray_s.size > 100:
            bright_thresh = float(np.percentile(face_gray_s, 75))
            bright_mask = face_gray_s > bright_thresh
            sobel_x = cv2.Sobel(face_gray_s, cv2.CV_32F, 1, 0, ksize=3)
            sobel_y = cv2.Sobel(face_gray_s, cv2.CV_32F, 0, 1, ksize=3)
            sobel_mag = np.sqrt(sobel_x**2 + sobel_y**2)
            sharp_thresh = float(np.percentile(sobel_mag, 75))
            sharp_mask = sobel_mag > sharp_thresh
            bright_count = int(np.sum(bright_mask))
            edge_component = float(np.sum(bright_mask & sharp_mask)) / bright_count if bright_count > 0 else 0.0

            p50_s = float(np.percentile(face_gray_s, 50))
            p90_s = float(np.percentile(face_gray_s, 90))
            peak_component = min(1.0, max(0.0, (p90_s / max(p50_s, 1.0) - 1.0) / 2.0))

            specularity = min(1.0, 0.4 * edge_component + 0.6 * peak_component)

    return {
        "ok": True,
        "highlight_width_ratio": round(highlight_width_ratio, 3),
        "highlight_rolloff_rate": round(rolloff, 3),
        "highlight_edge_gradient": round(edge_gradient, 3),
        "highlight_axis_deg": round(highlight_axis_deg, 1) if highlight_axis_deg is not None else None,
        "highlight_specularity": round(min(1.0, max(0.0, specularity)), 3),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. CATCHLIGHT PASS (ENHANCED)
# ═══════════════════════════════════════════════════════════════════════════

def catchlight_pass(
    img_bgr: np.ndarray,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    existing_catchlights: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enhanced catchlight detection with size and intensity signals.

    Extends existing catchlight detection with:
    - catchlight_size_ratio: size relative to iris
    - catchlight_intensity: brightness of catchlight (0-1)

    Returns:
        catchlight_count: Number of distinct light sources
        catchlight_shape: round/rectangular/octagonal/strip/mixed
        catchlight_position: Clock position (e.g. "upper_left")
        catchlight_size_ratio: Size of catchlight / iris diameter
        catchlight_intensity: Normalized brightness (0-1)
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    # Start with existing catchlight data if available
    base = existing_catchlights or {}
    count = base.get("light_count", 0)
    shape = "unknown"
    position = "unknown"

    # Analyze catchlight geometry from existing data
    eyes = base.get("eyes", [])
    if isinstance(eyes, list):
        for eye in eyes:
            if isinstance(eye, dict):
                catchlights = eye.get("catchlights", [])
                if catchlights:
                    count = max(count, len(catchlights))

    # If we have key_position from existing detection
    key_pos = base.get("key_position", "")
    if key_pos:
        position = key_pos

    # Determine shape from likely_modifier
    modifier_hint = base.get("likely_modifier", "")
    if "beauty dish" in modifier_hint.lower() or "round" in modifier_hint.lower():
        shape = "round"
    elif "softbox" in modifier_hint.lower() or "rect" in modifier_hint.lower():
        shape = "rectangular"
    elif "octa" in modifier_hint.lower():
        shape = "octagonal"
    elif "strip" in modifier_hint.lower():
        shape = "strip"

    # -- Enhanced: size ratio, intensity, and contour-based shape --
    catchlight_size_ratio = None
    catchlight_intensity = None
    # Collect per-eye circularity measurements for vision-based shape override
    _eye_circularities: list = []
    _eye_contour_areas: list = []

    if face_box is not None:
        x0, y0, x1, y1 = face_box
        face_h = y1 - y0
        face_w = x1 - x0

        # Estimate eye region (upper third of face, each side)
        eye_y_start = y0 + face_h // 4
        eye_y_end = y0 + face_h // 2
        eye_mid_x = x0 + face_w // 2

        for side in ["left", "right"]:
            if side == "left":
                ex0, ex1 = x0, eye_mid_x
            else:
                ex0, ex1 = eye_mid_x, x1

            ey0 = max(0, eye_y_start)
            ey1 = min(img_bgr.shape[0], eye_y_end)
            ex0 = max(0, ex0)
            ex1 = min(img_bgr.shape[1], ex1)

            if ey1 <= ey0 or ex1 <= ex0:
                continue

            eye_roi = cv2.cvtColor(img_bgr[ey0:ey1, ex0:ex1], cv2.COLOR_BGR2GRAY)

            if eye_roi.size < 100:
                continue

            # Find bright spots in eye region.
            # Floor lowered 200 → 180: catchlights in dark irises (dark-skinned
            # subjects, brown/dark eyes) can peak at 180-199 luma and were
            # missed with the original hard floor.
            thresh_val = max(180, int(np.percentile(eye_roi, 95)))
            _, bright = cv2.threshold(eye_roi, thresh_val, 255, cv2.THRESH_BINARY)

            bright_pixels = np.sum(bright > 0)
            total_pixels = eye_roi.size

            if bright_pixels > 2:
                # Size ratio: bright area / eye region area
                eye_area = (ex1 - ex0) * (ey1 - ey0)
                if eye_area > 0:
                    size_ratio = bright_pixels / (eye_area * 0.1)  # normalize to ~iris size
                    catchlight_size_ratio = min(0.5, size_ratio)

                # Intensity: mean brightness of catchlight pixels
                bright_values = eye_roi[bright > 0]
                if len(bright_values) > 0:
                    catchlight_intensity = float(np.mean(bright_values)) / 255.0

                # ── Contour-based shape analysis ──────────────────────
                # Measure circularity of the largest bright contour in
                # each eye.  Ring lights produce large, highly circular
                # catchlights (circularity > 0.55).  Rectangular softboxes
                # are typically < 0.4.
                # Use a lower threshold (200) for shape analysis when
                # the P95 threshold is very high (bright images like
                # high-key or B&W).  The P95 fragments ring reflections
                # that fill large portions of the eye.
                _shape_thresh = min(thresh_val, 200)
                _, _shape_bright = cv2.threshold(eye_roi, _shape_thresh, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(
                    _shape_bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
                )
                if contours:
                    largest = max(contours, key=cv2.contourArea)
                    area = cv2.contourArea(largest)
                    perimeter = cv2.arcLength(largest, True)
                    if perimeter > 0 and area > 5:
                        circularity = 4.0 * np.pi * area / (perimeter * perimeter)
                        _eye_circularities.append(circularity)
                        _eye_contour_areas.append(area)

    # ── Vision-based shape override ──────────────────────────────────
    # When modifier-hint shape is unknown or ambiguous, use contour
    # circularity and aspect ratio to classify the catchlight shape.
    if _eye_circularities and shape in ("unknown", "rectangular", "round"):
        _mean_circ = sum(_eye_circularities) / len(_eye_circularities)
        _max_area = max(_eye_contour_areas) if _eye_contour_areas else 0
        if _mean_circ > 0.55 and _max_area > 8:
            # Check existing per-catchlight shapes from vision_pipeline
            # for ring detection (hollow circle)
            _shapes_from_pipeline = []
            for eye in eyes:
                if isinstance(eye, dict):
                    for cl in eye.get("catchlights", []):
                        if isinstance(cl, dict) and cl.get("shape"):
                            _shapes_from_pipeline.append(cl["shape"])
            if "ring" in _shapes_from_pipeline:
                shape = "ring"
            elif shape != "round":
                shape = "round"

    return {
        "ok": True,
        "catchlight_count": count,
        "catchlight_shape": shape,
        "catchlight_position": position,
        "catchlight_size_ratio": round(catchlight_size_ratio, 3) if catchlight_size_ratio is not None else None,
        "catchlight_intensity": round(catchlight_intensity, 3) if catchlight_intensity is not None else None,
        "catchlight_circularity": round(sum(_eye_circularities) / len(_eye_circularities), 3) if _eye_circularities else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3b. CATCHLIGHT TOPOLOGY PASS
# ═══════════════════════════════════════════════════════════════════════════


def catchlight_topology_pass(
    img_bgr: np.ndarray,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    existing_catchlights: Optional[Dict[str, Any]] = None,
    catchlight_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Multi-catchlight topology analysis.

    Consumes Pipeline 1 catchlight data (MediaPipe iris landmarks, precise
    filtering) as the authoritative source.  Only falls back to a pixel
    re-scan when Pipeline 1 returned no catchlights.

    The re-scan path (lower threshold, face-box halving) is kept as a
    last-resort fallback — it produces noisier results and should not be
    the primary source.

    Parameters
    ----------
    img_bgr : np.ndarray
        BGR image.
    face_box : tuple or None
        (x0, y0, x1, y1) face bounding box.
    existing_catchlights : dict or None
        Raw catchlight pipeline data (from ``analyze_catchlights`` in
        vision_pipeline.py — Pipeline 1, MediaPipe iris landmarks).
    catchlight_data : dict or None
        Output from ``catchlight_pass`` for corroboration (unused now).

    Returns
    -------
    dict
        Flat dict suitable for pipeline ``results`` storage.  Includes
        ``raw_count`` (before dedup), ``displayed_count`` (after dedup),
        and ``dedup_note`` describing any merging that occurred.
    """
    import math as _math

    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    if face_box is None:
        return {
            "ok": True,
            "catchlight_count": 0,
            "raw_count": 0,
            "displayed_count": 0,
            "dedup_note": None,
            "cluster_geometry": "unknown",
            "cluster_spread_deg": 0.0,
            "inter_catchlight_spacing": [],
            "bilateral_symmetry_score": 0.0,
            "primary": None,
            "secondary": None,
            "tertiary": None,
            "confidence": 0.0,
            "notes": ["No face box — catchlight topology unavailable"],
        }

    x0, y0, x1, y1 = face_box
    face_h = y1 - y0
    face_w = x1 - x0
    if face_h < 20 or face_w < 20:
        return {
            "ok": True,
            "catchlight_count": 0,
            "raw_count": 0,
            "displayed_count": 0,
            "dedup_note": None,
            "cluster_geometry": "unknown",
            "cluster_spread_deg": 0.0,
            "inter_catchlight_spacing": [],
            "bilateral_symmetry_score": 0.0,
            "primary": None,
            "secondary": None,
            "tertiary": None,
            "confidence": 0.0,
            "notes": ["Face box too small for topology analysis"],
        }

    notes: List[str] = []

    # ── Convert clock-position string → clock_deg ─────────────────────
    # Pipeline 1 uses clock_position() which returns e.g. "12 o'clock upper_center".
    # We parse the leading integer and multiply by 30° (12 hours = 360°).
    def _pos_to_deg(pos_str: str) -> float:
        try:
            hour = int(pos_str.split()[0])
            return float((hour % 12) * 30)  # 12 o'clock → 0°, 3 → 90°, etc.
        except (ValueError, IndexError, AttributeError):
            return 0.0

    # ── Primary source: Pipeline 1 (MediaPipe iris landmarks) ────────
    all_catchlights: List[Dict[str, Any]] = []
    using_p1 = False

    p1_list: List[Dict[str, Any]] = (existing_catchlights or {}).get("catchlights", [])
    if p1_list:
        using_p1 = True
        for cl in p1_list:
            clock_deg = _pos_to_deg(cl.get("position", "12"))
            all_catchlights.append({
                "clock_deg": round(clock_deg, 1),
                "shape": cl.get("shape", "unknown"),
                "size_ratio": cl.get("size_ratio") or 0.0,
                "intensity": cl.get("intensity", 0.0),
                "eye": cl.get("eye", "unknown"),
                "area": 0,  # not available from P1
            })
        notes.append(f"Source: Pipeline 1 (MediaPipe iris, {len(p1_list)} raw catchlights)")

    # ── Fallback: pixel re-scan (face-box halving, lower threshold) ───
    # Used only when Pipeline 1 returned nothing — noisier, kept for
    # images where MediaPipe iris landmarks couldn't be detected.
    if not using_p1:
        notes.append("Source: pixel re-scan fallback (Pipeline 1 had no data)")

        eye_y_start = y0 + face_h // 4
        eye_y_end = y0 + face_h // 2
        eye_mid_x = x0 + face_w // 2

        eye_regions = {
            "left": (max(0, x0), max(0, eye_y_start), eye_mid_x, min(img_bgr.shape[0], eye_y_end)),
            "right": (eye_mid_x, max(0, eye_y_start), min(img_bgr.shape[1], x1), min(img_bgr.shape[0], eye_y_end)),
        }

        for eye_label, (ex0, ey0, ex1, ey1) in eye_regions.items():
            if ey1 <= ey0 or ex1 <= ex0:
                continue

            eye_roi = cv2.cvtColor(
                img_bgr[ey0:ey1, ex0:ex1], cv2.COLOR_BGR2GRAY
            )
            if eye_roi.size < 50:
                continue

            p90 = float(np.percentile(eye_roi, 90))
            thresh_val = max(180, int(p90))
            _, bright = cv2.threshold(eye_roi, thresh_val, 255, cv2.THRESH_BINARY)

            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
                bright, connectivity=8
            )

            roi_h, roi_w = eye_roi.shape[:2]
            roi_cx, roi_cy = roi_w / 2.0, roi_h / 2.0

            for label_idx in range(1, num_labels):
                area = stats[label_idx, cv2.CC_STAT_AREA]
                if area < CATCHLIGHT.TOPOLOGY_MIN_AREA:
                    continue

                cx, cy = centroids[label_idx]
                dx = cx - roi_cx
                dy = roi_cy - cy
                angle_rad = _math.atan2(dx, dy)
                clock_deg = _math.degrees(angle_rad) % 360

                bw = stats[label_idx, cv2.CC_STAT_WIDTH]
                bh = stats[label_idx, cv2.CC_STAT_HEIGHT]
                aspect = bw / max(bh, 1)
                # Strip requires ≥ 2.5:1 elongation (aligns with _SHAPE_LABELS).
                # 2:1 catchlights from large rectangular softboxes/panels must not
                # be misclassified as strip boxes.
                if aspect > 2.5 or aspect < 0.4:
                    shape = "strip"
                elif 0.8 <= aspect <= 1.25:
                    shape = "round"
                else:
                    shape = "rectangular"

                eye_area = roi_w * roi_h
                size_ratio = area / max(eye_area * 0.1, 1)

                component_mask = (labels == label_idx)
                bright_vals = eye_roi[component_mask]
                intensity = float(np.mean(bright_vals)) / 255.0 if len(bright_vals) > 0 else 0.0

                all_catchlights.append({
                    "clock_deg": round(clock_deg, 1),
                    "shape": shape,
                    "size_ratio": round(min(0.5, size_ratio), 3),
                    "intensity": round(intensity, 3),
                    "eye": eye_label,
                    "area": int(area),
                })

    raw_count = len(all_catchlights)

    # Sort by intensity (brightest first) then by area
    all_catchlights.sort(key=lambda c: (-c["intensity"], -c["area"]))

    # ── Deduplicate by angular proximity within same eye ──────────
    def _dedup(catchlights: List[Dict], min_angle_sep: float = 20.0) -> List[Dict]:
        kept: List[Dict] = []
        for c in catchlights:
            too_close = False
            for existing in kept:
                if existing["eye"] == c["eye"]:
                    diff = abs(existing["clock_deg"] - c["clock_deg"])
                    diff = min(diff, 360 - diff)
                    if diff < min_angle_sep:
                        too_close = True
                        break
            if not too_close:
                kept.append(c)
        return kept

    deduped = _dedup(all_catchlights)
    catchlight_count = len(deduped)

    # Track raw vs displayed counts and note any merging
    dedup_note: Optional[str] = None
    if raw_count > catchlight_count:
        dedup_note = f"{raw_count} raw → {catchlight_count} after dedup (angular proximity)"
        notes.append(dedup_note)

    # ── Assign primary / secondary / tertiary ─────────────────────
    primary = deduped[0] if len(deduped) >= 1 else None
    secondary = deduped[1] if len(deduped) >= 2 else None
    tertiary = deduped[2] if len(deduped) >= 3 else None

    # ── Cluster geometry ──────────────────────────────────────────
    cluster_geometry = "unknown"
    cluster_spread_deg = 0.0
    inter_catchlight_spacing: List[float] = []

    if catchlight_count == 0:
        cluster_geometry = "none"
    elif catchlight_count == 1:
        cluster_geometry = "single"
    else:
        # Compute angles for all catchlights
        angles = [c["clock_deg"] for c in deduped]

        # Inter-catchlight spacing
        for i in range(len(angles)):
            for j in range(i + 1, len(angles)):
                diff = abs(angles[i] - angles[j])
                diff = min(diff, 360 - diff)
                inter_catchlight_spacing.append(round(diff, 1))

        cluster_spread_deg = max(inter_catchlight_spacing) if inter_catchlight_spacing else 0.0

        if catchlight_count == 2:
            spacing = inter_catchlight_spacing[0] if inter_catchlight_spacing else 0
            if spacing > 150:  # opposite sides
                cluster_geometry = "bilateral"
            else:
                cluster_geometry = "dual"
        elif catchlight_count == 3:
            # Check if triangular: all three spacings roughly equal (classic 120/120/120)
            if len(inter_catchlight_spacing) == 3:
                mean_sp = sum(inter_catchlight_spacing) / 3
                variance = sum((s - mean_sp) ** 2 for s in inter_catchlight_spacing) / 3
                if _math.sqrt(variance) < 50:
                    cluster_geometry = "triangular"
                else:
                    # Check if linear: two spacings small, one large (~sum)
                    sorted_sp = sorted(inter_catchlight_spacing)
                    if sorted_sp[0] + sorted_sp[1] < sorted_sp[2] * 1.3:
                        cluster_geometry = "linear"
                    else:
                        cluster_geometry = "triangular"
            else:
                cluster_geometry = "triangular"
        elif catchlight_count >= 4:
            # Check linearity: sort by angle, check if evenly spaced
            shapes = [c["shape"] for c in deduped]
            strip_count = shapes.count("strip")
            if strip_count >= catchlight_count // 2:
                cluster_geometry = "strip"
            else:
                # Check ring: all spacings roughly equal
                if len(inter_catchlight_spacing) >= 3:
                    mean_sp = sum(inter_catchlight_spacing) / len(inter_catchlight_spacing)
                    variance = sum((s - mean_sp) ** 2 for s in inter_catchlight_spacing) / len(inter_catchlight_spacing)
                    if _math.sqrt(variance) < 30 and cluster_spread_deg > 180:
                        cluster_geometry = "ring"
                    else:
                        cluster_geometry = "linear"
                else:
                    cluster_geometry = "linear"

    # ── Bilateral symmetry (compare left vs right eye positions) ──
    bilateral_symmetry_score = 0.0
    left_angles = sorted([c["clock_deg"] for c in deduped if c["eye"] == "left"])
    right_angles = sorted([c["clock_deg"] for c in deduped if c["eye"] == "right"])

    if left_angles and right_angles and len(left_angles) == len(right_angles):
        # Compare positions: matching catchlights should appear at similar angles
        total_diff = 0.0
        for la, ra in zip(left_angles, right_angles):
            diff = abs(la - ra)
            diff = min(diff, 360 - diff)
            total_diff += diff
        mean_diff = total_diff / len(left_angles)
        # Perfect symmetry = 0° diff, score decays with diff
        bilateral_symmetry_score = max(0.0, 1.0 - mean_diff / 60.0)
    elif left_angles and right_angles:
        # Different counts — partial symmetry at best
        bilateral_symmetry_score = 0.3 * min(len(left_angles), len(right_angles)) / max(len(left_angles), len(right_angles))

    bilateral_symmetry_score = round(bilateral_symmetry_score, 3)

    # ── Confidence ────────────────────────────────────────────────
    confidence = 0.0
    if catchlight_count >= 3:
        confidence = 0.8
    elif catchlight_count == 2:
        confidence = 0.65
    elif catchlight_count == 1:
        confidence = 0.4
    # Boost if bilateral symmetry is high
    if bilateral_symmetry_score > 0.7 and catchlight_count >= 2:
        confidence = min(1.0, confidence + 0.1)

    return {
        "ok": True,
        "catchlight_count": catchlight_count,
        "raw_count": raw_count,
        "displayed_count": catchlight_count,
        "dedup_note": dedup_note,
        "cluster_geometry": cluster_geometry,
        "cluster_spread_deg": round(cluster_spread_deg, 1),
        "inter_catchlight_spacing": inter_catchlight_spacing,
        "bilateral_symmetry_score": bilateral_symmetry_score,
        "primary": primary,
        "secondary": secondary,
        "tertiary": tertiary,
        "confidence": round(confidence, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3c. HIGHLIGHT AXIS MAP PASS
# ═══════════════════════════════════════════════════════════════════════════


def highlight_axis_map_pass(
    img_bgr: np.ndarray,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    highlight_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Per-region facial highlight axis analysis.

    Divides the face into 7 regions (left/right cheek, nose bridge, chin,
    left/right jawline, forehead) and measures the highlight gradient
    direction in each.  Counts distinct axis directions to indicate
    multi-light setups.

    Returns
    -------
    dict
        regions, dominant_axis_deg, axis_count, axis_consistency, wrap_ratio,
        confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    if face_box is None:
        return {
            "ok": True,
            "regions": {},
            "dominant_axis_deg": 0.0,
            "axis_count": 0,
            "axis_consistency": 0.0,
            "wrap_ratio": 0.0,
            "confidence": 0.0,
            "notes": ["No face box — highlight axis map unavailable"],
        }

    x0, y0, x1, y1 = face_box
    face_h = y1 - y0
    face_w = x1 - x0
    if face_h < 30 or face_w < 30:
        return {
            "ok": True,
            "regions": {},
            "dominant_axis_deg": 0.0,
            "axis_count": 0,
            "axis_consistency": 0.0,
            "wrap_ratio": 0.0,
            "confidence": 0.0,
            "notes": ["Face box too small for highlight axis map"],
        }

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # ── Define 7 facial regions ───────────────────────────────────
    mid_x = x0 + face_w // 2
    third_h = face_h // 3
    quarter_h = face_h // 4

    regions_def = {
        "forehead": (x0, y0, x1, y0 + quarter_h),
        "left_cheek": (x0, y0 + quarter_h, mid_x, y0 + 2 * third_h),
        "right_cheek": (mid_x, y0 + quarter_h, x1, y0 + 2 * third_h),
        "nose_bridge": (mid_x - face_w // 6, y0 + quarter_h, mid_x + face_w // 6, y0 + 2 * third_h),
        "jawline_left": (x0, y0 + 2 * third_h, mid_x, y1),
        "jawline_right": (mid_x, y0 + 2 * third_h, x1, y1),
        "chin": (mid_x - face_w // 4, y0 + 2 * third_h, mid_x + face_w // 4, y1),
    }

    region_results: Dict[str, Dict[str, Any]] = {}
    all_axes: List[float] = []
    total_face_area = face_h * face_w
    highlighted_area = 0

    for name, (rx0, ry0, rx1, ry1) in regions_def.items():
        rx0 = max(0, rx0)
        ry0 = max(0, ry0)
        rx1 = min(gray.shape[1], rx1)
        ry1 = min(gray.shape[0], ry1)
        if ry1 <= ry0 or rx1 <= rx0:
            continue

        roi = gray[ry0:ry1, rx0:rx1].astype(np.float32)
        if roi.size < 50:
            continue

        mean_intensity = float(np.mean(roi)) / 255.0

        # Compute gradient to find highlight direction
        grad_x = cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3)

        # Mean gradient direction (weighted by magnitude)
        mag = np.sqrt(grad_x ** 2 + grad_y ** 2)
        mask = mag > np.percentile(mag, 75)

        if np.sum(mask) < 10:
            continue

        mean_gx = float(np.mean(grad_x[mask]))
        mean_gy = float(np.mean(grad_y[mask]))

        axis_deg = math.degrees(math.atan2(mean_gy, mean_gx))
        width_ratio = float(np.sum(roi > np.percentile(roi, 70))) / roi.size

        region_results[name] = {
            "axis_deg": round(axis_deg, 1),
            "width_ratio": round(width_ratio, 3),
            "intensity": round(mean_intensity, 3),
        }
        all_axes.append(axis_deg)

        # Track highlighted area
        highlight_threshold = np.percentile(roi, 70)
        highlighted_area += int(np.sum(roi > highlight_threshold))

    # ── Count distinct axes (>15° apart) ──────────────────────────
    if all_axes:
        clusters: List[List[float]] = []
        for ax in sorted(all_axes):
            placed = False
            for cluster in clusters:
                mean_c = sum(cluster) / len(cluster)
                diff = abs(ax - mean_c)
                diff = min(diff, 360 - diff)
                if diff < 15:
                    cluster.append(ax)
                    placed = True
                    break
            if not placed:
                clusters.append([ax])
        axis_count = len(clusters)

        # Dominant axis = cluster with most members
        biggest_cluster = max(clusters, key=len)
        dominant_axis_deg = sum(biggest_cluster) / len(biggest_cluster)

        # Axis consistency: how many regions agree with dominant
        axis_consistency = len(biggest_cluster) / len(all_axes) if all_axes else 0.0
    else:
        axis_count = 0
        dominant_axis_deg = 0.0
        axis_consistency = 0.0

    # Wrap ratio
    wrap_ratio = min(1.0, highlighted_area / max(total_face_area, 1))

    # Confidence
    confidence = min(0.9, 0.2 + 0.1 * len(region_results))

    return {
        "ok": True,
        "regions": region_results,
        "dominant_axis_deg": round(dominant_axis_deg, 1),
        "axis_count": axis_count,
        "axis_consistency": round(axis_consistency, 3),
        "wrap_ratio": round(wrap_ratio, 3),
        "confidence": round(confidence, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3d. HIGHLIGHT SYMMETRY PASS
# ═══════════════════════════════════════════════════════════════════════════


def highlight_symmetry_pass(
    img_bgr: np.ndarray,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    highlight_data: Optional[Dict[str, Any]] = None,
    highlight_axis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Bilateral highlight symmetry analysis.

    Splits the face vertically at the midline and compares mean highlight
    intensity on each side.  Detects fill presence and computes
    underfill in EV stops.

    Returns
    -------
    dict
        left_intensity, right_intensity, symmetry_score, dominant_side,
        intensity_ratio, fill_detected, fill_side, underfill_ev,
        confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    if face_box is None:
        return {
            "ok": True,
            "left_intensity": 0.0,
            "right_intensity": 0.0,
            "symmetry_score": 0.0,
            "dominant_side": "unknown",
            "intensity_ratio": 1.0,
            "fill_detected": False,
            "fill_side": None,
            "underfill_ev": None,
            "confidence": 0.0,
            "notes": ["No face box — highlight symmetry unavailable"],
        }

    x0, y0, x1, y1 = face_box
    face_h = y1 - y0
    face_w = x1 - x0
    if face_h < 20 or face_w < 20:
        return {
            "ok": True,
            "left_intensity": 0.0,
            "right_intensity": 0.0,
            "symmetry_score": 0.0,
            "dominant_side": "unknown",
            "intensity_ratio": 1.0,
            "fill_detected": False,
            "fill_side": None,
            "underfill_ev": None,
            "confidence": 0.0,
            "notes": ["Face box too small for symmetry analysis"],
        }

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    mid_x = x0 + face_w // 2

    # Extract left and right halves
    left_roi = gray[max(0, y0):min(gray.shape[0], y1), max(0, x0):mid_x]
    right_roi = gray[max(0, y0):min(gray.shape[0], y1), mid_x:min(gray.shape[1], x1)]

    if left_roi.size < 50 or right_roi.size < 50:
        return {
            "ok": True,
            "left_intensity": 0.0,
            "right_intensity": 0.0,
            "symmetry_score": 0.0,
            "dominant_side": "unknown",
            "intensity_ratio": 1.0,
            "fill_detected": False,
            "fill_side": None,
            "underfill_ev": None,
            "confidence": 0.0,
            "notes": ["Insufficient face area for symmetry analysis"],
        }

    left_intensity = float(np.mean(left_roi)) / 255.0
    right_intensity = float(np.mean(right_roi)) / 255.0

    # Symmetry score: 1.0 when perfectly even, 0.0 when maximally different
    max_intensity = max(left_intensity, right_intensity)
    min_intensity = min(left_intensity, right_intensity)

    if max_intensity > 0:
        symmetry_score = min_intensity / max_intensity
    else:
        symmetry_score = 1.0

    # Dominant side
    if abs(left_intensity - right_intensity) < 0.02:
        dominant_side = "center"
    elif left_intensity > right_intensity:
        dominant_side = "left"
    else:
        dominant_side = "right"

    # Intensity ratio
    if min_intensity > 0:
        intensity_ratio = max_intensity / min_intensity
    else:
        intensity_ratio = float("inf") if max_intensity > 0 else 1.0

    # Fill detection: if non-dominant side > 30% of dominant → fill present
    fill_detected = False
    fill_side = None
    underfill_ev = None

    if max_intensity > 0 and min_intensity > 0:
        fill_ratio = min_intensity / max_intensity
        fill_detected = fill_ratio > 0.30
        if dominant_side == "left":
            fill_side = "right"
        elif dominant_side == "right":
            fill_side = "left"

        # Underfill in EV stops: log2(brighter / dimmer)
        underfill_ev = round(math.log2(max(intensity_ratio, 1.0)), 2)
    elif max_intensity > 0:
        underfill_ev = 4.0  # very high underfill
        fill_detected = False

    # Confidence
    confidence = 0.7 if face_w > 60 else 0.4

    return {
        "ok": True,
        "left_intensity": round(left_intensity, 3),
        "right_intensity": round(right_intensity, 3),
        "symmetry_score": round(symmetry_score, 3),
        "dominant_side": dominant_side,
        "intensity_ratio": round(min(10.0, intensity_ratio), 3),
        "fill_detected": fill_detected,
        "fill_side": fill_side,
        "underfill_ev": underfill_ev,
        "confidence": round(confidence, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3e. CONTINUOUS SOURCE HEURISTIC PASS
# ═══════════════════════════════════════════════════════════════════════════


def continuous_source_heuristic_pass(
    img_bgr: np.ndarray,
    catchlight_data: Optional[Dict[str, Any]] = None,
    catchlight_topology_data: Optional[Dict[str, Any]] = None,
    highlight_data: Optional[Dict[str, Any]] = None,
    color_temp_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Heuristics for continuous vs strobe light technology detection.

    Combines catchlight shape analysis, specular edge characteristics,
    and color temperature consistency to infer source technology.

    Returns
    -------
    dict
        likely_technology, technology_confidence, evidence,
        specular_edge_sharpness, color_temp_consistency,
        confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    notes: List[str] = []
    evidence: List[str] = []
    scores: Dict[str, float] = {
        "continuous_led": 0.0,
        "continuous_panel": 0.0,
        "continuous_tube": 0.0,
        "strobe": 0.0,
        "flash": 0.0,
    }

    # ── Catchlight shape analysis ─────────────────────────────────
    catchlight_shape = "unknown"
    if catchlight_data and isinstance(catchlight_data, dict):
        catchlight_shape = catchlight_data.get("catchlight_shape", "unknown")

    if catchlight_shape == "strip":
        scores["continuous_tube"] += 2.0
        evidence.append("strip_catchlight → continuous tube likely")
    elif catchlight_shape == "rectangular":
        scores["continuous_panel"] += 1.5
        scores["strobe"] += 0.5
        evidence.append("rectangular_catchlight → panel or softbox")
    elif catchlight_shape == "round":
        scores["strobe"] += 1.0
        scores["continuous_led"] += 0.5
        evidence.append("round_catchlight → beauty dish or fresnel")

    # ── Topology analysis ─────────────────────────────────────────
    if catchlight_topology_data and isinstance(catchlight_topology_data, dict):
        cluster_geo = catchlight_topology_data.get("cluster_geometry", "unknown")
        if cluster_geo in ("strip", "linear"):
            scores["continuous_tube"] += 1.5
            scores["continuous_panel"] += 1.0
            evidence.append(f"cluster_geometry={cluster_geo} → continuous source likely")
        elif cluster_geo == "triangular":
            scores["continuous_panel"] += 2.0
            evidence.append("triangular_cluster → multi-panel continuous (Hurley-type)")

    # ── Specular edge sharpness ───────────────────────────────────
    specular_edge_sharpness = 0.5  # default mid
    if highlight_data and isinstance(highlight_data, dict):
        specularity = highlight_data.get("highlight_specularity", 0.5)
        edge_gradient = highlight_data.get("highlight_edge_gradient", 0.5)

        if specularity > 0.7:
            specular_edge_sharpness = specularity
            scores["strobe"] += 1.5
            evidence.append(f"high_specularity ({specularity:.2f}) → strobe/flash likely")
        elif specularity < 0.3:
            specular_edge_sharpness = specularity
            scores["continuous_led"] += 1.0
            scores["continuous_panel"] += 1.0
            evidence.append(f"low_specularity ({specularity:.2f}) → continuous source likely")

    # ── Color temperature consistency ─────────────────────────────
    color_temp_consistency = 0.5
    if color_temp_data and isinstance(color_temp_data, dict):
        if color_temp_data.get("ok"):
            variation = color_temp_data.get("cct_variation", 0)
            if isinstance(variation, (int, float)):
                if variation < 200:
                    color_temp_consistency = 0.9
                    scores["continuous_led"] += 1.0
                    evidence.append("low_cct_variation → consistent source (continuous)")
                elif variation > 800:
                    color_temp_consistency = 0.3
                    scores["strobe"] += 0.5
                    evidence.append("high_cct_variation → mixed sources")

    # ── Determine most likely technology ──────────────────────────
    if sum(scores.values()) == 0:
        likely_technology = "unknown"
        technology_confidence = 0.0
    else:
        likely_technology = max(scores, key=scores.get)  # type: ignore[arg-type]
        total_score = sum(scores.values())
        technology_confidence = round(scores[likely_technology] / total_score, 3) if total_score > 0 else 0.0

    confidence = min(0.9, technology_confidence * 0.8 + 0.1 * len(evidence))

    return {
        "ok": True,
        "likely_technology": likely_technology,
        "technology_confidence": round(technology_confidence, 3),
        "evidence": evidence,
        "specular_edge_sharpness": round(specular_edge_sharpness, 3),
        "color_temp_consistency": round(color_temp_consistency, 3),
        "confidence": round(confidence, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3b. BOUNCE CONTRIBUTOR PASS
# ═══════════════════════════════════════════════════════════════════════════


def bounce_contributor_pass(
    img_bgr: np.ndarray,
    shadow_data: Optional[Dict[str, Any]] = None,
    highlight_data: Optional[Dict[str, Any]] = None,
    bounce_data: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Classify bounce/reflector/fill contributors from shadow-side illumination.

    Analyzes brightness and color temperature on the shadow side of the face
    to detect reflectors (gold, silver, white), v-flats, or fill lights.

    Returns
    -------
    dict
        contributors, primary_fill_type, fill_to_key_ratio,
        total_bounce_contribution, confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    notes: List[str] = []
    contributors: List[Dict[str, Any]] = []
    primary_fill_type = "unknown"
    fill_to_key_ratio = 0.0
    total_bounce_contribution = 0.0

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # ── Determine analysis region ─────────────────────────────────
    if face_box is not None:
        fx, fy, fw, fh = face_box
        fx = max(0, fx)
        fy = max(0, fy)
        fw = min(fw, w - fx)
        fh = min(fh, h - fy)
        face_roi = gray[fy:fy + fh, fx:fx + fw]
        color_roi = img_bgr[fy:fy + fh, fx:fx + fw]
    elif person_mask is not None and person_mask.any():
        face_roi = gray.copy()
        face_roi[~person_mask] = 0
        color_roi = img_bgr.copy()
        color_roi[~person_mask] = 0
    else:
        notes.append("no face_box or person_mask — using full image center")
        cy, cx = h // 2, w // 2
        rh, rw = h // 3, w // 3
        face_roi = gray[cy - rh:cy + rh, cx - rw:cx + rw]
        color_roi = img_bgr[cy - rh:cy + rh, cx - rw:cx + rw]

    if face_roi.size < 100:
        notes.append("region too small for analysis")
        return {
            "ok": True,
            "contributors": contributors,
            "primary_fill_type": primary_fill_type,
            "fill_to_key_ratio": fill_to_key_ratio,
            "total_bounce_contribution": total_bounce_contribution,
            "confidence": 0.0,
            "notes": notes,
        }

    roi_h, roi_w = face_roi.shape[:2]
    mid_x = roi_w // 2

    # ── Compute brightness on each side ───────────────────────────
    left_half = face_roi[:, :mid_x]
    right_half = face_roi[:, mid_x:]

    left_mean = float(np.mean(left_half)) if left_half.size > 0 else 0.0
    right_mean = float(np.mean(right_half)) if right_half.size > 0 else 0.0

    key_side_brightness = max(left_mean, right_mean)
    fill_side_brightness = min(left_mean, right_mean)
    shadow_side = "left" if left_mean < right_mean else "right"

    # ── Fill-to-key ratio ────────────────────────────────────────
    if key_side_brightness > 1.0:
        fill_to_key_ratio = round(fill_side_brightness / key_side_brightness, 3)
    else:
        fill_to_key_ratio = 0.0

    # ── Color temperature analysis on shadow side ────────────────
    if shadow_side == "left":
        fill_color = color_roi[:, :mid_x]
    else:
        fill_color = color_roi[:, mid_x:]

    if fill_color.size > 30:
        mean_b = float(np.mean(fill_color[:, :, 0]))
        mean_g = float(np.mean(fill_color[:, :, 1]))
        mean_r = float(np.mean(fill_color[:, :, 2]))

        # Classify fill type by color temperature shift
        warmth = mean_r - mean_b
        if warmth > 20:
            primary_fill_type = "gold_reflector"
            contributors.append({
                "type": "gold_reflector",
                "warmth_delta": round(warmth, 1),
                "side": shadow_side,
            })
            notes.append(f"warm fill on {shadow_side} side (warmth={warmth:.1f}) → gold reflector")
        elif warmth < -10:
            primary_fill_type = "silver_reflector"
            contributors.append({
                "type": "silver_reflector",
                "warmth_delta": round(warmth, 1),
                "side": shadow_side,
            })
            notes.append(f"cool fill on {shadow_side} side → silver reflector")
        elif fill_to_key_ratio > 0.5:
            primary_fill_type = "white_reflector"
            contributors.append({
                "type": "white_reflector",
                "warmth_delta": round(warmth, 1),
                "side": shadow_side,
            })
            notes.append(f"neutral fill with good ratio ({fill_to_key_ratio:.2f}) → white reflector/foam")
        elif fill_to_key_ratio < 0.2:
            # Very dark shadow side suggests negative fill (v-flat)
            primary_fill_type = "negative_fill"
            contributors.append({
                "type": "v_flat",
                "fill_ratio": fill_to_key_ratio,
                "side": shadow_side,
            })
            notes.append(f"very low fill ratio ({fill_to_key_ratio:.2f}) → possible v-flat/negative fill")
        else:
            primary_fill_type = "ambient"
            notes.append("moderate fill without strong color shift → ambient fill")

    # ── Total bounce contribution ────────────────────────────────
    total_bounce_contribution = round(fill_to_key_ratio * 0.8, 3)

    # ── Use existing bounce_data if available ────────────────────
    if bounce_data and isinstance(bounce_data, dict) and bounce_data.get("ok"):
        bounce_intensity = bounce_data.get("bounce_intensity", 0.0)
        if isinstance(bounce_intensity, (int, float)) and bounce_intensity > 0:
            total_bounce_contribution = round(
                max(total_bounce_contribution, bounce_intensity), 3
            )
            notes.append(f"bounce_geometry confirms contribution={bounce_intensity:.3f}")

    # ── Confidence ───────────────────────────────────────────────
    confidence = 0.3
    if face_box is not None:
        confidence += 0.2
    if fill_to_key_ratio > 0.1:
        confidence += 0.2
    if len(contributors) > 0:
        confidence += 0.1
    confidence = round(min(0.9, confidence), 3)

    return {
        "ok": True,
        "contributors": contributors,
        "primary_fill_type": primary_fill_type,
        "fill_to_key_ratio": round(fill_to_key_ratio, 3),
        "total_bounce_contribution": total_bounce_contribution,
        "confidence": confidence,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3c. SEPARATION LIGHT PASS
# ═══════════════════════════════════════════════════════════════════════════


def separation_light_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    edge_highlights: Optional[Dict[str, Any]] = None,
    background_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Detect hair light, rim light, and background spill differentiation.

    Hair light: bright edges concentrated on the top third of the head.
    Rim light: bright edges along the sides.
    Background spill: edge brightness that correlates with background brightness.

    Returns
    -------
    dict
        has_hair_light, hair_light_direction_deg, hair_light_intensity,
        hair_light_width_ratio, has_rim_light, rim_side,
        has_background_spill, spill_vs_intentional_confidence,
        confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    notes: List[str] = []
    has_hair_light = False
    hair_light_direction_deg: Optional[float] = None
    hair_light_intensity = 0.0
    hair_light_width_ratio = 0.0
    has_rim_light = False
    rim_side: Optional[str] = None
    has_background_spill = False
    spill_vs_intentional_confidence = 0.5

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # ── Use edge_highlights data if provided ─────────────────────
    if edge_highlights and isinstance(edge_highlights, dict):
        if edge_highlights.get("has_rim"):
            has_rim_light = True
            rim_side = edge_highlights.get("rim_side")
            notes.append(f"rim light detected from edge_highlights on {rim_side} side")

    # ── Determine head region for hair light detection ───────────
    if face_box is not None:
        fx, fy, fw, fh = face_box
        # Hair region: above the face box and slightly wider
        hair_top = max(0, fy - fh // 2)
        hair_bottom = fy + fh // 6  # top sixth of face
        hair_left = max(0, fx - fw // 4)
        hair_right = min(w, fx + fw + fw // 4)

        hair_region = gray[hair_top:hair_bottom, hair_left:hair_right]

        # Side regions for rim detection
        side_top = fy
        side_bottom = fy + fh
        left_strip_l = max(0, fx - fw // 4)
        left_strip_r = fx + fw // 8
        right_strip_l = fx + fw - fw // 8
        right_strip_r = min(w, fx + fw + fw // 4)

        left_strip = gray[side_top:side_bottom, left_strip_l:left_strip_r]
        right_strip = gray[side_top:side_bottom, right_strip_l:right_strip_r]
        face_interior = gray[fy:fy + fh, fx + fw // 4:fx + 3 * fw // 4]
    elif person_mask is not None and person_mask.any():
        # Approximate head region from top portion of person mask
        rows = np.where(person_mask.any(axis=1))[0]
        if len(rows) < 10:
            return {
                "ok": True, "has_hair_light": False,
                "hair_light_direction_deg": None,
                "hair_light_intensity": 0.0, "hair_light_width_ratio": 0.0,
                "has_rim_light": has_rim_light, "rim_side": rim_side,
                "has_background_spill": False,
                "spill_vs_intentional_confidence": 0.5,
                "confidence": 0.2, "notes": notes,
            }
        top_row = rows[0]
        person_h = rows[-1] - top_row
        hair_bottom = top_row + person_h // 6
        hair_region = gray[top_row:hair_bottom]
        left_strip = gray[top_row:top_row + person_h, :w // 4]
        right_strip = gray[top_row:top_row + person_h, 3 * w // 4:]
        face_interior = gray[top_row:top_row + person_h, w // 4:3 * w // 4]
    else:
        notes.append("no face_box or person_mask — limited separation light analysis")
        return {
            "ok": True, "has_hair_light": False,
            "hair_light_direction_deg": None,
            "hair_light_intensity": 0.0, "hair_light_width_ratio": 0.0,
            "has_rim_light": has_rim_light, "rim_side": rim_side,
            "has_background_spill": False,
            "spill_vs_intentional_confidence": 0.5,
            "confidence": 0.1, "notes": notes,
        }

    # ── Hair light detection ─────────────────────────────────────
    if hair_region.size > 50:
        hair_mean = float(np.mean(hair_region))
        interior_mean = float(np.mean(face_interior)) if face_interior.size > 50 else 128.0

        # Hair light = bright relative to face interior
        if interior_mean > 1.0:
            hair_ratio = hair_mean / interior_mean
        else:
            hair_ratio = 0.0

        if hair_ratio > 1.15:
            has_hair_light = True
            hair_light_intensity = round(min(1.0, (hair_ratio - 1.0) * 2.0), 3)

            # Direction: compare left vs right halves of hair region
            hair_mid = hair_region.shape[1] // 2
            if hair_mid > 0 and hair_region.shape[1] > hair_mid:
                hair_left_mean = float(np.mean(hair_region[:, :hair_mid]))
                hair_right_mean = float(np.mean(hair_region[:, hair_mid:]))
                if hair_left_mean > hair_right_mean * 1.1:
                    hair_light_direction_deg = -30.0  # from left
                elif hair_right_mean > hair_left_mean * 1.1:
                    hair_light_direction_deg = 30.0  # from right
                else:
                    hair_light_direction_deg = 0.0  # from above center

            # Width ratio: how much of the top is bright
            bright_threshold = interior_mean * 1.1
            bright_pixels = np.sum(hair_region > bright_threshold)
            total_pixels = hair_region.size
            hair_light_width_ratio = round(bright_pixels / max(1, total_pixels), 3)

            notes.append(
                f"hair light detected: intensity={hair_light_intensity:.2f}, "
                f"width_ratio={hair_light_width_ratio:.2f}"
            )

    # ── Rim light detection (from face strips if not already found) ──
    if not has_rim_light and face_interior.size > 50:
        interior_mean = float(np.mean(face_interior))
        left_mean = float(np.mean(left_strip)) if left_strip.size > 20 else 0.0
        right_mean = float(np.mean(right_strip)) if right_strip.size > 20 else 0.0

        rim_threshold = interior_mean * 1.2
        if left_mean > rim_threshold and left_mean > right_mean:
            has_rim_light = True
            rim_side = "left"
            notes.append(f"rim light on left: edge={left_mean:.0f} vs interior={interior_mean:.0f}")
        elif right_mean > rim_threshold and right_mean > left_mean:
            has_rim_light = True
            rim_side = "right"
            notes.append(f"rim light on right: edge={right_mean:.0f} vs interior={interior_mean:.0f}")

    # ── Background spill detection ───────────────────────────────
    bg_brightness = 128.0
    if background_data and isinstance(background_data, dict) and background_data.get("ok"):
        bg_brightness = background_data.get("mean_brightness", 128.0)
        if not isinstance(bg_brightness, (int, float)):
            bg_brightness = 128.0

    # If edge brightness correlates with background brightness, it's spill
    if has_rim_light or has_hair_light:
        edge_brightness = hair_light_intensity * 255 if has_hair_light else 0.0
        if bg_brightness > 180:
            # Bright background → likely spill
            has_background_spill = True
            spill_vs_intentional_confidence = round(
                max(0.1, 0.5 - (bg_brightness - 180) / 150.0), 3
            )
            notes.append(
                f"bright background ({bg_brightness:.0f}) → possible spill, "
                f"intentional_confidence={spill_vs_intentional_confidence:.2f}"
            )
        else:
            # Dark background → intentional separation light
            spill_vs_intentional_confidence = round(
                min(0.95, 0.5 + (180 - bg_brightness) / 360.0), 3
            )

    # ── Confidence ───────────────────────────────────────────────
    confidence = 0.3
    if face_box is not None:
        confidence += 0.15
    if has_hair_light:
        confidence += 0.15
    if has_rim_light:
        confidence += 0.15
    if edge_highlights:
        confidence += 0.1
    confidence = round(min(0.9, confidence), 3)

    return {
        "ok": True,
        "has_hair_light": has_hair_light,
        "hair_light_direction_deg": hair_light_direction_deg,
        "hair_light_intensity": round(hair_light_intensity, 3),
        "hair_light_width_ratio": round(hair_light_width_ratio, 3),
        "has_rim_light": has_rim_light,
        "rim_side": rim_side,
        "has_background_spill": has_background_spill,
        "spill_vs_intentional_confidence": round(spill_vs_intentional_confidence, 3),
        "confidence": confidence,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3d. OFF-AXIS KEY PASS
# ═══════════════════════════════════════════════════════════════════════════


def off_axis_key_pass(
    img_bgr: np.ndarray,
    shadow_data: Optional[Dict[str, Any]] = None,
    highlight_data: Optional[Dict[str, Any]] = None,
    highlight_axis_data: Optional[Dict[str, Any]] = None,
    catchlight_data: Optional[Dict[str, Any]] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Compute continuous key light azimuth with off-axis detection.

    Weighted average of available signals:
    - shadow_vector_deg (inverted for key direction)
    - highlight_axis_deg from highlight_axis_map
    - catchlight position (converted to azimuth)

    Off-axis flag: |azimuth| between 15 and 30 degrees from center.

    Returns
    -------
    dict
        key_azimuth_deg, key_elevation_deg, is_off_axis,
        off_axis_angle_deg, detection_method, confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    notes: List[str] = []
    azimuths: List[Tuple[float, float]] = []  # (azimuth_deg, weight)
    methods: List[str] = []

    # ── Shadow vector (inverted = key direction) ──────────────────
    if shadow_data and isinstance(shadow_data, dict) and shadow_data.get("ok"):
        shadow_vec = shadow_data.get("shadow_vector_deg")
        if isinstance(shadow_vec, (int, float)):
            # shadow_vector_deg is now in VLM convention (0=down=butterfly baseline).
            # Key direction is opposite to shadow direction.  Since we added +180° to
            # output convention, the inversion simplifies: key = shadow_vec (not +180).
            key_from_shadow = float(shadow_vec) % 360.0
            # Normalize to -180..+180 range (0=front, negative=left, positive=right)
            if key_from_shadow > 180:
                key_from_shadow -= 360
            azimuths.append((key_from_shadow, 1.5))
            methods.append("shadow_vector")
            notes.append(f"shadow_vector_deg={shadow_vec:.1f} → key azimuth={key_from_shadow:.1f}")

    # ── Highlight axis deg ───────────────────────────────────────
    if highlight_axis_data and isinstance(highlight_axis_data, dict) and highlight_axis_data.get("ok"):
        axis_deg = highlight_axis_data.get("dominant_axis_deg")
        if isinstance(axis_deg, (int, float)):
            # Highlight axis roughly indicates key direction
            h_azimuth = float(axis_deg)
            if h_azimuth > 180:
                h_azimuth -= 360
            azimuths.append((h_azimuth, 1.0))
            methods.append("highlight_axis")
            notes.append(f"highlight_axis_deg={axis_deg:.1f} → azimuth={h_azimuth:.1f}")

    # ── Catchlight position ──────────────────────────────────────
    if catchlight_data and isinstance(catchlight_data, dict) and catchlight_data.get("ok"):
        cl_pos = catchlight_data.get("catchlight_position", "")
        if isinstance(cl_pos, str) and cl_pos:
            # Map clock position to approximate azimuth
            clock_to_azimuth = {
                "upper_left": -45.0, "upper_right": 45.0,
                "left": -90.0, "right": 90.0,
                "lower_left": -135.0, "lower_right": 135.0,
                "top": 0.0, "bottom": 180.0,
                "10_oclock": -60.0, "2_oclock": 60.0,
                "11_oclock": -30.0, "1_oclock": 30.0,
                "9_oclock": -90.0, "3_oclock": 90.0,
            }
            if cl_pos in clock_to_azimuth:
                cl_azimuth = clock_to_azimuth[cl_pos]
                azimuths.append((cl_azimuth, 1.2))
                methods.append("catchlight_position")
                notes.append(f"catchlight_position={cl_pos} → azimuth={cl_azimuth:.1f}")

    # ── Weighted average ─────────────────────────────────────────
    if not azimuths:
        # Fallback: analyze image brightness distribution
        h_img, w_img = img_bgr.shape[:2]
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        if face_box is not None:
            fx, fy, fw, fh = face_box
            roi = gray[max(0, fy):min(h_img, fy + fh), max(0, fx):min(w_img, fx + fw)]
        else:
            roi = gray

        if roi.size > 100:
            mid_x = roi.shape[1] // 2
            left_mean = float(np.mean(roi[:, :mid_x]))
            right_mean = float(np.mean(roi[:, mid_x:]))
            if left_mean > right_mean * 1.05:
                azimuths.append((-30.0, 0.5))
                methods.append("brightness_fallback")
            elif right_mean > left_mean * 1.05:
                azimuths.append((30.0, 0.5))
                methods.append("brightness_fallback")
            else:
                azimuths.append((0.0, 0.3))
                methods.append("brightness_fallback")

    if azimuths:
        total_weight = sum(wt for _, wt in azimuths)
        key_azimuth_deg = round(
            sum(az * wt for az, wt in azimuths) / max(total_weight, 0.001), 1
        )
    else:
        key_azimuth_deg = 0.0

    # ── Off-axis detection ───────────────────────────────────────
    abs_azimuth = abs(key_azimuth_deg)
    is_off_axis = 15.0 <= abs_azimuth <= 30.0
    off_axis_angle_deg = round(abs_azimuth, 1) if is_off_axis else 0.0

    if is_off_axis:
        notes.append(f"off-axis key detected at {key_azimuth_deg:.1f}° (15-30° range)")

    # ── Elevation estimate (basic) ───────────────────────────────
    key_elevation_deg = 45.0  # default mid-high
    if shadow_data and isinstance(shadow_data, dict):
        shadow_length = shadow_data.get("shadow_length_ratio")
        if isinstance(shadow_length, (int, float)):
            if shadow_length > 0.8:
                key_elevation_deg = 25.0  # low light → long shadows
            elif shadow_length < 0.3:
                key_elevation_deg = 65.0  # high light → short shadows

    detection_method = "+".join(methods) if methods else "none"

    # ── Confidence ───────────────────────────────────────────────
    confidence = round(min(0.9, 0.15 * len(methods) + 0.1), 3)

    return {
        "ok": True,
        "key_azimuth_deg": round(key_azimuth_deg, 1),
        "key_elevation_deg": round(key_elevation_deg, 1),
        "is_off_axis": is_off_axis,
        "off_axis_angle_deg": round(off_axis_angle_deg, 1),
        "detection_method": detection_method,
        "confidence": confidence,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3e. LIGHT STRUCTURE PASS
# ═══════════════════════════════════════════════════════════════════════════


def light_structure_pass(
    img_bgr: np.ndarray,
    shadow_data: Optional[Dict[str, Any]] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    highlight_symmetry_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Detect triangle lighting, loop, Rembrandt, butterfly, split structure.

    Analyzes the nose shadow region of the face to classify the lighting
    pattern based on shadow shape and position.

    Returns
    -------
    dict
        nose_shadow_shape, nose_shadow_length_ratio, nose_shadow_angle_deg,
        triangle_detected, triangle_cheek, triangle_completeness,
        pattern_name, confidence, notes, ok.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    notes: List[str] = []
    nose_shadow_shape = "unknown"
    nose_shadow_length_ratio = 0.0
    nose_shadow_angle_deg = 0.0
    triangle_detected = False
    triangle_cheek: Optional[str] = None
    triangle_completeness = 0.0
    _triangle_isolation = 0.0
    pattern_name = "unknown"

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    #: True when no real face box was supplied and we fell back to a center crop.
    #: Kept as an explicit flag rather than a note, because a note is prose and
    #: nothing downstream reads prose as a confidence signal.
    face_box_estimated = False

    if face_box is None:
        # Estimate face region from person segmentation or image center.
        # Many dark-skin portrait images fail face detection due to MediaPipe
        # model limitations.  Use a conservative center crop (20-80% of image)
        # as the face ROI so shadow analysis can still run — abandoning those
        # subjects is not an option.
        h_img, w_img = img_bgr.shape[:2]
        face_box = (
            int(w_img * 0.15), int(h_img * 0.08),
            int(w_img * 0.85), int(h_img * 0.80),
        )
        face_box_estimated = True
        notes.append("face_box estimated from image center crop (face detector failed)")

    # face_box is (x0, y0, x1, y1) — two corner coordinates, not (x, y, w, h).
    # Every other pass in this file unpacks as x0, y0, x1, y1.  Convert to
    # width/height here so the remainder of the function is unchanged.
    _bx0, _by0, _bx1, _by1 = face_box
    _bx0 = max(0, _bx0)
    _by0 = max(0, _by0)
    _bx1 = min(_bx1, w)
    _by1 = min(_by1, h)
    fx, fy = _bx0, _by0
    fw = _bx1 - _bx0
    fh = _by1 - _by0

    if fw < 20 or fh < 20:
        notes.append("face box too small")
        return {
            "ok": True,
            "nose_shadow_shape": nose_shadow_shape,
            "nose_shadow_length_ratio": nose_shadow_length_ratio,
            "nose_shadow_angle_deg": nose_shadow_angle_deg,
            "triangle_detected": False,
            "triangle_cheek": None,
            "triangle_completeness": 0.0,
            "pattern_name": pattern_name,
            "confidence": 0.1,
            "notes": notes,
        }

    face_roi = gray[fy:fy + fh, fx:fx + fw]
    face_mean = float(np.mean(face_roi))

    # ── Nose region: center-bottom third of face ─────────────────
    nose_top = fh // 3
    nose_bottom = 2 * fh // 3
    nose_left = fw // 3
    nose_right = 2 * fw // 3
    nose_region = face_roi[nose_top:nose_bottom, nose_left:nose_right]

    if nose_region.size < 50:
        notes.append("nose region too small")
        return {
            "ok": True,
            "nose_shadow_shape": nose_shadow_shape,
            "nose_shadow_length_ratio": nose_shadow_length_ratio,
            "nose_shadow_angle_deg": nose_shadow_angle_deg,
            "triangle_detected": False,
            "triangle_cheek": None,
            "triangle_completeness": 0.0,
            "pattern_name": pattern_name,
            "confidence": 0.15,
            "notes": notes,
        }

    # ── Shadow detection in nose region ──────────────────────────
    # Skin-tone adaptive threshold: darker skin has a compressed tonal range,
    # so shadow pixels are only slightly darker than the face mean.  A fixed
    # 0.70 ratio classifies too much as "lit" on dark skin (face_mean ~90-110).
    # Boost the ratio for darker faces so shadow pixels near 75-80 luma are
    # captured correctly.  Capped at 0.82 to avoid false positives on very
    # dark backlit faces where noise approaches face_mean.
    # face_mean ~180 (light skin)  → ratio ≈ 0.70  → threshold ≈ 126
    # face_mean ~130 (medium skin) → ratio ≈ 0.70  → threshold ≈  91
    # face_mean ~100 (dark skin)   → ratio ≈ 0.775 → threshold ≈  78
    _shadow_ratio_base = 0.70 + max(0.0, (130.0 - face_mean) / 400.0)
    _shadow_ratio_base = min(_shadow_ratio_base, 0.82)
    shadow_threshold = face_mean * _shadow_ratio_base
    shadow_mask = (nose_region < shadow_threshold).astype(np.uint8)
    shadow_ratio = float(np.mean(shadow_mask))

    # ── Analyze shadow position and shape ────────────────────────
    nr_h, nr_w = nose_region.shape
    mid_x = nr_w // 2

    left_shadow = float(np.mean(shadow_mask[:, :mid_x]))
    right_shadow = float(np.mean(shadow_mask[:, mid_x:]))

    # ── Skin-tone-aware shadow asymmetry ─────────────────────────
    # On dark skin, the absolute threshold shadow_mask may register
    # very few pixels as "shadow" on either side (the skin itself is
    # near the threshold). Supplement with a RELATIVE brightness
    # comparison: compare left-half mean vs right-half mean of the
    # nose region, normalized by face_mean.  This captures the
    # directional lighting asymmetry regardless of skin tone.
    _left_mean = float(np.mean(nose_region[:, :mid_x]))
    _right_mean = float(np.mean(nose_region[:, mid_x:]))
    _rel_asym = abs(_left_mean - _right_mean) / max(face_mean, 1.0)
    # When threshold-based asymmetry is low but relative brightness
    # asymmetry is strong, use relative to boost the effective
    # left_shadow / right_shadow difference so the Rembrandt branch
    # can trigger.
    if abs(left_shadow - right_shadow) < 0.20 and _rel_asym > 0.08:
        # Remap: relative brightness difference → effective shadow ratio
        # The darker half gets a shadow boost proportional to the asymmetry
        if _left_mean < _right_mean:
            left_shadow = max(left_shadow, min(0.50, _rel_asym * 3.0))
        else:
            right_shadow = max(right_shadow, min(0.50, _rel_asym * 3.0))

    top_shadow = float(np.mean(shadow_mask[:nr_h // 2, :]))
    bottom_shadow = float(np.mean(shadow_mask[nr_h // 2:, :]))

    # ── Nose-specific shadow centroid vector ──────────────────────
    # Instead of relying on shadow_pass's whole-face Sobel gradient,
    # compute the shadow direction directly from the centroid of shadow
    # pixels in the nose region relative to the nose center.  This is
    # more precise for nose shadow angle classification.
    _centroid_angle = 0.0
    _centroid_dist = 0.0
    shadow_ys, shadow_xs = np.where(shadow_mask > 0)
    if len(shadow_xs) > 5:
        _scx = float(np.mean(shadow_xs)) - nr_w / 2.0
        _scy = float(np.mean(shadow_ys)) - nr_h / 2.0
        import math as _math
        _cdist_px = _math.hypot(_scx, _scy)
        _centroid_dist = min(1.0, _cdist_px / max(nr_w, nr_h) * 2.0)
        # Angle: 0=up, 90=right, 180=down, 270=left (clock convention)
        _rad = _math.atan2(_scx, _scy)  # atan2(x, y) because y-down
        _centroid_angle = (_math.degrees(_rad) + 360) % 360

    # ── Nose shadow length ratio (use shadow_data if available) ──
    if shadow_data and isinstance(shadow_data, dict) and shadow_data.get("ok"):
        sl = shadow_data.get("shadow_length_ratio")
        if isinstance(sl, (int, float)):
            nose_shadow_length_ratio = round(float(sl), 3)
        sv = shadow_data.get("shadow_vector_deg")
        if isinstance(sv, (int, float)):
            nose_shadow_angle_deg = round(float(sv), 1)
    else:
        nose_shadow_length_ratio = round(shadow_ratio, 3)

    # Use the nose-centroid angle as the primary angle when it's valid
    # and the shadow_pass angle is likely imprecise (whole-face gradient).
    # The centroid angle directly measures where the nose shadow mass is.
    if _centroid_dist > 0.05 and len(shadow_xs) > 10:
        nose_shadow_angle_deg = round(_centroid_angle, 1)

    # ── Pattern classification ───────────────────────────────────
    symmetry_score = 0.5
    if highlight_symmetry_data and isinstance(highlight_symmetry_data, dict):
        symmetry_score = highlight_symmetry_data.get("symmetry_score", 0.5)
        if not isinstance(symmetry_score, (int, float)):
            symmetry_score = 0.5

    # ── Compute near-vertical angle using centroid when available ──
    # The centroid angle measures where shadow mass sits relative to nose
    # center: 0°=below, 90°=right, 180°=above, 270°=left.
    # Butterfly: shadow falls straight DOWN → centroid near 0°/360°.
    # shadow_pass convention: 0°=up, 180°=down.
    # Convert centroid → shadow_pass convention: add 180°.
    if _centroid_dist > 0.05:
        _centroid_in_sp_convention = (_centroid_angle + 180.0) % 360.0
        _angle_near_vertical = (160 < _centroid_in_sp_convention < 200)
    elif nose_shadow_angle_deg > 0:
        # nose_shadow_angle_deg uses shadow_pass convention (0°=up, 180°=down).
        # "Near vertical" means shadow falls approximately downward (≈180°).
        # But overhead keys produce angles near 0°/360° (shadow falls from
        # above, gradient points UP) as well as near 180° depending on
        # measurement frame.  Check BOTH ranges to catch overhead keys:
        #   - 160-200° = shadow gradient points down (direct measurement)
        #   - 340-360° or 0-20° = shadow gradient points up (overhead key
        #     where atan2 wraps around 0°; nose_shadow_angle 355.8° is a
        #     textbook overhead/butterfly key)
        _nsa = nose_shadow_angle_deg
        _angle_near_vertical = (160 < _nsa < 200) or (_nsa > 340) or (_nsa < 20)
    else:
        # No reliable angle data — do NOT presume vertical.
        # Defaulting True allowed butterfly to fire on dark skin where compressed
        # shadow range produces a small, nearly-symmetric nose shadow with no
        # measurable centroid direction.  Loop and Rembrandt would then be skipped
        # even when the shadow asymmetry clearly points off-axis.
        # Require actual measured evidence of a near-vertical angle for butterfly.
        _angle_near_vertical = False

    # ── Low-abs diagonal: near-zero L/R asymmetry + confirmed diagonal centroid ──
    # A well-filled loop (1:1 fill ratio, ≤0.3 stops down) compresses both
    # shadow_ratio AND L/R asymmetry toward zero.  It also collapses the
    # bottom/top shadow ratio — so the main loop branch (which requires
    # bottom > top * 1.05) fails.  BUT the key is physically at 30–45° off-axis:
    # the shadow centroid stays diagonal regardless of fill strength.
    # When abs < 0.10 AND centroid is reliably diagonal, the geometry is the
    # stronger signal than any ratio heuristic.  Fire loop FIRST, before any
    # symmetric-source branch (clamshell/butterfly) can claim the case.
    # Require shadow_ratio > 0.02 so centroid is measured on real shadow pixels,
    # not noise, and centroid_dist > 0.05 for a reliable directional measurement.
    _face_bright_enough = face_mean > 60
    _low_abs_lra = abs(left_shadow - right_shadow) < 0.10
    _ca_now = _centroid_angle
    _diagonal_centroid = (20 < _ca_now < 80) or (280 < _ca_now < 340)
    if (
        _centroid_dist > 0.05
        and not _angle_near_vertical
        and shadow_ratio > 0.02
        and _low_abs_lra
        and _diagonal_centroid
    ):
        pattern_name = "loop"
        nose_shadow_shape = "short_angled"
        notes.append(
            f"low-abs diagonal loop: L/R asym={abs(left_shadow - right_shadow):.3f} (<0.10), "
            f"centroid={_ca_now:.0f}° (dist={_centroid_dist:.2f}), "
            f"shadow_ratio={shadow_ratio:.3f} — diagonal centroid overrides ratio heuristics"
        )

    # ── Very low shadow: on-axis source (clamshell / flat / beauty) ──
    # When shadow_density is extremely low (< 5%), the nose region has
    # essentially no shadow pixels.  Shadow distribution metrics (left/right,
    # top/bottom) are running on noise.  Minimal shadow = fill is canceling
    # key shadow → clamshell or flat beauty lighting.  Butterfly produces a
    # *visible* nose shadow (the "butterfly wings" shape); when the shadow
    # is truly absent, a fill-from-below (clamshell) or multi-source flat
    # setup is the more likely cause.
    # Guard 1: a nearly-silhouetted face (face_mean < 60) likely means backlighting
    # or rim light, not an on-axis source.  Low shadow_ratio there is noise.
    # Guard 2: clamshell requires an ON-AXIS source → near-vertical shadow direction.
    # Loop with heavy fill (1:1 ratio, 0.3 stops down) collapses shadow_ratio to
    # near-zero AND compresses L/R asymmetry below 0.15 — but the shadow direction
    # remains DIAGONAL (30–45° off-axis).  Requiring _angle_near_vertical prevents
    # clamshell from stealing fill-heavy loop cases.
    elif shadow_ratio < 0.05 and abs(left_shadow - right_shadow) < 0.15 and _face_bright_enough and _angle_near_vertical:
        pattern_name = "clamshell"
        nose_shadow_shape = "minimal_centered"
        notes.append(f"very low shadow density ({shadow_ratio:.3f}) + symmetric + near-vertical → clamshell/flat (fill cancels key shadow)")

    # Butterfly: symmetric shadow under BOTH nostrils AND shadow angle near-vertical.
    # Domain rule (photographer): butterfly = shadow under BOTH nostrils; loop =
    # shadow under ONE nostril.  A scalar L/R asymmetry check alone is not enough —
    # a one-sided loop shadow like left=0.12, right=0.01 has abs diff 0.11 and
    # would falsely pass a < 0.15 threshold.  Require that BOTH halves of the
    # sub-nasal shadow region carry measurable shadow density (min > 0.04) so
    # single-nostril loop cases cannot masquerade as butterfly.
    elif (
        abs(left_shadow - right_shadow) < 0.08
        and min(left_shadow, right_shadow) > 0.04
        and bottom_shadow > top_shadow * 1.3
        and _angle_near_vertical
    ):
        pattern_name = "butterfly"
        nose_shadow_shape = "butterfly_below"
        notes.append(
            f"symmetric shadow under both nostrils "
            f"(L={left_shadow:.3f} R={right_shadow:.3f}) → butterfly pattern"
        )

    # Loop: key at 30–45° off-axis creates a diagonal nose shadow that wraps
    # under ONE nostril (not both).  This produces moderate L/R asymmetry —
    # one side darker — but NOT enough to reach Rembrandt's cheek shadow.
    # The single-nostril comma shadow is the anatomical signature: it is
    # physically impossible from a frontal source (butterfly cannot make it).
    #
    # Threshold: < 0.20 (up to where Rembrandt starts) with a diagonal angle
    # confirms loop.  The prior threshold (< 0.15) was too strict — it excluded
    # the natural single-nostril asymmetry that defines loop.  Bottom-heavy
    # relaxed to > 1.1 (shadow falls below nose at any ratio, not just 1.3×).
    elif abs(left_shadow - right_shadow) < 0.20 and bottom_shadow > top_shadow * 1.05 and not _angle_near_vertical:
        pattern_name = "loop"
        nose_shadow_shape = "short_angled"
        notes.append(
            f"single-nostril nose shadow (L/R asym {abs(left_shadow - right_shadow):.3f}) "
            f"+ diagonal angle ({nose_shadow_angle_deg:.0f}°) → loop pattern"
        )

    # Split: half face in shadow — but check for Rembrandt triangle first.
    # At |L-R| > 0.5, both split and Rembrandt are possible. The triangle
    # check disambiguates.
    elif abs(left_shadow - right_shadow) > 0.5:
        shadow_side = "left" if left_shadow > right_shadow else "right"
        # Quick triangle check using percentile spread
        _sp_ct = int(fh * 0.45); _sp_cb = int(fh * 0.70)
        _sp_jt = int(fh * 0.70); _sp_jb = int(fh * 0.85)
        if shadow_side == "left":
            _sp_cr = face_roi[_sp_ct:_sp_cb, :int(fw * 0.40)]
            _sp_jr = face_roi[_sp_jt:_sp_jb, :int(fw * 0.40)]
        else:
            _sp_cr = face_roi[_sp_ct:_sp_cb, int(fw * 0.60):]
            _sp_jr = face_roi[_sp_jt:_sp_jb, int(fw * 0.60):]
        _sp_has_triangle = False
        if _sp_cr.size > 50 and _sp_jr.size > 20:
            _sp_p75 = float(np.percentile(_sp_cr, 75))
            _sp_p25 = float(np.percentile(_sp_cr, 25))
            _sp_jm = float(np.mean(_sp_jr))
            _sp_spread = (_sp_p75 - _sp_p25) / max(face_mean, 1.0)
            _sp_bvj = (_sp_p75 - _sp_jm) / max(face_mean, 1.0)
            _sp_has_triangle = _sp_spread > 0.15 and _sp_bvj > 0.10
        if _sp_has_triangle:
            # Triangle found in split-range asymmetry → this is Rembrandt
            _triangle_isolation = _sp_spread
            triangle_detected = True
            triangle_cheek = shadow_side
            pattern_name = "rembrandt"
            nose_shadow_shape = "angled_with_triangle"
            notes.append(
                f"split-range asymmetry ({abs(left_shadow-right_shadow):.3f}) "
                f"but triangle present (spread={_sp_spread:.3f}) → rembrandt"
            )
        else:
            pattern_name = "split"
            nose_shadow_shape = "half_face"
            notes.append("strong left/right asymmetry → split lighting")

    # Rembrandt: triangle on shadow-side cheek
    elif abs(left_shadow - right_shadow) > 0.2:
        shadow_side = "left" if left_shadow > right_shadow else "right"

        # ── Shadow connectivity: nose shadow → cheek zone ─────────────
        # A genuine Rembrandt shadow runs continuously from the nose
        # downward to the shadow-side cheek, forming one connected dark
        # zone that the lit triangle interrupts at the lower cheek.
        # Verify that the mid-face strip (face rows 35-65%) on the shadow
        # side is dark (below 90% of face mean), confirming the shadow
        # connects nose shadow to the cheek measurement zone.
        _rem_conn_y0 = int(fh * 0.35)
        _rem_conn_y1 = int(fh * 0.65)
        if shadow_side == "left":
            _rem_conn_region = face_roi[_rem_conn_y0:_rem_conn_y1, :fw // 3]
        else:
            _rem_conn_region = face_roi[_rem_conn_y0:_rem_conn_y1, 2 * fw // 3:]
        _shadow_connected = (
            _rem_conn_region.size > 20
            and float(np.mean(_rem_conn_region)) < face_mean * 0.90
        )

        # ── Shadow strength: shadow side must have real shadow pixels ──
        # Require >= 15% of nose-region shadow-side pixels to be below the
        # shadow threshold.  This prevents "Rembrandt" from being called
        # when the L/R asymmetry comes from a soft tonal gradient with no
        # actual deep shadow pixels (which would be loop or broad, not Rembrandt).
        _shadow_side_pct = left_shadow if shadow_side == "left" else right_shadow
        _shadow_strong = _shadow_side_pct >= 0.15

        # Check for triangle: the Rembrandt triangle sits on the shadow
        # cheek BELOW the eye and ABOVE the jawline. Using 45-70% of face
        # height captures the eye-to-nose region where the triangle forms.
        # The outer 40% of the face width on the shadow side targets the
        # cheek specifically (wider than the old 1/3 which missed the
        # triangle on wide or turned faces).
        cheek_top = int(fh * 0.45)
        cheek_bottom = int(fh * 0.70)
        if shadow_side == "left":
            cheek_region = face_roi[cheek_top:cheek_bottom, :int(fw * 0.40)]
            surround_region = face_roi[int(fh * 0.25):cheek_top, :int(fw * 0.40)]
        else:
            cheek_region = face_roi[cheek_top:cheek_bottom, int(fw * 0.60):]
            surround_region = face_roi[int(fh * 0.25):cheek_top, int(fw * 0.60):]

        # Also sample BELOW the cheek (jaw zone) for peak detection
        jaw_top = int(fh * 0.70)
        jaw_bottom = int(fh * 0.85)
        if shadow_side == "left":
            jaw_region = face_roi[jaw_top:jaw_bottom, :int(fw * 0.40)]
        else:
            jaw_region = face_roi[jaw_top:jaw_bottom, int(fw * 0.60):]

        if cheek_region.size > 20:
            cheek_brightness = float(np.mean(cheek_region))
            surround_brightness = float(np.mean(surround_region)) if surround_region.size > 20 else cheek_brightness
            jaw_brightness = float(np.mean(jaw_region)) if jaw_region.size > 20 else cheek_brightness

            # ── Skin-tone-aware triangle isolation ────────────────────────
            # The triangle is a bright patch surrounded by shadow. The
            # absolute luminance delta is large on light skin (~30 units)
            # and small on dark skin (~5-10 units), but the RELATIVE
            # significance is the same: "this patch is meaningfully brighter
            # than its neighbors."
            #
            # Two complementary measures:
            #   1. Global: delta / face_mean (original — catches high-contrast)
            #   2. Local:  delta / local_range (new — catches low-contrast
            #              triangles on dark skin where the tonal range is
            #              compressed but the triangle is still distinct)
            #
            # The triangle passes if EITHER measure exceeds its threshold.
            _delta = cheek_brightness - surround_brightness
            _tri_global = _delta / max(face_mean, 1.0)
            # Local range: difference between brightest and darkest in the
            # shadow-side region (cheek + surround combined).
            _local_pixels = np.concatenate([
                cheek_region.ravel(),
                surround_region.ravel() if surround_region.size > 0 else np.array([])
            ])
            _local_range = float(np.percentile(_local_pixels, 95) - np.percentile(_local_pixels, 5)) if _local_pixels.size > 20 else max(face_mean, 1.0)
            _tri_local = _delta / max(_local_range, 1.0)

            _triangle_isolation = max(_tri_global, _tri_local)

            _above_threshold = cheek_brightness > shadow_threshold
            # Global threshold: 0.12 of face_mean (original)
            # Local threshold: 0.20 of local range (triangle is 20%+ of the
            # shadow-side tonal range — works even on very dark skin)
            _isolation_ok = _tri_global >= 0.12 or _tri_local >= 0.20

            # ── Percentile-based triangle detection ────────────────────
            # The Rembrandt triangle is a BRIGHT PATCH (maybe 20-30% of the
            # cheek area) surrounded by shadow. The mean of the cheek
            # region is diluted by shadow pixels. Instead, compare the
            # BRIGHT FRACTION of the cheek (p75 = upper quartile, which
            # captures the triangle patch) against the DARK FRACTION of
            # the same region (p25 = lower quartile, the shadow around it).
            # If the spread is wide, there's a distinct bright patch.
            if cheek_region.size > 50:
                _cheek_p75 = float(np.percentile(cheek_region, 75))
                _cheek_p25 = float(np.percentile(cheek_region, 25))
                _cheek_spread = (_cheek_p75 - _cheek_p25) / max(face_mean, 1.0)
                # Also check: does the bright fraction of the cheek
                # exceed the mean of the jaw below? (triangle is brighter
                # than the lowest shadow zone)
                _bright_vs_jaw = (_cheek_p75 - jaw_brightness) / max(face_mean, 1.0) if jaw_brightness > 0 else 0
                if _cheek_spread > 0.15 and _bright_vs_jaw > 0.10:
                    _isolation_ok = True
                    _triangle_isolation = _cheek_spread
                    notes.append(
                        f"percentile triangle: cheek_p75={_cheek_p75:.0f} "
                        f"cheek_p25={_cheek_p25:.0f} spread={_cheek_spread:.3f} "
                        f"jaw={jaw_brightness:.0f} bright_vs_jaw={_bright_vs_jaw:.3f}"
                    )

            # ── Dark skin / no-face-box fallback ──────────────────────────
            # When the face box is unavailable (face detector failed) or the
            # face has very dark skin (face_mean < 75), the fixed cheek
            # regions often miss the actual Rembrandt triangle because:
            #   a) Without landmarks, the ROI is a rough crop
            #   b) On dark skin, the tonal delta between triangle and
            #      shadow is too small for absolute thresholds
            # In this case, STRONG shadow asymmetry (|L-R| > 0.25) +
            # shadow_strong IS the Rembrandt evidence: one side of the face
            # is clearly in shadow with enough depth to form the pattern.
            _no_facebox = not hasattr(face_roi, '_facebox_sourced')  # rough proxy
            _dark_skin = face_mean < 75
            if (not _isolation_ok) and _shadow_strong and (_dark_skin or _delta < 0):
                _lr_diff = abs(left_shadow - right_shadow)
                if _lr_diff > 0.25:
                    _isolation_ok = True
                    _above_threshold = True
                    notes.append(
                        f"dark-skin/no-facebox triangle fallback: "
                        f"lr_diff={_lr_diff:.3f} shadow_strong=True "
                        f"face_mean={face_mean:.0f} → accepting as triangle"
                    )

            # Full Rembrandt: triangle confirmed + shadow connects nose to cheek
            # + meaningful shadow depth on the shadow side.
            # Relaxed connectivity for dark skin (conn_region often reads above
            # threshold because dark skin luminance is closer to shadow threshold).
            _conn_ok = _shadow_connected or (_dark_skin and _shadow_strong)
            if _above_threshold and _isolation_ok and _conn_ok and _shadow_strong:
                triangle_detected = True
                triangle_cheek = shadow_side
                triangle_completeness = round(
                    min(1.0, cheek_brightness / max(face_mean, 1.0)), 3
                )
                pattern_name = "rembrandt"
                nose_shadow_shape = "angled_with_triangle"
                notes.append(
                    f"illuminated triangle on {shadow_side} cheek "
                    f"(completeness={triangle_completeness:.2f}, "
                    f"isolation={_triangle_isolation:.2f}, "
                    f"shadow_pct={_shadow_side_pct:.2f}, "
                    f"connected={'yes' if _shadow_connected else 'no'}) → Rembrandt"
                )
            elif _above_threshold and _isolation_ok:
                # Triangle visible but connectivity or shadow strength weak —
                # record the triangle for downstream use but classify as loop
                # (the shadow zone doesn't fully support a Rembrandt call).
                triangle_detected = True
                triangle_cheek = shadow_side
                triangle_completeness = round(
                    min(1.0, cheek_brightness / max(face_mean, 1.0)), 3
                )
                pattern_name = "loop"
                nose_shadow_shape = "angled_with_triangle"
                notes.append(
                    f"triangle on {shadow_side} cheek (isolation={_triangle_isolation:.2f}) "
                    f"but shadow not fully connected (conn={'yes' if _shadow_connected else 'no'}, "
                    f"pct={_shadow_side_pct:.2f}) → loop (Rembrandt uncertain)"
                )
            else:
                # Check nose shadow angle: if near-horizontal (80-100° or
                # 260-280°), light is coming from the side → split, not loop.
                # Loop has a diagonal (~45°) nose shadow from above-and-side.
                _nsa = nose_shadow_angle_deg
                _is_horizontal = (70 <= _nsa <= 110) or (250 <= _nsa <= 290)
                if _is_horizontal and abs(left_shadow - right_shadow) > 0.25:
                    pattern_name = "split"
                    nose_shadow_shape = "half_face"
                    notes.append(
                        f"horizontal nose shadow angle ({_nsa:.0f}°) + asymmetry "
                        f"→ split lighting (not loop)"
                    )
                else:
                    pattern_name = "loop"
                    nose_shadow_shape = "short_angled"
                    notes.append(
                        f"angled shadow without triangle on {shadow_side} → loop lighting"
                    )
        else:
            pattern_name = "loop"
            nose_shadow_shape = "short_angled"

    # ── Indeterminate zone: 0.15 ≤ asymmetry < 0.2 ─────────────
    # Falls between butterfly/loop (< 0.15) and rembrandt (> 0.2).
    # Use centroid angle as tiebreaker: diagonal shadow direction
    # from upper quadrant is consistent with loop (off-axis key).
    elif abs(left_shadow - right_shadow) >= 0.15:
        # Moderate asymmetry — could be loop or weak rembrandt.
        # Check centroid direction: upper-diagonal = loop, lower = rembrandt
        _ca = _centroid_angle
        _is_diagonal_upper = (20 < _ca < 80) or (280 < _ca < 340)
        if _centroid_dist > 0.05 and _is_diagonal_upper:
            pattern_name = "loop"
            nose_shadow_shape = "short_angled"
            notes.append(
                f"indeterminate asymmetry ({abs(left_shadow - right_shadow):.2f}) "
                f"+ diagonal centroid ({_ca:.0f}°) → loop"
            )
        elif bottom_shadow > top_shadow * 1.2:
            # Shadow mass below nose center — ambiguous without strong
            # directional evidence.  Leave as unknown so reference_read's
            # richer analysis (with full-face geometry) can resolve it.
            pattern_name = "unknown"
            nose_shadow_shape = "indeterminate"
            notes.append(
                f"indeterminate asymmetry ({abs(left_shadow - right_shadow):.2f}) "
                f"+ bottom-heavy shadow → unknown (deferred to reference_read)"
            )
        else:
            pattern_name = "unknown"
            nose_shadow_shape = "indeterminate"
            notes.append(
                f"indeterminate zone: asymmetry={abs(left_shadow - right_shadow):.2f}, "
                f"centroid={_ca:.0f}°/{_centroid_dist:.2f}"
            )

    # Fill-heavy loop: very low abs asymmetry but confirmed diagonal centroid.
    # A well-filled loop (1:1 ratio) compresses both shadow_ratio and L/R asymmetry
    # to near-zero — all the earlier conditions fail.  But the shadow direction is
    # still diagonal.  If centroid is reliably diagonal and shadow isn't near-vertical,
    # call it loop.  This is the last chance before broad/unknown consumes it.
    elif _centroid_dist > 0.05 and not _angle_near_vertical and shadow_ratio > 0.02:
        _ca = _centroid_angle
        _is_diagonal = (20 < _ca < 80) or (280 < _ca < 340)
        if _is_diagonal:
            pattern_name = "loop"
            nose_shadow_shape = "short_angled"
            notes.append(
                f"fill-heavy loop: low shadow density ({shadow_ratio:.3f}), "
                f"diagonal centroid ({_ca:.0f}°, dist={_centroid_dist:.2f}) → loop"
            )
        else:
            pattern_name = "unknown"
            nose_shadow_shape = "indeterminate"
            notes.append(f"diagonal centroid but non-loop angle ({_ca:.0f}°) → unknown")

    # Broad lighting: symmetry > 0.7, wide highlight, near-vertical shadow.
    # Require _angle_near_vertical — broad/flat uses an on-axis or near-axis key;
    # a diagonal shadow direction rules out broad even when shadow_ratio is low.
    elif symmetry_score > 0.7 and shadow_ratio < 0.2 and _angle_near_vertical:
        pattern_name = "broad"
        nose_shadow_shape = "minimal"
        notes.append("high symmetry + minimal shadow + near-vertical → broad/flat lighting")

    else:
        pattern_name = "unknown"
        nose_shadow_shape = "indeterminate"
        notes.append(f"shadow_ratio={shadow_ratio:.2f}, asymmetry={abs(left_shadow - right_shadow):.2f}")

    # ── Unconditional cheek triangle scan ───────────────────────────
    # The Rembrandt branch above (elif abs(left-right) > 0.2) only runs
    # the cheek triangle measurement when there is significant nose L/R
    # shadow asymmetry.  A genuine Rembrandt triangle can exist even when
    # the nose shadow appears symmetric:
    #   (a) subtle key angle → mostly downward nose shadow with a small
    #       off-axis displacement  (b) low-key image → dark face averaging hides the cheek triangle
    # Scan BOTH cheeks unconditionally and update _triangle_isolation if
    # the Rembrandt branch did not already set it (i.e., still 0.0).
    # This does NOT change pattern_name — the cheek triangle alone does
    # not override the nose-shadow-based classification.  It only ensures
    # that the triangle_isolation metric is populated so that downstream
    # contradiction checks (orchestrator.py butterfly block) can use it.
    # True butterfly has no cheek triangle (tri_iso ≈ 0.00–0.08).
    # Rembrandt with near-symmetric nose: tri_iso measured here will
    # correctly show > 0.12 on the shadow-side cheek.
    if _triangle_isolation < 0.12 and face_mean > 0 and fh > 0 and fw > 0:
        _ct_cheek_top = 2 * fh // 3
        _ct_cheek_bot = fh
        _ct_surr_top  = fh // 2
        _ct_surr_bot  = _ct_cheek_top
        # Left cheek
        _ct_lc = face_roi[_ct_cheek_top:_ct_cheek_bot, :fw // 3]
        _ct_ls = face_roi[_ct_surr_top:_ct_surr_bot,  :fw // 3]
        # Right cheek
        _ct_rc = face_roi[_ct_cheek_top:_ct_cheek_bot, 2 * fw // 3:]
        _ct_rs = face_roi[_ct_surr_top:_ct_surr_bot,  2 * fw // 3:]
        _ct_best = 0.0
        for _cc, _cs in ((_ct_lc, _ct_ls), (_ct_rc, _ct_rs)):
            if _cc.size > 20:
                _cc_b = float(np.mean(_cc))
                _cs_b = float(np.mean(_cs)) if _cs.size > 20 else _cc_b
                _iso  = (_cc_b - _cs_b) / max(face_mean, 1.0)
                if _iso > _ct_best:
                    _ct_best = _iso
        if _ct_best > _triangle_isolation:
            _triangle_isolation = round(_ct_best, 3)
            if _ct_best >= 0.12:
                notes.append(
                    f"unconditional cheek scan found triangle_isolation={_ct_best:.3f} "
                    f"(Rembrandt triangle present despite low nose L/R asymmetry)"
                )

    # ── Confidence ───────────────────────────────────────────────
    confidence = 0.3
    if face_box is not None:
        confidence += 0.15
    if pattern_name != "unknown":
        confidence += 0.2
    if shadow_data and isinstance(shadow_data, dict) and shadow_data.get("ok"):
        confidence += 0.1
    if triangle_detected:
        confidence += 0.1
    confidence = round(min(0.9, confidence), 3)

    # ── Honesty gate: a guessed face box cannot support a pattern claim ──
    # This pass reads the NOSE SHADOW REGION. Without a real face box we do not
    # know where the nose is, so any pattern derived from a center crop is a
    # guess wearing a confidence score — and it was reporting 0.65.
    #
    # The center-crop fallback stays: it lets the surrounding passes work on
    # images where MediaPipe fails, which disproportionately affects
    # dark-skinned subjects, and abandoning them is not an option. What changes
    # is that this pass stops asserting a pattern it cannot support.
    if face_box_estimated:
        pattern_name = "unknown"
        confidence = min(confidence, 0.15)
        notes.append(
            "pattern withheld — face box was estimated, so nose-shadow geometry "
            "is not reliable enough to name a pattern"
        )

    # ── Highlight width ratio ────────────────────────────────────
    # Compute from the full face ROI: what fraction of columns are
    # brighter than 115% of the face mean?  This is a proxy for how
    # broad the lit side is.
    _highlight_width_ratio = 0.0
    col_means = np.mean(face_roi, axis=0).astype(float)
    if len(col_means) > 5:
        _hl_threshold = face_mean * 1.15
        _hl_cols = col_means > _hl_threshold
        _highlight_width_ratio = round(float(np.sum(_hl_cols)) / len(col_means), 3)

    return {
        "ok": True,
        "nose_shadow_shape": nose_shadow_shape,
        "nose_shadow_length_ratio": round(nose_shadow_length_ratio, 3),
        "nose_shadow_angle_deg": round(nose_shadow_angle_deg, 1),
        "triangle_detected": triangle_detected,
        "triangle_cheek": triangle_cheek,
        "triangle_completeness": round(triangle_completeness, 3),
        "pattern_name": pattern_name,
        "confidence": confidence,
        "face_box_estimated": face_box_estimated,
        "notes": notes,
        # ── Enhanced signals (v2) ──
        "nose_shadow_centroid_angle_deg": round(_centroid_angle, 1),
        "nose_shadow_centroid_distance": round(_centroid_dist, 3),
        "left_right_asymmetry": round(abs(left_shadow - right_shadow), 3),
        "top_bottom_ratio": round(bottom_shadow / max(top_shadow, 0.01), 3),
        "shadow_density": round(shadow_ratio, 3),
        "triangle_isolation": round(_triangle_isolation, 3),
        "highlight_width_ratio": _highlight_width_ratio,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. BACKGROUND GRADIENT PASS
# ═══════════════════════════════════════════════════════════════════════════

def background_pass(
    img_bgr: np.ndarray,
    background_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Analyze the brightness distribution of the background.

    Returns:
        background_gradient_center_x: X center of brightest region (0-1)
        background_gradient_center_y: Y center of brightest region (0-1)
        background_gradient_spread: How spread out the gradient is (0-1)
        background_intensity_ratio: Background brightness vs subject (0-1)
        background_direction: Direction of gradient (center/left/right/top/bottom)
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Use background mask if available
    if background_mask is not None:
        bg_mask = background_mask.astype(bool)
    else:
        # Assume outer 20% is background
        bg_mask = np.ones((h, w), dtype=bool)
        margin_y, margin_x = h // 5, w // 5
        bg_mask[margin_y:h-margin_y, margin_x:w-margin_x] = False

    bg_pixels = gray[bg_mask]

    if len(bg_pixels) < 100:
        return {"ok": False, "error": "insufficient background pixels"}

    # -- Gradient center --
    # Find the centroid of the brightest background pixels
    bg_gray = gray.copy().astype(float)
    bg_gray[~bg_mask] = 0

    # Blur to find smooth gradient
    bg_blurred = cv2.GaussianBlur(bg_gray, (51, 51), 0)
    bg_blurred[~bg_mask] = 0

    # Find peak brightness location
    if np.max(bg_blurred) > 0:
        # Threshold to top 20% of brightness
        top_thresh = np.percentile(bg_blurred[bg_mask], 80)
        bright_mask = bg_blurred > top_thresh

        ys, xs = np.where(bright_mask)
        if len(xs) > 0:
            center_x = float(np.mean(xs)) / w
            center_y = float(np.mean(ys)) / h
        else:
            center_x, center_y = 0.5, 0.5
    else:
        center_x, center_y = 0.5, 0.5

    # -- Gradient spread --
    # Standard deviation of brightness values
    bg_std = float(np.std(bg_pixels))
    bg_mean = float(np.mean(bg_pixels))
    if bg_mean > 0:
        spread = min(1.0, bg_std / bg_mean)
    else:
        spread = 0.0

    # -- Intensity ratio --
    # Compare background brightness to overall person brightness
    subject_mask = ~bg_mask
    subject_pixels = gray[subject_mask]
    if len(subject_pixels) > 0:
        intensity_ratio = bg_mean / max(float(np.mean(subject_pixels)), 1.0)
        intensity_ratio = min(1.0, max(0.0, intensity_ratio))
    else:
        intensity_ratio = 0.5

    # -- Direction --
    # Divide background into quadrants and compare brightness
    mid_x, mid_y = w // 2, h // 2
    left_mask = bg_mask.copy()
    left_mask[:, mid_x:] = False
    right_mask = bg_mask.copy()
    right_mask[:, :mid_x] = False
    top_mask = bg_mask.copy()
    top_mask[mid_y:, :] = False
    bottom_mask = bg_mask.copy()
    bottom_mask[:mid_y, :] = False

    region_means = {
        "left": float(np.mean(gray[left_mask])) if np.any(left_mask) else 0,
        "right": float(np.mean(gray[right_mask])) if np.any(right_mask) else 0,
        "top": float(np.mean(gray[top_mask])) if np.any(top_mask) else 0,
        "bottom": float(np.mean(gray[bottom_mask])) if np.any(bottom_mask) else 0,
    }

    max_region = max(region_means, key=region_means.get)
    min_region = min(region_means, key=region_means.get)
    max_val = region_means[max_region]
    min_val = region_means[min_region]

    if max_val > 0 and (max_val - min_val) / max_val > 0.15:
        direction = max_region
    else:
        direction = "center"

    return {
        "ok": True,
        "background_gradient_center_x": round(center_x, 3),
        "background_gradient_center_y": round(center_y, 3),
        "background_gradient_spread": round(spread, 3),
        "background_intensity_ratio": round(intensity_ratio, 3),
        "background_direction": direction,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. SPECULAR SURFACE PASS
# ═══════════════════════════════════════════════════════════════════════════

_SPECULAR_REGIONS = ["forehead", "cheekbone", "shoulders", "arms", "legs", "clothing"]


def specular_surface_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Analyze specular highlights on skin and reflective surfaces.

    Large specular spread usually indicates larger modifiers or closer lights.

    Returns:
        specular_highlight_count: Number of distinct specular highlights
        specular_highlight_size: Average size of specular spots (0-1)
        specular_highlight_spread: How spread out specular highlights are (0-1)
        specular_axis_deg: Angle of specular highlight axis
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Work within person region
    if person_mask is not None:
        pmask = person_mask.astype(np.uint8) * 255
    else:
        pmask = np.ones((h, w), dtype=np.uint8) * 255

    person_gray = cv2.bitwise_and(gray, pmask)
    person_pixels = person_gray[pmask > 0]

    if len(person_pixels) < 100:
        return {"ok": False, "error": "insufficient person pixels for specular analysis"}

    # -- Find specular highlights --
    # Specular highlights are very bright, low-saturation spots
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    # High brightness + low saturation = specular
    bright_thresh = max(220, int(np.percentile(person_pixels, 97)))
    specular_mask = (gray > bright_thresh) & (sat < 60) & (pmask > 0)

    # Clean up with morphological operations
    kernel = np.ones((3, 3), np.uint8)
    specular_cleaned = cv2.morphologyEx(
        specular_mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel
    )
    specular_cleaned = cv2.morphologyEx(specular_cleaned, cv2.MORPH_OPEN, kernel)

    # Find contours of specular regions
    contours, _ = cv2.findContours(
        specular_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    # Filter small noise (< 10 pixels)
    min_area = max(10, (h * w) // 50000)
    valid_contours = [c for c in contours if cv2.contourArea(c) >= min_area]

    specular_count = len(valid_contours)

    # -- Specular size --
    if valid_contours:
        areas = [cv2.contourArea(c) for c in valid_contours]
        total_area = h * w
        avg_area = float(np.mean(areas))
        specular_size = min(1.0, avg_area / (total_area * 0.01))
    else:
        specular_size = 0.0

    # -- Specular spread --
    if len(valid_contours) >= 2:
        centroids = []
        for c in valid_contours:
            M = cv2.moments(c)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                centroids.append((cx, cy))

        if len(centroids) >= 2:
            # Compute pairwise distances
            pts = np.array(centroids, dtype=float)
            dists = []
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    d = np.sqrt((pts[i][0] - pts[j][0])**2 + (pts[i][1] - pts[j][1])**2)
                    dists.append(d)
            max_dist = max(w, h)
            spread = min(1.0, float(np.mean(dists)) / (max_dist * 0.5))
        else:
            spread = 0.0
    else:
        spread = 0.0

    # -- Specular axis --
    specular_axis = None
    if valid_contours:
        # Combine all specular points and fit a line
        all_points = np.vstack(valid_contours) if len(valid_contours) > 0 else None
        if all_points is not None and len(all_points) >= 5:
            try:
                (_, _), (_, _), angle = cv2.fitEllipse(all_points)
                specular_axis = float(angle)
            except cv2.error:
                pass

    return {
        "ok": True,
        "specular_highlight_count": specular_count,
        "specular_highlight_size": round(specular_size, 3),
        "specular_highlight_spread": round(spread, 3),
        "specular_axis_deg": round(specular_axis, 1) if specular_axis is not None else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5A. LIGHT ROLE PASS
# ═══════════════════════════════════════════════════════════════════════════

_LIGHT_ROLES = [
    "key", "fill", "negative_fill", "rim", "kicker",
    "background", "bounce", "unknown_secondary",
]

_LIGHT_COUNT_LABELS = ["one", "two", "three", "multi"]


def _detect_edge_highlights(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray],
    face_box: Optional[Tuple[int, int, int, int]],
) -> Dict[str, Any]:
    """Scan left/right edges of person for bright rim/kicker highlights.

    Erodes the person mask, subtracts from original to get an edge strip,
    then compares brightness of left-edge vs right-edge vs interior.

    Returns dict with: has_rim, rim_side, rim_brightness_ratio, has_kicker.
    """
    result = {
        "has_rim": False,
        "rim_side": None,
        "rim_brightness_ratio": 0.0,
        "has_kicker": False,
    }

    if cv2 is None or person_mask is None:
        return result

    pmask = person_mask.astype(np.uint8)
    if pmask.sum() < 200:
        return result

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Erode person mask to get interior
    erode_px = max(3, min(10, w // 30))
    kernel = np.ones((erode_px, erode_px), np.uint8)
    eroded = cv2.erode(pmask, kernel, iterations=1)

    # Edge strip = original mask minus eroded
    edge_strip = pmask - eroded
    edge_strip = np.clip(edge_strip, 0, 1)

    # Split into left and right halves
    mid_x = w // 2
    left_edge = edge_strip.copy()
    left_edge[:, mid_x:] = 0
    right_edge = edge_strip.copy()
    right_edge[:, :mid_x] = 0

    interior = eroded

    # Mean brightness in each region
    left_pixels = gray[left_edge > 0]
    right_pixels = gray[right_edge > 0]
    interior_pixels = gray[interior > 0]

    if len(left_pixels) < 10 or len(right_pixels) < 10 or len(interior_pixels) < 10:
        return result

    left_brightness = float(np.mean(left_pixels))
    right_brightness = float(np.mean(right_pixels))
    interior_brightness = float(np.mean(interior_pixels))

    # Avoid division by zero
    if interior_brightness < 5:
        return result

    left_ratio = left_brightness / interior_brightness
    right_ratio = right_brightness / interior_brightness

    # Rim: bright edge on one side (ratio > 1.3)
    rim_threshold = 1.3
    if left_ratio > rim_threshold and left_ratio > right_ratio + 0.2:
        result["has_rim"] = True
        result["rim_side"] = "left"
        result["rim_brightness_ratio"] = round(left_ratio, 3)
    elif right_ratio > rim_threshold and right_ratio > left_ratio + 0.2:
        result["has_rim"] = True
        result["rim_side"] = "right"
        result["rim_brightness_ratio"] = round(right_ratio, 3)

    # Kicker: both sides brighter than interior (both > 1.2)
    kicker_threshold = 1.2
    if left_ratio > kicker_threshold and right_ratio > kicker_threshold:
        result["has_kicker"] = True
        result["rim_brightness_ratio"] = round(max(left_ratio, right_ratio), 3)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 5b. LIGHT DIRECTION FIELD PASS
# ═══════════════════════════════════════════════════════════════════════════

_LDF_GRID_SIZE = 4  # 4x4 grid over subject region


def light_direction_field_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Estimate multiple local light direction vectors across the subject.

    Divides the subject region into a grid and computes per-cell gradient
    directions in the luminance channel.  Consistent vectors indicate a
    single distant source; divergent vectors suggest multiple or close sources.

    Returns:
        ok, ldf_vectors, dominant_light_vector_deg, vector_consistency,
        ldf_cell_count, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Determine analysis region — person mask or face box fallback
    if person_mask is not None and person_mask.any():
        ys, xs = np.where(person_mask > 0)
        roi_y0, roi_y1 = int(ys.min()), int(ys.max())
        roi_x0, roi_x1 = int(xs.min()), int(xs.max())
    elif face_box is not None:
        roi_x0, roi_y0, roi_x1, roi_y1 = face_box
    else:
        # Fallback: central 60% of image
        roi_y0, roi_y1 = int(h * 0.2), int(h * 0.8)
        roi_x0, roi_x1 = int(w * 0.2), int(w * 0.8)
        notes.append("No mask/face_box — using central region.")

    roi_h = roi_y1 - roi_y0
    roi_w = roi_x1 - roi_x0
    if roi_h < 20 or roi_w < 20:
        return {"ok": False, "error": "ROI too small for LDF analysis"}

    cell_h = roi_h // _LDF_GRID_SIZE
    cell_w = roi_w // _LDF_GRID_SIZE
    if cell_h < 5 or cell_w < 5:
        return {"ok": False, "error": "Grid cells too small"}

    # Compute Sobel gradients
    grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

    vectors: List[Dict[str, Any]] = []
    angles: List[float] = []

    for row in range(_LDF_GRID_SIZE):
        for col in range(_LDF_GRID_SIZE):
            cy0 = roi_y0 + row * cell_h
            cy1 = cy0 + cell_h
            cx0 = roi_x0 + col * cell_w
            cx1 = cx0 + cell_w

            # Skip cells outside person mask
            if person_mask is not None:
                cell_mask = person_mask[cy0:cy1, cx0:cx1]
                if cell_mask.size == 0 or float(np.mean(cell_mask > 0)) < 0.3:
                    continue

            gx = grad_x[cy0:cy1, cx0:cx1]
            gy = grad_y[cy0:cy1, cx0:cx1]
            mag = np.sqrt(gx ** 2 + gy ** 2)
            mean_mag = float(np.mean(mag))
            if mean_mag < 1.0:
                continue  # flat region — no gradient

            # Weighted mean direction (magnitude-weighted)
            w_gx = float(np.sum(gx * mag)) / float(np.sum(mag) + 1e-9)
            w_gy = float(np.sum(gy * mag)) / float(np.sum(mag) + 1e-9)
            angle_deg = float(np.degrees(np.arctan2(w_gy, w_gx)))

            vectors.append({
                "region": f"r{row}_c{col}",
                "angle_deg": round(angle_deg, 1),
                "magnitude": round(mean_mag, 2),
                "confidence": min(1.0, mean_mag / 50.0),
            })
            angles.append(angle_deg)

    if not angles:
        return {
            "ok": True,
            "ldf_vectors": [],
            "dominant_light_vector_deg": 0.0,
            "vector_consistency": 0.0,
            "ldf_cell_count": 0,
            "notes": notes + ["No valid gradient cells found."],
        }

    # Dominant direction via circular mean
    rads = np.radians(angles)
    mean_sin = float(np.mean(np.sin(rads)))
    mean_cos = float(np.mean(np.cos(rads)))
    dominant_deg = float(np.degrees(np.arctan2(mean_sin, mean_cos)))

    # Consistency = 1 - circular variance (R-bar)
    r_bar = math.sqrt(mean_sin ** 2 + mean_cos ** 2)
    consistency = round(min(1.0, r_bar), 3)

    notes.append(f"Analyzed {len(angles)} cells, dominant direction {dominant_deg:.1f}°.")

    return {
        "ok": True,
        "ldf_vectors": vectors,
        "dominant_light_vector_deg": round(dominant_deg, 1),
        "vector_consistency": consistency,
        "ldf_cell_count": len(angles),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5c. INVERSE SQUARE SOLVER PASS
# ═══════════════════════════════════════════════════════════════════════════

_ISQ_DISTANCE_NEAR = 3.0   # feet
_ISQ_DISTANCE_FAR = 8.0    # feet


def inverse_square_solver_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    specular: Optional[Dict[str, Any]] = None,
    catchlight: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Estimate light-to-subject distance using brightness falloff.

    Measures brightness across vertical bands of the subject (head, torso,
    lower body).  Steep falloff indicates a close source; flat falloff
    indicates a distant source.

    Returns:
        ok, distance_estimate_ft, distance_class, falloff_gradient,
        falloff_direction, isq_confidence, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Determine analysis region
    if person_mask is not None and person_mask.any():
        ys, xs = np.where(person_mask > 0)
        roi_y0, roi_y1 = int(ys.min()), int(ys.max())
        roi_x0, roi_x1 = int(xs.min()), int(xs.max())
    elif face_box is not None:
        fx0, fy0, fx1, fy1 = face_box
        face_h = fy1 - fy0
        roi_x0, roi_y0 = fx0, fy0
        roi_x1 = fx1
        roi_y1 = min(h, fy1 + face_h * 4)  # estimate body below face
    else:
        return {"ok": False, "error": "No person_mask or face_box"}

    roi_h = roi_y1 - roi_y0
    if roi_h < 30:
        return {"ok": False, "error": "ROI too small for falloff analysis"}

    # Split into 3 vertical bands
    band_h = roi_h // 3
    bands = []
    for i in range(3):
        by0 = roi_y0 + i * band_h
        by1 = by0 + band_h
        band = gray[by0:by1, roi_x0:roi_x1]
        if person_mask is not None:
            mask_band = person_mask[by0:by1, roi_x0:roi_x1]
            pixels = band[mask_band > 0]
        else:
            pixels = band.ravel()
        if pixels.size > 10:
            bands.append(float(np.mean(pixels)))
        else:
            bands.append(0.0)

    if bands[0] < 1.0:
        return {"ok": False, "error": "Top band too dark for falloff analysis"}

    # Compute falloff gradient (ratio of top to bottom brightness)
    falloff = 1.0 - (bands[2] / max(bands[0], 1.0))
    falloff = max(0.0, min(1.0, falloff))

    # Also check horizontal falloff (left-to-right) for side-lit scenes
    mid_y0 = roi_y0 + band_h
    mid_y1 = mid_y0 + band_h
    mid_w = roi_x1 - roi_x0
    if mid_w > 20:
        left_band = gray[mid_y0:mid_y1, roi_x0:roi_x0 + mid_w // 3]
        right_band = gray[mid_y0:mid_y1, roi_x1 - mid_w // 3:roi_x1]
        if person_mask is not None:
            lm = person_mask[mid_y0:mid_y1, roi_x0:roi_x0 + mid_w // 3]
            rm = person_mask[mid_y0:mid_y1, roi_x1 - mid_w // 3:roi_x1]
            left_mean = float(np.mean(left_band[lm > 0])) if lm.any() else 0.0
            right_mean = float(np.mean(right_band[rm > 0])) if rm.any() else 0.0
        else:
            left_mean = float(np.mean(left_band))
            right_mean = float(np.mean(right_band))

        horiz_diff = abs(left_mean - right_mean) / max(left_mean, right_mean, 1.0)
    else:
        left_mean = right_mean = horiz_diff = 0.0

    # Choose dominant falloff direction
    if horiz_diff > falloff and horiz_diff > 0.1:
        direction = "left_to_right" if left_mean > right_mean else "right_to_left"
        gradient = horiz_diff
        notes.append(f"Horizontal falloff ({horiz_diff:.2f}) dominates vertical ({falloff:.2f}).")
    else:
        direction = "top_to_bottom"
        gradient = falloff
        notes.append(f"Vertical falloff ({falloff:.2f}) is primary.")

    # Map gradient to distance estimate using inverse-square relationship
    # Steep gradient (>0.4) → close (<3ft), flat (<0.15) → far (>8ft)
    if gradient > 0.4:
        distance_ft = max(1.5, 3.0 - (gradient - 0.4) * 5.0)
        distance_class = "near"
    elif gradient > 0.15:
        distance_ft = 3.0 + (0.4 - gradient) * 20.0
        distance_class = "medium"
    else:
        distance_ft = 8.0 + (0.15 - gradient) * 40.0
        distance_class = "far"

    confidence = min(1.0, 0.3 + gradient * 1.5)

    return {
        "ok": True,
        "distance_estimate_ft": round(distance_ft, 1),
        "distance_class": distance_class,
        "falloff_gradient": round(gradient, 3),
        "falloff_direction": direction,
        "isq_confidence": round(confidence, 2),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5d. SOLAR GEOMETRY PASS
# ═══════════════════════════════════════════════════════════════════════════


def solar_geometry_pass(
    img_bgr: np.ndarray,
    shadow: Optional[Dict[str, Any]] = None,
    background: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Detect sun/daylight illumination using parallel shadow vectors and warmth.

    Parallel shadows (multiple objects casting same-direction shadows) are
    the hallmark of a distant point source (sun).  Combined with warm color
    temperature and outdoor background cues.

    Returns:
        ok, sun_candidate, sun_azimuth_deg, sun_elevation_deg,
        parallel_shadow_score, color_warmth_score, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Ensure mask is uint8 for OpenCV bitwise ops (CV 4.13+ rejects bool)
    if person_mask is not None and person_mask.dtype == bool:
        person_mask = person_mask.astype(np.uint8) * 255

    # 1. Shadow edge parallelism via Canny + HoughLinesP
    edges = cv2.Canny(gray, 50, 150)
    if person_mask is not None:
        # Analyze shadows on the ground / non-person areas
        bg_mask = cv2.bitwise_not(person_mask) if person_mask is not None else None
        if bg_mask is not None:
            edges = cv2.bitwise_and(edges, edges, mask=bg_mask)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40,
                            minLineLength=max(20, min(h, w) // 15),
                            maxLineGap=10)

    parallel_score = 0.0
    sun_azimuth = None
    if lines is not None and len(lines) >= 3:
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            angles.append(angle)
        angles = np.array(angles)

        # Histogram of angles — peak at one angle means parallel
        hist, bin_edges = np.histogram(angles, bins=18, range=(0, 180))
        peak_idx = int(np.argmax(hist))
        peak_count = int(hist[peak_idx])
        total = len(angles)

        parallel_score = peak_count / max(total, 1)
        if parallel_score > 0.3:
            sun_azimuth = float((bin_edges[peak_idx] + bin_edges[peak_idx + 1]) / 2)
            notes.append(f"Parallel shadow edges: {peak_count}/{total} lines at ~{sun_azimuth:.0f}°.")
    else:
        notes.append("Insufficient shadow edges for parallelism analysis.")

    # 2. Color warmth — high R/B ratio in highlight regions
    highlight_mask = gray > np.percentile(gray, 85)
    if person_mask is not None:
        highlight_mask = highlight_mask & (person_mask > 0)

    warmth_score = 0.0
    if highlight_mask.any():
        r_chan = img_bgr[:, :, 2].astype(float)  # BGR → R
        b_chan = img_bgr[:, :, 0].astype(float)  # BGR → B
        r_mean = float(np.mean(r_chan[highlight_mask]))
        b_mean = float(np.mean(b_chan[highlight_mask]))
        if b_mean > 0:
            rb_ratio = r_mean / b_mean
            # Daylight: ~1.0-1.1, Golden hour: 1.2-1.5, Tungsten: 1.3-1.6
            warmth_score = max(0.0, min(1.0, (rb_ratio - 1.0) * 3.0))
        notes.append(f"Highlight warmth: R/B={rb_ratio:.2f} → warmth={warmth_score:.2f}.")

    # 3. Estimate sun elevation from shadow vector angle (from upstream)
    sun_elevation = None
    if shadow and shadow.get("ok"):
        vert_angle = shadow.get("shadow_vertical_angle_deg")
        if vert_angle is not None:
            # Shadow angle below horizon → elevation above
            sun_elevation = max(0.0, 90.0 - abs(vert_angle))

    # 4. Sun candidate determination
    sun_candidate = parallel_score > 0.35 and warmth_score > 0.2

    return {
        "ok": True,
        "sun_candidate": sun_candidate,
        "sun_azimuth_deg": round(sun_azimuth, 1) if sun_azimuth is not None else None,
        "sun_elevation_deg": round(sun_elevation, 1) if sun_elevation is not None else None,
        "parallel_shadow_score": round(parallel_score, 3),
        "color_warmth_score": round(warmth_score, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5e. WINDOW GEOMETRY PASS
# ═══════════════════════════════════════════════════════════════════════════


def window_geometry_pass(
    img_bgr: np.ndarray,
    background: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Detect window lighting using directional gradients and rectangular reflections.

    Window light creates characteristic unidirectional luminance gradients
    with rectangular catchlight shapes and soft-to-medium shadow transitions.

    Returns:
        ok, window_candidate, window_direction, rectangular_reflection_score,
        gradient_directionality, window_confidence, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Ensure mask is uint8 for OpenCV bitwise ops (CV 4.13+ rejects bool)
    if person_mask is not None and person_mask.dtype == bool:
        person_mask = person_mask.astype(np.uint8) * 255

    # 1. Luminance gradient directionality
    # Split image into left/right/top/bottom strips and compare means
    strip_w = max(1, w // 5)
    strip_h = max(1, h // 5)

    left_mean = float(np.mean(gray[:, :strip_w]))
    right_mean = float(np.mean(gray[:, w - strip_w:]))
    top_mean = float(np.mean(gray[:strip_h, :]))
    bottom_mean = float(np.mean(gray[h - strip_h:, :]))
    center_mean = float(np.mean(gray[strip_h:h - strip_h, strip_w:w - strip_w]))

    # Directionality: how much one direction dominates
    horiz_diff = abs(left_mean - right_mean) / max(center_mean, 1.0)
    vert_diff = abs(top_mean - bottom_mean) / max(center_mean, 1.0)
    directionality = max(horiz_diff, vert_diff)
    directionality = min(1.0, directionality * 2.0)  # scale to 0-1

    # Determine window direction
    window_dir = None
    if horiz_diff > vert_diff and horiz_diff > 0.1:
        window_dir = "left" if left_mean > right_mean else "right"
    elif vert_diff > 0.1:
        window_dir = "above" if top_mean > bottom_mean else "below"

    # 2. Rectangular reflection detection (from highlight regions)
    rect_score = 0.0
    bright_mask = (gray > np.percentile(gray, 92)).astype(np.uint8)
    if person_mask is not None:
        bright_mask = cv2.bitwise_and(bright_mask, bright_mask, mask=person_mask)

    contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    rect_count = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 50:
            continue
        _, _, cw, ch = cv2.boundingRect(cnt)
        if cw < 3 or ch < 3:
            continue
        aspect = max(cw, ch) / min(cw, ch)
        # Rectangular: aspect 1.2-4.0, not too circular
        perimeter = cv2.arcLength(cnt, True)
        circularity = (4 * math.pi * area) / (perimeter * perimeter + 1e-9)
        if 1.2 <= aspect <= 4.0 and circularity < 0.75:
            rect_count += 1
    rect_score = min(1.0, rect_count / 3.0)

    # 3. Window candidate determination
    # Window light: unidirectional + soft (wide highlight) + rectangular catchlights
    highlight_width = 0.0
    if highlight and highlight.get("ok"):
        highlight_width = highlight.get("highlight_width_ratio", 0.0)

    # Soft-to-medium range for window (not point-source hard, not envelope soft)
    softness_score = 0.0
    if 0.2 < highlight_width < 0.7:
        softness_score = 1.0 - abs(highlight_width - 0.45) * 3.0
        softness_score = max(0.0, min(1.0, softness_score))

    confidence = (directionality * 0.4 + rect_score * 0.3 + softness_score * 0.3)
    window_candidate = confidence > 0.35 and directionality > 0.2

    notes.append(
        f"Gradient directionality={directionality:.2f}, "
        f"rect_reflections={rect_count}, softness={softness_score:.2f}."
    )

    return {
        "ok": True,
        "window_candidate": window_candidate,
        "window_direction": window_dir,
        "rectangular_reflection_score": round(rect_score, 3),
        "gradient_directionality": round(directionality, 3),
        "window_confidence": round(confidence, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5f. BOUNCE GEOMETRY PASS
# ═══════════════════════════════════════════════════════════════════════════


def bounce_geometry_pass(
    img_bgr: np.ndarray,
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Detect environmental bounce sources (walls, floors, reflectors).

    Bounce light appears as low-contrast fill from a broad direction,
    often carrying the color of the bouncing surface.

    Returns:
        ok, bounce_sources, dominant_bounce_direction, bounce_fill_ratio, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Analyze shadow-side brightness for bounce evidence
    # If the shadow side of the face/body is surprisingly bright with a
    # color cast, it's likely bounce from a nearby surface.
    bounce_sources: List[Dict[str, Any]] = []
    dominant_bounce = None
    bounce_fill_ratio = 0.0

    if face_box is not None:
        fx0, fy0, fx1, fy1 = face_box
        face_w = fx1 - fx0
        face_h = fy1 - fy0
        mid_x = fx0 + face_w // 2

        # Left and right face halves
        left_face = img_bgr[fy0:fy1, fx0:mid_x]
        right_face = img_bgr[fy0:fy1, mid_x:fx1]

        if left_face.size > 0 and right_face.size > 0:
            left_lum = float(np.mean(cv2.cvtColor(left_face, cv2.COLOR_BGR2GRAY)))
            right_lum = float(np.mean(cv2.cvtColor(right_face, cv2.COLOR_BGR2GRAY)))

            # Shadow side is the darker half
            if left_lum < right_lum:
                shadow_face = left_face
                shadow_lum = left_lum
                bright_lum = right_lum
                shadow_dir = "left"
            else:
                shadow_face = right_face
                shadow_lum = right_lum
                bright_lum = left_lum
                shadow_dir = "right"

            # Fill ratio: how much the shadow side is filled relative to key
            if bright_lum > 1:
                bounce_fill_ratio = shadow_lum / bright_lum
                bounce_fill_ratio = max(0.0, min(1.0, bounce_fill_ratio))

            # Check color cast in shadow region
            shadow_mean = np.mean(shadow_face.reshape(-1, 3), axis=0)  # BGR
            total = float(np.sum(shadow_mean)) + 1e-9
            b_pct = shadow_mean[0] / total
            g_pct = shadow_mean[1] / total
            r_pct = shadow_mean[2] / total

            color_cast = "neutral"
            if r_pct > 0.38:
                color_cast = "warm"
            elif b_pct > 0.38:
                color_cast = "cool"
            elif g_pct > 0.38:
                color_cast = "green_cast"

            # Bounce evidence: fill_ratio > 0.3 suggests bounce/fill from shadow side
            if bounce_fill_ratio > 0.3:
                bounce_sources.append({
                    "direction": shadow_dir,
                    "intensity": round(bounce_fill_ratio, 3),
                    "color_cast": color_cast,
                    "confidence": round(min(1.0, bounce_fill_ratio * 1.5), 2),
                })
                dominant_bounce = shadow_dir
                notes.append(
                    f"Bounce fill from {shadow_dir}: "
                    f"ratio={bounce_fill_ratio:.2f}, cast={color_cast}."
                )

    # Check below-face bounce (floor/reflector below)
    if face_box is not None:
        fx0, fy0, fx1, fy1 = face_box
        face_h = fy1 - fy0
        below_y0 = fy1
        below_y1 = min(h, fy1 + face_h)
        if below_y1 - below_y0 > 10:
            chin_region = gray[fy1 - face_h // 4:fy1, fx0:fx1]
            below_region = gray[below_y0:below_y1, fx0:fx1]
            if chin_region.size > 0 and below_region.size > 0:
                chin_lum = float(np.mean(chin_region))
                below_lum = float(np.mean(below_region))
                # Bright below-face + illuminated chin = upward bounce
                if below_lum > chin_lum * 0.8 and chin_lum > 80:
                    bounce_sources.append({
                        "direction": "below",
                        "intensity": round(min(1.0, chin_lum / 255.0), 3),
                        "color_cast": "neutral",
                        "confidence": 0.5,
                    })
                    notes.append("Possible floor/reflector bounce from below.")

    return {
        "ok": True,
        "bounce_sources": bounce_sources,
        "dominant_bounce_direction": dominant_bounce,
        "bounce_fill_ratio": round(bounce_fill_ratio, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5g. REFLECTION GEOMETRY PASS
# ═══════════════════════════════════════════════════════════════════════════

_SHAPE_LABELS = {
    (0.8, 1.3): "circular",
    (1.3, 2.5): "rectangular",
    (2.5, 8.0): "strip",
}


def reflection_geometry_pass(
    img_bgr: np.ndarray,
    specular: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Detect specular reflection regions and characterize their geometry.

    Maps reflection contours to infer source shape and position.

    Returns:
        ok, reflection_regions, reflection_count, dominant_reflection_shape,
        reflection_axis_deg, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Ensure mask is uint8 for OpenCV bitwise ops (CV 4.13+ rejects bool)
    if person_mask is not None and person_mask.dtype == bool:
        person_mask = person_mask.astype(np.uint8) * 255

    # Find bright specular regions
    thresh = max(200, int(np.percentile(gray, 97)))
    bright_mask = (gray >= thresh).astype(np.uint8)

    # Focus on person region if available
    if person_mask is not None:
        bright_mask = cv2.bitwise_and(bright_mask, bright_mask, mask=person_mask)

    # Clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    regions: List[Dict[str, Any]] = []
    shapes_seen: List[str] = []
    axis_angles: List[float] = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 20:
            continue

        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < 2 or ch < 2:
            continue

        aspect = max(cw, ch) / min(cw, ch)
        brightness = float(np.mean(gray[y:y + ch, x:x + cw]))

        # Classify shape by aspect ratio
        shape = "point"
        if area < 50:
            shape = "point"
        else:
            for (lo, hi), label in _SHAPE_LABELS.items():
                if lo <= aspect < hi:
                    shape = label
                    break
            else:
                shape = "strip" if aspect >= 8.0 else "point"

        # Check for ring shape (donut — hollow center)
        perimeter = cv2.arcLength(cnt, True)
        circularity = (4 * math.pi * area) / (perimeter * perimeter + 1e-9)
        if 0.4 < circularity < 0.7 and 0.8 <= aspect <= 1.5:
            shape = "ring"

        regions.append({
            "contour_bbox": [int(x), int(y), int(cw), int(ch)],
            "shape": shape,
            "aspect_ratio": round(aspect, 2),
            "brightness": round(brightness, 1),
            "area_px": int(area),
        })
        shapes_seen.append(shape)

        # Axis from ellipse fit
        if len(cnt) >= 5:
            (_, _), (_, _), angle = cv2.fitEllipse(cnt)
            axis_angles.append(angle)

    # Dominant shape
    if shapes_seen:
        from collections import Counter
        shape_counts = Counter(shapes_seen)
        dominant_shape = shape_counts.most_common(1)[0][0]
    else:
        dominant_shape = "none"

    # Dominant axis
    reflection_axis = None
    if axis_angles:
        reflection_axis = float(np.median(axis_angles))

    notes.append(f"Found {len(regions)} reflection regions, dominant shape={dominant_shape}.")

    return {
        "ok": True,
        "reflection_regions": regions,
        "reflection_count": len(regions),
        "dominant_reflection_shape": dominant_shape,
        "reflection_axis_deg": round(reflection_axis, 1) if reflection_axis is not None else None,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5h. SHADOW PENUMBRA PASS
# ═══════════════════════════════════════════════════════════════════════════

_PENUMBRA_SIZE_MAP = [
    (0.0, 0.02, "point"),
    (0.02, 0.06, "small"),
    (0.06, 0.12, "medium"),
    (0.12, 0.25, "large"),
    (0.25, 1.0, "very_large"),
]


def shadow_penumbra_pass(
    img_bgr: np.ndarray,
    shadow: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Measure shadow penumbra width to estimate apparent source angular size.

    The penumbra (transition zone from light to shadow) encodes the angular
    size of the source as seen from the subject.  Wider penumbra = larger
    apparent source (closer or bigger modifier).

    Returns:
        ok, penumbra_width_px, penumbra_width_ratio, apparent_source_size,
        penumbra_uniformity, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Find shadow edges via Canny on the subject region
    analysis_mask = person_mask
    if analysis_mask is None and face_box is not None:
        analysis_mask = np.zeros((h, w), dtype=np.uint8)
        fx0, fy0, fx1, fy1 = face_box
        analysis_mask[fy0:fy1, fx0:fx1] = 255

    if analysis_mask is None:
        return {"ok": False, "error": "No mask or face_box for penumbra analysis"}

    # Ensure mask is uint8 for OpenCV
    if analysis_mask.dtype == bool:
        analysis_mask = analysis_mask.astype(np.uint8) * 255

    # Apply mask and find edges
    masked_gray = cv2.bitwise_and(gray, gray, mask=analysis_mask)
    edges = cv2.Canny(masked_gray, 30, 100)

    # Get edge points
    edge_ys, edge_xs = np.where(edges > 0)
    if len(edge_ys) < 10:
        return {"ok": False, "error": "Insufficient shadow edges"}

    # Sample perpendicular profiles along shadow edges
    # For each edge point, measure brightness profile perpendicular to gradient
    grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

    widths: List[float] = []
    sample_count = min(50, len(edge_ys))
    indices = np.random.RandomState(42).choice(len(edge_ys), sample_count, replace=False)

    for idx in indices:
        ey, ex = int(edge_ys[idx]), int(edge_xs[idx])
        gx = grad_x[ey, ex]
        gy = grad_y[ey, ex]
        mag = math.sqrt(gx * gx + gy * gy)
        if mag < 1.0:
            continue

        # Normal direction (perpendicular to edge)
        nx, ny = -gy / mag, gx / mag

        # Sample 20 pixels in each direction along normal
        profile = []
        for t in range(-20, 21):
            px = int(round(ex + t * nx))
            py = int(round(ey + t * ny))
            if 0 <= px < w and 0 <= py < h:
                profile.append(float(gray[py, px]))
        if len(profile) < 10:
            continue

        profile = np.array(profile)
        p10 = np.percentile(profile, 10)
        p90 = np.percentile(profile, 90)
        if p90 - p10 < 10:
            continue  # No real transition

        # Width = number of samples where value is between 10th and 90th pctile
        transition = np.sum((profile > p10) & (profile < p90))
        widths.append(float(transition))

    if not widths:
        return {"ok": False, "error": "Could not measure penumbra widths"}

    mean_width = float(np.mean(widths))
    std_width = float(np.std(widths))

    # Normalize to image/subject size
    ref_size = float(max(h, w))
    if face_box is not None:
        ref_size = float(max(face_box[2] - face_box[0], face_box[3] - face_box[1]))
    width_ratio = mean_width / max(ref_size, 1.0)

    # Uniformity (1 = all same width, 0 = wildly variable)
    uniformity = 1.0 - min(1.0, std_width / max(mean_width, 1.0))

    # Map to apparent source size
    apparent_size = "unknown"
    for lo, hi, label in _PENUMBRA_SIZE_MAP:
        if lo <= width_ratio < hi:
            apparent_size = label
            break
    else:
        apparent_size = "very_large"

    notes.append(
        f"Mean penumbra width={mean_width:.1f}px (ratio={width_ratio:.3f}), "
        f"uniformity={uniformity:.2f} → {apparent_size}."
    )

    return {
        "ok": True,
        "penumbra_width_px": round(mean_width, 1),
        "penumbra_width_ratio": round(width_ratio, 4),
        "apparent_source_size": apparent_size,
        "penumbra_uniformity": round(uniformity, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5i. OCCLUSION SHADOW PASS
# ═══════════════════════════════════════════════════════════════════════════


def occlusion_shadow_pass(
    img_bgr: np.ndarray,
    shadow: Optional[Dict[str, Any]] = None,
    background: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Detect foliage or environmental occlusion patterns (gobos, dappled light).

    High-frequency shadow patterns with organic shapes indicate gobo or
    foliage between light source and subject.

    Returns:
        ok, occlusion_detected, occlusion_type, pattern_frequency,
        pattern_regularity, occlusion_confidence, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    # Ensure mask is uint8 for OpenCV bitwise ops (CV 4.13+ rejects bool)
    if person_mask is not None and person_mask.dtype == bool:
        person_mask = person_mask.astype(np.uint8) * 255

    # Analyze shadow pattern on the subject via high-pass filter
    analysis_region = gray.copy()
    if person_mask is not None:
        analysis_region = cv2.bitwise_and(analysis_region, analysis_region,
                                          mask=person_mask)

    # High-pass: subtract blurred version to isolate shadow patterns
    blurred = cv2.GaussianBlur(analysis_region, (31, 31), 0)
    high_pass = cv2.subtract(analysis_region, blurred)
    high_pass = cv2.add(high_pass, 128)  # center at 128

    # FFT for frequency analysis
    if person_mask is not None:
        roi_ys, roi_xs = np.where(person_mask > 0)
        if len(roi_ys) < 100:
            return {"ok": True, "occlusion_detected": False, "occlusion_type": "none",
                    "pattern_frequency": 0.0, "pattern_regularity": 0.0,
                    "occlusion_confidence": 0.0, "notes": ["ROI too small."]}
        ry0, ry1 = int(roi_ys.min()), int(roi_ys.max())
        rx0, rx1 = int(roi_xs.min()), int(roi_xs.max())
        roi = high_pass[ry0:ry1, rx0:rx1]
    else:
        roi = high_pass

    if roi.shape[0] < 32 or roi.shape[1] < 32:
        return {"ok": True, "occlusion_detected": False, "occlusion_type": "none",
                "pattern_frequency": 0.0, "pattern_regularity": 0.0,
                "occlusion_confidence": 0.0, "notes": ["ROI too small for FFT."]}

    # 2D FFT
    f_transform = np.fft.fft2(roi.astype(float))
    f_shift = np.fft.fftshift(f_transform)
    magnitude = np.abs(f_shift)
    magnitude[magnitude.shape[0] // 2, magnitude.shape[1] // 2] = 0  # remove DC

    # Frequency analysis: ratio of high-freq to low-freq energy
    ch, cw = magnitude.shape[0] // 2, magnitude.shape[1] // 2
    low_freq_r = max(ch, cw) // 4
    high_freq_r = max(ch, cw) // 2

    y_grid, x_grid = np.ogrid[:magnitude.shape[0], :magnitude.shape[1]]
    dist = np.sqrt((y_grid - ch) ** 2 + (x_grid - cw) ** 2)

    low_energy = float(np.mean(magnitude[dist <= low_freq_r]))
    high_energy = float(np.mean(magnitude[(dist > low_freq_r) & (dist <= high_freq_r)]))

    freq_ratio = high_energy / max(low_energy, 1e-9)
    pattern_frequency = min(1.0, freq_ratio * 5.0)

    # Regularity: check angular distribution of high-freq energy
    # Regular (blinds) = peaked at specific angles; organic (foliage) = spread
    angular_bins = 18
    angular_hist = np.zeros(angular_bins)
    hf_mask = (dist > low_freq_r) & (dist <= high_freq_r)
    hf_ys, hf_xs = np.where(hf_mask)
    for hy, hx in zip(hf_ys, hf_xs):
        angle = math.atan2(hy - ch, hx - cw)
        bin_idx = int((angle + math.pi) / (2 * math.pi) * angular_bins) % angular_bins
        angular_hist[bin_idx] += magnitude[hy, hx]

    if angular_hist.sum() > 0:
        angular_hist /= angular_hist.sum()
        # Entropy-based regularity: low entropy = regular, high entropy = organic
        entropy = -float(np.sum(angular_hist[angular_hist > 0] *
                                np.log(angular_hist[angular_hist > 0] + 1e-9)))
        max_entropy = math.log(angular_bins)
        regularity = 1.0 - (entropy / max_entropy)
    else:
        regularity = 0.0

    # Classification
    occlusion_detected = pattern_frequency > 0.15
    if not occlusion_detected:
        occlusion_type = "none"
    elif regularity > 0.6:
        occlusion_type = "blinds"
    elif regularity > 0.35:
        occlusion_type = "geometric"
    else:
        occlusion_type = "foliage"

    confidence = min(1.0, pattern_frequency * 2.0) * (0.5 + regularity * 0.5)

    notes.append(
        f"Pattern frequency={pattern_frequency:.2f}, "
        f"regularity={regularity:.2f} → {occlusion_type}."
    )

    return {
        "ok": True,
        "occlusion_detected": occlusion_detected,
        "occlusion_type": occlusion_type,
        "pattern_frequency": round(pattern_frequency, 3),
        "pattern_regularity": round(regularity, 3),
        "occlusion_confidence": round(confidence, 3),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5j. COLOR TEMPERATURE PASS
# ═══════════════════════════════════════════════════════════════════════════

# Approximate CCT from R/B ratio (simplified Planckian locus mapping)
_CCT_RB_MAP = [
    (1.6, 2700),   # warm tungsten
    (1.4, 3200),   # tungsten/halogen
    (1.2, 4000),   # warm fluorescent
    (1.05, 5500),  # daylight
    (0.95, 6500),  # overcast
    (0.85, 7500),  # shade
    (0.7, 9000),   # deep shade/blue
]


def color_temperature_pass(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Detect and estimate color temperatures of visible light sources.

    Analyzes R/G/B channel ratios in highlight and shadow regions to
    estimate CCT.  Multiple distinct CCTs suggest mixed lighting.

    Returns:
        ok, dominant_cct_kelvin, cct_sources, mixed_lighting,
        cct_spread_kelvin, notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    notes: List[str] = []

    def _rb_to_cct(rb_ratio: float) -> int:
        """Convert R/B ratio to approximate CCT in Kelvin."""
        for rb, cct in _CCT_RB_MAP:
            if rb_ratio >= rb:
                return cct
        return 10000

    # Analyze highlight region CCT
    highlight_thresh = np.percentile(gray, 85)
    highlight_mask = gray > highlight_thresh
    if person_mask is not None:
        highlight_mask = highlight_mask & (person_mask > 0)

    # Analyze shadow region CCT
    shadow_thresh = np.percentile(gray, 30)
    shadow_mask = (gray < shadow_thresh) & (gray > 10)
    if person_mask is not None:
        shadow_mask = shadow_mask & (person_mask > 0)

    cct_sources: List[Dict[str, Any]] = []

    for region_name, mask in [("highlight", highlight_mask), ("shadow", shadow_mask)]:
        if not mask.any():
            continue
        r_mean = float(np.mean(img_bgr[:, :, 2][mask]))
        b_mean = float(np.mean(img_bgr[:, :, 0][mask]))
        if b_mean < 1:
            continue
        rb = r_mean / b_mean
        cct = _rb_to_cct(rb)
        pixel_count = int(mask.sum())
        total_pixels = int((person_mask > 0).sum()) if person_mask is not None else h * w
        intensity_pct = round(pixel_count / max(total_pixels, 1) * 100, 1)

        cct_sources.append({
            "cct_kelvin": cct,
            "region": region_name,
            "intensity_pct": intensity_pct,
            "confidence": min(1.0, 0.5 + abs(rb - 1.0) * 0.5),
            "rb_ratio": round(rb, 3),
        })

    # Determine dominant CCT and spread
    if cct_sources:
        # Dominant = highlight CCT (most representative of key light)
        dominant = next((s for s in cct_sources if s["region"] == "highlight"),
                        cct_sources[0])
        dominant_cct = dominant["cct_kelvin"]
        all_ccts = [s["cct_kelvin"] for s in cct_sources]
        cct_spread = max(all_ccts) - min(all_ccts)
        mixed = cct_spread > 1500
    else:
        dominant_cct = 5500  # assume daylight
        cct_spread = 0
        mixed = False
        notes.append("No highlight/shadow regions for CCT — defaulting to daylight.")

    if mixed:
        notes.append(f"Mixed lighting detected: CCT spread={cct_spread}K.")
    notes.append(f"Dominant CCT={dominant_cct}K from {len(cct_sources)} regions.")

    return {
        "ok": True,
        "dominant_cct_kelvin": dominant_cct,
        "cct_sources": cct_sources,
        "mixed_lighting": mixed,
        "cct_spread_kelvin": cct_spread,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5k. ENVIRONMENT LIGHT PASS
# ═══════════════════════════════════════════════════════════════════════════


def environment_light_pass(
    img_bgr: np.ndarray,
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    background: Optional[Dict[str, Any]] = None,
    solar: Optional[Dict[str, Any]] = None,
    window: Optional[Dict[str, Any]] = None,
    bounce: Optional[Dict[str, Any]] = None,
    color_temp: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Classify the overall lighting environment from aggregated signals.

    Synthesizes solar, window, bounce, color temperature, and background
    signals into a unified environment classification.

    Returns:
        ok, environment_class, environment_confidence, indoor_outdoor,
        controlled_lighting, environment_evidence, notes
    """
    notes: List[str] = []
    evidence: List[str] = []

    scores = {
        "studio": 0.0,
        "window_light": 0.0,
        "direct_sun": 0.0,
        "overcast": 0.0,
        "shade": 0.0,
        "mixed": 0.0,
    }

    # Solar signals
    if solar and solar.get("ok"):
        if solar.get("sun_candidate"):
            scores["direct_sun"] += 0.4
            evidence.append("Sun candidate detected (parallel shadows + warmth).")
        par = solar.get("parallel_shadow_score", 0)
        if par > 0.3:
            scores["direct_sun"] += par * 0.2

    # Window signals
    if window and window.get("ok"):
        if window.get("window_candidate"):
            scores["window_light"] += 0.4
            evidence.append("Window light candidate (directional gradient + rect reflections).")
        scores["window_light"] += window.get("window_confidence", 0) * 0.2

    # Bounce signals
    if bounce and bounce.get("ok"):
        fill_ratio = bounce.get("bounce_fill_ratio", 0)
        if fill_ratio > 0.5:
            # Strong bounce suggests large environmental source
            scores["window_light"] += 0.1
            scores["overcast"] += 0.1
            evidence.append(f"Strong bounce fill (ratio={fill_ratio:.2f}).")

    # Color temperature
    if color_temp and color_temp.get("ok"):
        cct = color_temp.get("dominant_cct_kelvin", 5500)
        mixed = color_temp.get("mixed_lighting", False)
        if mixed:
            scores["mixed"] += 0.3
            evidence.append("Mixed color temperatures detected.")
        if cct < 3500:
            scores["studio"] += 0.15  # tungsten studio lights
            evidence.append(f"Warm CCT ({cct}K) suggests tungsten/studio.")
        elif cct > 7000:
            scores["shade"] += 0.2
            scores["overcast"] += 0.15
            evidence.append(f"Cool CCT ({cct}K) suggests shade/overcast.")
        elif 5000 <= cct <= 6500:
            scores["direct_sun"] += 0.05
            scores["window_light"] += 0.05

    # Background signals
    if background and background.get("ok"):
        bg_std = background.get("background_gradient_std", 0)
        bg_mean = background.get("background_mean_luminance", 128)
        if bg_std < 15 and bg_mean < 80:
            scores["studio"] += 0.3
            evidence.append("Dark, even background suggests studio.")
        elif bg_std < 20:
            scores["studio"] += 0.15
            evidence.append("Even background suggests controlled environment.")

    # Shadow softness (from upstream)
    if shadow and shadow.get("ok"):
        softness = shadow.get("shadow_softness", 0.5)
        if softness > 0.7:
            scores["overcast"] += 0.15
            scores["window_light"] += 0.1
        elif softness < 0.2:
            scores["direct_sun"] += 0.1
            scores["studio"] += 0.1

    # Default studio bump if no outdoor signals
    if scores["direct_sun"] < 0.1 and scores["overcast"] < 0.1:
        scores["studio"] += 0.1

    # Determine winner
    best = max(scores, key=scores.get)
    confidence = scores[best]
    confidence = min(1.0, confidence)

    # Indoor/outdoor determination
    if best in ("direct_sun", "overcast", "shade"):
        indoor_outdoor = "outdoor"
    elif best == "studio":
        indoor_outdoor = "indoor"
    elif best == "window_light":
        indoor_outdoor = "indoor"
    else:
        indoor_outdoor = "unknown"

    controlled = best in ("studio",)

    notes.append(f"Environment: {best} (conf={confidence:.2f}), {indoor_outdoor}.")

    return {
        "ok": True,
        "environment_class": best,
        "environment_confidence": round(confidence, 3),
        "indoor_outdoor": indoor_outdoor,
        "controlled_lighting": controlled,
        "environment_evidence": evidence,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6a. MODIFIER SHAPE SOLVER PASS
# ═══════════════════════════════════════════════════════════════════════════

_SHAPE_TO_MODIFIER = {
    "circular": ["octa_softbox", "beauty_dish"],
    "rectangular": ["softbox_rect", "softbox_strip"],
    "strip": ["stripbox", "softbox_strip"],
    "ring": ["ring_light"],
    "point": ["bare_bulb", "zoom_reflector", "fresnel"],
}


def modifier_shape_solver_pass(
    img_bgr: np.ndarray,
    catchlight: Optional[Dict[str, Any]] = None,
    reflection: Optional[Dict[str, Any]] = None,
    specular: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    penumbra: Optional[Dict[str, Any]] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Infer modifier type from reflection geometry and catchlight shape.

    Maps detected reflection shapes to likely modifiers:
        circle/octagon → octa softbox or beauty dish
        rectangle → rectangular softbox
        thin bar → stripbox
        ring → ring light
        point → bare bulb / zoom reflector

    Returns:
        ok, modifier_candidates, primary_modifier, primary_modifier_confidence,
        reflection_regions, notes
    """
    notes: List[str] = []
    candidates: List[Dict[str, Any]] = []

    # 1. From reflection geometry pass
    refl_shape = "unknown"
    if reflection and reflection.get("ok"):
        refl_shape = reflection.get("dominant_reflection_shape", "none")
        if refl_shape in _SHAPE_TO_MODIFIER:
            for mod in _SHAPE_TO_MODIFIER[refl_shape]:
                candidates.append({
                    "modifier_type": mod,
                    "shape_evidence": f"reflection_{refl_shape}",
                    "confidence": 0.5,
                })
            notes.append(f"Reflection shape '{refl_shape}' suggests {_SHAPE_TO_MODIFIER[refl_shape]}.")

    # 2. From catchlight shape (existing pass)
    if catchlight and catchlight.get("ok"):
        cl_shape = catchlight.get("catchlight_shape", "unknown")
        if isinstance(cl_shape, str) and cl_shape != "unknown":
            shape_map = {
                "round": "circular",
                "circular": "circular",
                "octagonal": "circular",
                "rectangular": "rectangular",
                "square": "rectangular",
                "elongated": "strip",
                "ring": "ring",
            }
            mapped = shape_map.get(cl_shape.lower(), "")
            if mapped and mapped in _SHAPE_TO_MODIFIER:
                for mod in _SHAPE_TO_MODIFIER[mapped]:
                    # Check if already in candidates
                    existing = [c for c in candidates if c["modifier_type"] == mod]
                    if existing:
                        existing[0]["confidence"] = min(1.0, existing[0]["confidence"] + 0.3)
                        existing[0]["shape_evidence"] += f"+catchlight_{cl_shape}"
                    else:
                        candidates.append({
                            "modifier_type": mod,
                            "shape_evidence": f"catchlight_{cl_shape}",
                            "confidence": 0.4,
                        })
                notes.append(f"Catchlight shape '{cl_shape}' → modifier evidence.")

    # 3. Penumbra evidence
    if penumbra and penumbra.get("ok"):
        src_size = penumbra.get("apparent_source_size", "unknown")
        if src_size in ("large", "very_large"):
            # Boost softbox/octa candidates
            for c in candidates:
                if "softbox" in c["modifier_type"] or "octa" in c["modifier_type"]:
                    c["confidence"] = min(1.0, c["confidence"] + 0.15)
            notes.append(f"Large apparent source ({src_size}) supports soft modifier.")
        elif src_size in ("point", "small"):
            # Boost bare_bulb/fresnel candidates
            for c in candidates:
                if "bare" in c["modifier_type"] or "fresnel" in c["modifier_type"]:
                    c["confidence"] = min(1.0, c["confidence"] + 0.15)
            notes.append(f"Small apparent source ({src_size}) supports hard modifier.")

    # Sort by confidence
    candidates.sort(key=lambda c: c["confidence"], reverse=True)

    primary = candidates[0]["modifier_type"] if candidates else "unknown"
    primary_conf = candidates[0]["confidence"] if candidates else 0.0

    refl_regions = []
    if reflection and reflection.get("ok"):
        refl_regions = reflection.get("reflection_regions", [])

    return {
        "ok": True,
        "modifier_candidates": candidates,
        "primary_modifier": primary,
        "primary_modifier_confidence": round(primary_conf, 3),
        "reflection_regions": refl_regions,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6b. LIGHTING HYPOTHESIS ENGINE
# ═══════════════════════════════════════════════════════════════════════════

_HYPOTHESIS_LIGHT_ROLES = [
    "key", "fill", "negative_fill", "rim", "kicker",
    "background", "bounce", "unknown_secondary",
]


def lighting_hypothesis_engine(
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    catchlight: Optional[Dict[str, Any]] = None,
    background: Optional[Dict[str, Any]] = None,
    specular: Optional[Dict[str, Any]] = None,
    pose_solver: Optional[Dict[str, Any]] = None,
    surface_class: Optional[Dict[str, Any]] = None,
    light_direction_field: Optional[Dict[str, Any]] = None,
    inverse_square: Optional[Dict[str, Any]] = None,
    solar: Optional[Dict[str, Any]] = None,
    window: Optional[Dict[str, Any]] = None,
    bounce_geo: Optional[Dict[str, Any]] = None,
    reflection: Optional[Dict[str, Any]] = None,
    penumbra: Optional[Dict[str, Any]] = None,
    occlusion: Optional[Dict[str, Any]] = None,
    color_temp: Optional[Dict[str, Any]] = None,
    environment: Optional[Dict[str, Any]] = None,
    modifier_shape: Optional[Dict[str, Any]] = None,
    # For backward compat — accept same args as light_role_pass
    img_bgr: Optional[np.ndarray] = None,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Generate candidate lighting setups from all extracted signals.

    Combines all upstream passes to build 1-5 candidate lighting hypotheses.
    Each hypothesis describes a complete lighting setup.

    This pass SUBSUMES the role of the old light_role_pass.  It produces
    all backward-compatible keys (likely_light_count, roles, etc.) plus
    new structured hypothesis objects.

    Returns:
        ok, hypotheses, best_hypothesis_index,
        likely_light_count, light_count_confidence, roles,
        multi_light_evidence_score, false_multi_light_risk, light_role_notes,
        notes
    """
    notes: List[str] = []
    shd = shadow or {}
    hlt = highlight or {}
    cat = catchlight or {}
    bg = background or {}
    spec = specular or {}
    pose = pose_solver or {}
    surf = surface_class or {}
    ldf = light_direction_field or {}
    isq = inverse_square or {}
    sol = solar or {}
    win = window or {}
    bnc = bounce_geo or {}
    refl = reflection or {}
    pen = penumbra or {}
    occ = occlusion or {}
    ct = color_temp or {}
    env = environment or {}
    mod = modifier_shape or {}

    # ── Key light analysis ──
    key_direction_deg = shd.get("shadow_vector_deg", 0.0)
    if ldf.get("ok") and ldf.get("vector_consistency", 0) > 0.5:
        key_direction_deg = ldf.get("dominant_light_vector_deg", key_direction_deg)

    key_height = "eye_level"
    if shd.get("ok") and shd.get("shadow_vertical_angle_deg") is not None:
        vert = shd.get("shadow_vertical_angle_deg", 0)
        if vert > 20:
            key_height = "high"
        elif vert < -10:
            key_height = "low"

    key_distance = isq.get("distance_estimate_ft", 6.0) if isq.get("ok") else 6.0
    key_modifier = mod.get("primary_modifier", "unknown") if mod.get("ok") else "unknown"
    key_cct = ct.get("dominant_cct_kelvin", 5500) if ct.get("ok") else 5500

    env_class = env.get("environment_class", "unknown") if env.get("ok") else "unknown"

    # ── Role detection (backward compat with light_role_pass) ──
    roles: Dict[str, Dict[str, Any]] = {}
    for role in _HYPOTHESIS_LIGHT_ROLES:
        roles[role] = {"present": False, "confidence": 0.0, "evidence": []}

    # Key is always present
    roles["key"]["present"] = True
    roles["key"]["confidence"] = 0.9
    roles["key"]["evidence"].append("Primary light source assumed.")

    # Fill detection
    fill_conf = 0.0
    hw_ratio = hlt.get("highlight_width_ratio", 0) if hlt.get("ok") else 0
    if hw_ratio > 0.65:
        fill_conf += 0.3
        roles["fill"]["evidence"].append(f"Wide highlights (ratio={hw_ratio:.2f}).")
    cl_count = cat.get("catchlight_count", 0) if cat.get("ok") else 0
    if cl_count >= 2:
        fill_conf += 0.35
        roles["fill"]["evidence"].append(f"{cl_count} catchlights detected.")
    if bnc.get("ok") and bnc.get("bounce_fill_ratio", 0) > 0.4:
        fill_conf += 0.15
        roles["fill"]["evidence"].append("Bounce fill detected.")
    roles["fill"]["present"] = fill_conf > 0.3
    roles["fill"]["confidence"] = min(1.0, fill_conf)

    # Negative fill
    neg_fill_conf = 0.0
    if hw_ratio < 0.3 and hw_ratio > 0:
        neg_fill_conf += 0.3
    shadow_softness = shd.get("shadow_softness", 0.5) if shd.get("ok") else 0.5
    if shadow_softness < 0.3:
        neg_fill_conf += 0.2
    if cl_count <= 1:
        neg_fill_conf += 0.15
    roles["negative_fill"]["present"] = neg_fill_conf > 0.4 and not roles["fill"]["present"]
    roles["negative_fill"]["confidence"] = min(1.0, neg_fill_conf)

    # Rim/kicker from specular surface pass
    if spec.get("ok"):
        if spec.get("has_rim"):
            roles["rim"]["present"] = True
            rim_ratio = spec.get("rim_brightness_ratio", 0)
            roles["rim"]["confidence"] = min(1.0, 0.4 + rim_ratio * 0.3)
            roles["rim"]["evidence"].append(f"Edge brightness ratio={rim_ratio:.2f}.")
        if spec.get("has_kicker"):
            roles["kicker"]["present"] = True
            roles["kicker"]["confidence"] = 0.5
            roles["kicker"]["evidence"].append("Both edges bright — kicker detected.")

    # Background light
    bg_grad = bg.get("background_gradient_spread", 0) if bg.get("ok") else 0
    bg_int = bg.get("background_intensity_ratio", 0) if bg.get("ok") else 0
    if bg_grad > 0.3 and bg_int > 0.4:
        roles["background"]["present"] = True
        roles["background"]["confidence"] = min(1.0, 0.3 + bg_grad * 0.3 + bg_int * 0.2)
        roles["background"]["evidence"].append(f"BG gradient={bg_grad:.2f}, intensity={bg_int:.2f}.")

    # Bounce
    if bnc.get("ok") and bnc.get("bounce_sources"):
        roles["bounce"]["present"] = True
        roles["bounce"]["confidence"] = min(1.0, bnc.get("bounce_fill_ratio", 0) * 1.5)
        roles["bounce"]["evidence"].append("Bounce sources detected.")

    # ── Light count ──
    active_roles = [r for r, info in roles.items() if info["present"]]
    multi_evidence = 0.0
    false_risk = 0.0

    if cl_count >= 2:
        multi_evidence += 0.35
    if roles["rim"]["present"]:
        multi_evidence += 0.25
    if roles["background"]["present"]:
        multi_evidence += 0.2
    if roles["fill"]["present"] and cl_count >= 2:
        multi_evidence += 0.2

    # False multi-light risk
    if surf.get("ok"):
        bias = surf.get("global_surface_bias", "")
        if bias in ("metallic", "chrome_like", "glass"):
            false_risk += 0.3
        complexity = surf.get("surface_complexity_score", 0)
        if complexity > 0.5:
            false_risk += 0.2
    if pose.get("ok") and pose.get("pose_shadow_interference"):
        false_risk += 0.1

    adjusted = multi_evidence - false_risk * 0.5
    if adjusted < 0.2:
        light_count = "one"
    elif adjusted < 0.45:
        light_count = "two"
    elif adjusted < 0.7:
        light_count = "three"
    else:
        light_count = "multi"

    count_confidence = min(1.0, 0.4 + abs(adjusted) * 0.8)

    # ── Build hypotheses ──
    hypotheses: List[Dict[str, Any]] = []

    # Primary hypothesis from all signals
    primary_lights = [
        {
            "role": "key",
            "direction_deg": round(key_direction_deg, 1),
            "height": key_height,
            "distance_ft": round(key_distance, 1),
            "modifier": key_modifier,
            "color_temp_k": key_cct,
        }
    ]

    if roles["fill"]["present"]:
        fill_dir = key_direction_deg + 180  # opposite key
        if fill_dir > 360:
            fill_dir -= 360
        primary_lights.append({
            "role": "fill",
            "direction_deg": round(fill_dir, 1),
            "height": "eye_level",
            "distance_ft": round(key_distance * 1.5, 1),
            "modifier": "unknown",
            "color_temp_k": key_cct,
        })

    if roles["rim"]["present"]:
        rim_dir = key_direction_deg + 135
        if rim_dir > 360:
            rim_dir -= 360
        primary_lights.append({
            "role": "rim",
            "direction_deg": round(rim_dir, 1),
            "height": "high",
            "distance_ft": round(key_distance, 1),
            "modifier": "unknown",
            "color_temp_k": key_cct,
        })

    if roles["background"]["present"]:
        primary_lights.append({
            "role": "background",
            "direction_deg": 180.0,
            "height": "eye_level",
            "distance_ft": 10.0,
            "modifier": "unknown",
            "color_temp_k": key_cct,
        })

    primary_hypothesis = {
        "lights": primary_lights,
        "environment": env_class,
        "confidence": round(count_confidence * 0.8, 3),
        "evidence": [f"{r}: {roles[r]['evidence']}" for r in active_roles if roles[r]["evidence"]],
    }
    hypotheses.append(primary_hypothesis)

    # Natural light alternative (if sun/window detected)
    if sol.get("sun_candidate") or win.get("window_candidate"):
        nat_lights = [{
            "role": "key",
            "direction_deg": round(sol.get("sun_azimuth_deg", key_direction_deg) or key_direction_deg, 1),
            "height": "high" if sol.get("sun_candidate") else key_height,
            "distance_ft": 999.0,  # natural source
            "modifier": "sun" if sol.get("sun_candidate") else "window",
            "color_temp_k": ct.get("dominant_cct_kelvin", 5500) if ct.get("ok") else 5500,
        }]
        nat_hypothesis = {
            "lights": nat_lights,
            "environment": "direct_sun" if sol.get("sun_candidate") else "window_light",
            "confidence": round(max(sol.get("parallel_shadow_score", 0),
                                    win.get("window_confidence", 0)) * 0.8, 3),
            "evidence": ["Natural light source detected."],
        }
        hypotheses.append(nat_hypothesis)

    light_role_notes = [f"Light count: {light_count} (conf={count_confidence:.2f})"]
    for r, info in roles.items():
        if info["present"]:
            light_role_notes.append(f"{r}: conf={info['confidence']:.2f}")

    return {
        "ok": True,
        "hypotheses": hypotheses,
        "best_hypothesis_index": 0,
        # Backward compat keys (same as light_role_pass)
        "likely_light_count": light_count,
        "light_count_confidence": round(count_confidence, 3),
        "roles": roles,
        "multi_light_evidence_score": round(multi_evidence, 3),
        "false_multi_light_risk": round(false_risk, 3),
        "light_role_notes": light_role_notes,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6c. PHYSICS CONSISTENCY ENGINE
# ═══════════════════════════════════════════════════════════════════════════


def physics_consistency_engine(
    hypotheses: Optional[Dict[str, Any]] = None,
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    catchlight: Optional[Dict[str, Any]] = None,
    specular: Optional[Dict[str, Any]] = None,
    light_direction_field: Optional[Dict[str, Any]] = None,
    inverse_square: Optional[Dict[str, Any]] = None,
    penumbra: Optional[Dict[str, Any]] = None,
    color_temp: Optional[Dict[str, Any]] = None,
    reflection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score hypotheses against physical constraints.

    For each hypothesis, checks:
    - Shadow alignment: shadow direction vs predicted light position
    - Highlight axis: highlight axis vs light direction
    - Catchlight geometry: shape vs hypothesized modifier
    - Falloff consistency: measured falloff vs hypothesized distance
    - Reflection geometry: reflection shapes vs modifier hypothesis
    - Penumbra width: penumbra vs source size hypothesis
    - Color temperature: detected CCT vs source type

    Returns:
        ok, scored_hypotheses, best_hypothesis_index, best_physics_score,
        violation_summary, notes
    """
    notes: List[str] = []

    # Accept either a list of hypotheses or a dict with a "hypotheses" key
    if isinstance(hypotheses, list):
        hyp_list = hypotheses
    elif isinstance(hypotheses, dict):
        hyp_list = hypotheses.get("hypotheses", [])
    else:
        hyp_list = []

    if not hyp_list:
        return {
            "ok": True,
            "scored_hypotheses": [],
            "best_hypothesis_index": 0,
            "best_physics_score": 0.5,
            "violation_summary": [],
            "notes": ["No hypotheses provided."],
        }

    shd = shadow or {}
    hlt = highlight or {}
    cat = catchlight or {}
    spec = specular or {}
    ldf = light_direction_field or {}
    isq = inverse_square or {}
    pen = penumbra or {}
    ct = color_temp or {}
    refl = reflection or {}

    scored: List[Dict[str, Any]] = []

    for i, hyp in enumerate(hyp_list):
        checks: Dict[str, float] = {}
        violations: List[str] = []
        lights = hyp.get("lights", [])

        if not lights:
            scored.append({"hypothesis": hyp, "physics_score": 0.0,
                           "violations": ["No lights in hypothesis."], "checks": {}})
            continue

        key_light = lights[0]
        key_dir = key_light.get("direction_deg", 0)
        key_dist = key_light.get("distance_ft", 6)
        key_mod = key_light.get("modifier", "unknown")

        # Check 1: Shadow alignment
        if shd.get("ok") and shd.get("shadow_vector_deg") is not None:
            shadow_dir = shd["shadow_vector_deg"]
            # Shadow should be ~180° from light.
            # shadow_vector_deg is now in VLM convention (0=down=butterfly baseline),
            # so expected_shadow = key_dir (not key_dir + 180; the +180 is already baked in).
            expected_shadow = key_dir % 360.0
            diff = abs(shadow_dir - expected_shadow)
            if diff > 180:
                diff = 360 - diff
            alignment = max(0.0, 1.0 - diff / 90.0)
            checks["shadow_alignment"] = round(alignment, 3)
            if alignment < 0.3:
                violations.append(f"Shadow direction ({shadow_dir:.0f}°) inconsistent with key ({key_dir:.0f}°).")

        # Check 2: Highlight axis
        if hlt.get("ok") and hlt.get("highlight_axis_deg") is not None:
            hl_axis = hlt["highlight_axis_deg"]
            diff = abs(hl_axis - key_dir)
            if diff > 180:
                diff = 360 - diff
            hl_alignment = max(0.0, 1.0 - diff / 60.0)
            checks["highlight_axis"] = round(hl_alignment, 3)

        # Check 3: Catchlight geometry
        if cat.get("ok"):
            cl_shape = str(cat.get("catchlight_shape", "unknown")).lower()
            mod_lower = key_mod.lower()
            shape_match = 0.5  # neutral
            if "softbox" in mod_lower and cl_shape in ("rectangular", "square"):
                shape_match = 1.0
            elif "octa" in mod_lower and cl_shape in ("circular", "octagonal", "round"):
                shape_match = 1.0
            elif "ring" in mod_lower and cl_shape == "ring":
                shape_match = 1.0
            elif "bare" in mod_lower and cl_shape == "point":
                shape_match = 0.8
            elif cl_shape == "unknown":
                shape_match = 0.5
            checks["catchlight_geometry"] = round(shape_match, 3)

        # Check 4: Falloff consistency
        if isq.get("ok") and isq.get("distance_estimate_ft") is not None:
            est_dist = isq["distance_estimate_ft"]
            ratio = min(est_dist, key_dist) / max(est_dist, key_dist, 0.1)
            checks["falloff_consistency"] = round(ratio, 3)
            if ratio < 0.4:
                violations.append(
                    f"Estimated distance ({est_dist:.1f}ft) differs from "
                    f"hypothesis ({key_dist:.1f}ft)."
                )

        # Check 5: Penumbra width
        if pen.get("ok"):
            src_size = pen.get("apparent_source_size", "unknown")
            size_match = 0.5
            if "softbox" in key_mod or "octa" in key_mod:
                if src_size in ("large", "very_large"):
                    size_match = 1.0
                elif src_size == "medium":
                    size_match = 0.7
                else:
                    size_match = 0.3
            elif "bare" in key_mod or "fresnel" in key_mod:
                if src_size in ("point", "small"):
                    size_match = 1.0
                elif src_size == "medium":
                    size_match = 0.6
                else:
                    size_match = 0.3
            checks["penumbra_width"] = round(size_match, 3)

        # Check 6: Color temperature
        if ct.get("ok"):
            detected_cct = ct.get("dominant_cct_kelvin", 5500)
            hyp_cct = key_light.get("color_temp_k", 5500)
            cct_diff = abs(detected_cct - hyp_cct)
            cct_score = max(0.0, 1.0 - cct_diff / 3000.0)
            checks["color_temperature"] = round(cct_score, 3)

        # Check 7: Direction field consistency
        if ldf.get("ok") and ldf.get("vector_consistency", 0) > 0:
            checks["direction_field"] = round(ldf["vector_consistency"], 3)

        # Aggregate score
        if checks:
            physics_score = float(np.mean(list(checks.values())))
        else:
            physics_score = 0.5  # no data to check

        scored.append({
            "hypothesis": hyp,
            "physics_score": round(physics_score, 3),
            "violations": violations,
            "checks": checks,
        })

    # Find best
    best_idx = 0
    best_score = 0.0
    for i, s in enumerate(scored):
        if s["physics_score"] > best_score:
            best_score = s["physics_score"]
            best_idx = i

    all_violations = []
    for s in scored:
        all_violations.extend(s["violations"])

    notes.append(f"Scored {len(scored)} hypotheses, best={best_idx} (score={best_score:.3f}).")

    return {
        "ok": True,
        "scored_hypotheses": scored,
        "best_hypothesis_index": best_idx,
        "best_physics_score": round(best_score, 3),
        "violation_summary": all_violations,
        "notes": notes,
    }


def light_role_pass(
    img_bgr: np.ndarray,
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    catchlight: Optional[Dict[str, Any]] = None,
    background: Optional[Dict[str, Any]] = None,
    specular: Optional[Dict[str, Any]] = None,
    pose_solver: Optional[Dict[str, Any]] = None,
    surface_class: Optional[Dict[str, Any]] = None,
    person_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Estimate likely light count and assign roles to detected light sources.

    Synthesises all upstream signals to determine how many lights are
    present and what role each plays.  Specifically detects false
    multi-light signals from spill, bounce, and reflective surfaces.

    IMPORTANT: This pass does NOT determine final lighting setup —
    the NGW rule engine makes that determination.

    Returns:
        ok, likely_light_count, light_count_confidence,
        roles (dict per role), multi_light_evidence_score,
        false_multi_light_risk, light_role_notes
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not available"}

    shd = shadow or {}
    hlt = highlight or {}
    cat = catchlight or {}
    bg = background or {}
    spec = specular or {}
    pose = pose_solver or {}
    surf = surface_class or {}

    notes: List[str] = []

    # Initialise roles
    roles: Dict[str, Dict[str, Any]] = {}
    for role in _LIGHT_ROLES:
        roles[role] = {"present": False, "confidence": 0.0, "evidence": []}

    # ── A. Key light (always assumed present) ───────────────────────────
    roles["key"]["present"] = True
    roles["key"]["confidence"] = 0.9
    key_evidence: List[str] = []
    if shd.get("shadow_vector_deg") is not None:
        key_evidence.append("shadow_vector")
    if cat.get("catchlight_position"):
        key_evidence.append("primary_catchlight")
    roles["key"]["evidence"] = key_evidence or ["assumed"]

    # ── B. Edge highlights for rim / kicker ─────────────────────────────
    edge_info = _detect_edge_highlights(img_bgr, person_mask, face_box)
    has_rim = edge_info["has_rim"]
    has_kicker = edge_info["has_kicker"]

    if has_rim:
        roles["rim"]["present"] = True
        roles["rim"]["confidence"] = min(0.85, 0.4 + edge_info["rim_brightness_ratio"] * 0.2)
        roles["rim"]["evidence"] = [
            f"edge_brightness_{edge_info['rim_side']}",
            f"ratio={edge_info['rim_brightness_ratio']}",
        ]
        notes.append(f"rim detected on {edge_info['rim_side']} side")

    if has_kicker:
        roles["kicker"]["present"] = True
        roles["kicker"]["confidence"] = 0.5
        roles["kicker"]["evidence"] = ["both_edges_bright"]
        notes.append("possible kicker: both edges brighter than interior")

    # ── C. Fill detection ───────────────────────────────────────────────
    hlt_width = hlt.get("highlight_width_ratio")
    cat_count = cat.get("catchlight_count", 0)
    cat_pos = cat.get("catchlight_position", "")

    fill_with_catchlight = False
    if hlt_width is not None and hlt_width > 0.65:
        roles["fill"]["present"] = True
        fill_evidence = [f"highlight_width={hlt_width:.2f}"]
        fill_conf = 0.6

        # Secondary catchlight confirms fill
        if cat_count >= 2:
            fill_with_catchlight = True
            fill_conf = 0.85
            fill_evidence.append("secondary_catchlight")

        roles["fill"]["confidence"] = fill_conf
        roles["fill"]["evidence"] = fill_evidence
        notes.append("fill detected from broad highlight width")

    # ── D. Negative fill ────────────────────────────────────────────────
    if hlt_width is not None and hlt_width < 0.3:
        shd_softness = shd.get("shadow_softness", 0.5)
        if shd_softness < 0.3 and cat_count < 2:
            roles["negative_fill"]["present"] = True
            roles["negative_fill"]["confidence"] = 0.65
            roles["negative_fill"]["evidence"] = [
                f"narrow_highlight={hlt_width:.2f}",
                f"hard_shadows={shd_softness:.2f}",
                "no_secondary_catchlight",
            ]
            notes.append("negative fill: narrow highlight + hard shadows")

    # ── E. Background light ─────────────────────────────────────────────
    bg_spread = bg.get("background_gradient_spread", 0.0)
    bg_intensity = bg.get("background_intensity_ratio", 0.0)
    bg_direction = bg.get("background_direction", "")

    bg_light_independent = False
    if bg_spread > 0.3 and bg_intensity > 0.4:
        roles["background"]["present"] = True
        bg_evidence = [f"spread={bg_spread:.2f}", f"intensity={bg_intensity:.2f}"]
        bg_conf = 0.6

        # Check if bg illumination axis is independent from key
        shd_vector = shd.get("shadow_vector_deg")
        if shd_vector is not None and bg_direction:
            # Simple heuristic: bg gradient direction vs key shadow direction
            bg_light_independent = True
            bg_conf = 0.75
            bg_evidence.append("independent_axis")

        roles["background"]["confidence"] = bg_conf
        roles["background"]["evidence"] = bg_evidence

    # ── F. Bounce detection ─────────────────────────────────────────────
    if (hlt_width is not None and 0.5 < hlt_width < 0.7
            and cat_count < 2
            and shd.get("shadow_edge_gradient", 0) > 0.4):
        roles["bounce"]["present"] = True
        roles["bounce"]["confidence"] = 0.45
        roles["bounce"]["evidence"] = [
            "moderate_highlight_width",
            "no_secondary_catchlight",
            "soft_shadow_edge",
        ]
        notes.append("possible bounce fill (soft fill without secondary catchlight)")

    # ── G. False multi-light risk ───────────────────────────────────────
    false_multi_light_risk = 0.0

    # Reflective wardrobe
    if surf.get("ok"):
        reflection_regions = surf.get("reflection_dominant_regions", [])
        if reflection_regions:
            false_multi_light_risk += 0.3
            notes.append(f"false-multi-light risk: reflective regions {reflection_regions}")
        bias = surf.get("global_surface_bias", "")
        if bias in ("chrome_like", "glass", "metallic"):
            false_multi_light_risk += 0.2
            notes.append(f"false-multi-light risk: global surface bias is {bias}")

    # Pose self-shadow
    if pose.get("ok") and pose.get("pose_shadow_interference"):
        false_multi_light_risk += 0.1
        notes.append("false-multi-light risk: pose shadow interference")

    # Spill from key matching bg gradient
    if bg_spread > 0.2 and not bg_light_independent:
        spill_risk = min(0.2, bg_spread * 0.3)
        false_multi_light_risk += spill_risk

    false_multi_light_risk = min(1.0, false_multi_light_risk)

    # ── H. Multi-light evidence score ───────────────────────────────────
    multi_light_evidence = 0.0

    # Distinct secondary catchlight
    if cat_count >= 2:
        multi_light_evidence += 0.35

    # Separate edge highlight (rim)
    if has_rim:
        multi_light_evidence += 0.25

    # Independent background illumination
    if bg_light_independent:
        multi_light_evidence += 0.2

    # Fill present with catchlight confirmation
    if fill_with_catchlight:
        multi_light_evidence += 0.2

    multi_light_evidence = min(1.0, multi_light_evidence)

    # ── I. Light count determination ────────────────────────────────────
    adjusted_evidence = multi_light_evidence - (false_multi_light_risk * 0.5)
    adjusted_evidence = max(0.0, adjusted_evidence)

    if adjusted_evidence < 0.2:
        likely_count = "one"
    elif adjusted_evidence < 0.45:
        likely_count = "two"
    elif adjusted_evidence < 0.7:
        likely_count = "three"
    else:
        likely_count = "multi"

    count_confidence = max(0.3, 1.0 - false_multi_light_risk * 0.5)

    return {
        "ok": True,
        "likely_light_count": likely_count,
        "light_count_confidence": round(count_confidence, 3),
        "roles": roles,
        "multi_light_evidence_score": round(multi_light_evidence, 3),
        "false_multi_light_risk": round(false_multi_light_risk, 3),
        "light_role_notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. RECONSTRUCTION PASS (UPDATED)
# ═══════════════════════════════════════════════════════════════════════════

# Surface response profiles: how each surface class affects signal interpretation
_SURFACE_RESPONSE_PROFILES: Dict[str, Dict[str, Any]] = {
    "face_skin": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": 0.0,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 1.0,
        "highlight_reliability": 0.9,
        "preferred_signals": ["catchlight", "highlight_rolloff", "shadow"],
        "reflection_dominant": False,
    },
    "matte_fabric": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.15,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 1.0,
        "highlight_reliability": 0.6,
        "preferred_signals": ["shadow", "background"],
        "reflection_dominant": False,
    },
    "satin_silk": {
        "highlight_width_correction": -0.15,
        "rolloff_correction": 0.1,
        "specularity_correction": -0.1,
        "specular_spread_correction": -0.1,
        "shadow_reliability": 0.8,
        "highlight_reliability": 0.5,
        "preferred_signals": ["catchlight", "shadow", "background"],
        "reflection_dominant": False,
    },
    "leather": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.2,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.9,
        "highlight_reliability": 0.6,
        "preferred_signals": ["shadow", "catchlight"],
        "reflection_dominant": False,
    },
    "metallic": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.3,
        "specular_spread_correction": -0.2,
        "shadow_reliability": 0.5,
        "highlight_reliability": 0.3,
        "preferred_signals": ["catchlight", "background"],
        "reflection_dominant": True,
    },
    "chrome_like": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.4,
        "specular_spread_correction": -0.3,
        "shadow_reliability": 0.3,
        "highlight_reliability": 0.2,
        "preferred_signals": ["catchlight"],
        "reflection_dominant": True,
    },
    "glass": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.3,
        "specular_spread_correction": -0.2,
        "shadow_reliability": 0.4,
        "highlight_reliability": 0.3,
        "preferred_signals": ["catchlight", "background"],
        "reflection_dominant": True,
    },
    "skin_sheen": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": 0.0,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.9,
        "highlight_reliability": 0.85,
        "preferred_signals": ["catchlight", "highlight_rolloff"],
        "reflection_dominant": False,
    },
    "semi_gloss_fabric": {
        "highlight_width_correction": -0.05,
        "rolloff_correction": 0.05,
        "specularity_correction": -0.1,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.85,
        "highlight_reliability": 0.65,
        "preferred_signals": ["shadow", "catchlight", "highlight_rolloff"],
        "reflection_dominant": False,
    },
    "hair": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.1,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.7,
        "highlight_reliability": 0.5,
        "preferred_signals": ["catchlight", "shadow"],
        "reflection_dominant": False,
    },
    "body_skin": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": 0.0,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 1.0,
        "highlight_reliability": 0.85,
        "preferred_signals": ["catchlight", "highlight_rolloff", "shadow"],
        "reflection_dominant": False,
    },
    "background_paper": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": 0.0,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.7,
        "highlight_reliability": 0.5,
        "preferred_signals": ["background"],
        "reflection_dominant": False,
    },
    "background_painted_wall": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": 0.0,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.7,
        "highlight_reliability": 0.5,
        "preferred_signals": ["background"],
        "reflection_dominant": False,
    },
    "matte_skin": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": -0.1,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 1.0,
        "highlight_reliability": 0.7,
        "preferred_signals": ["shadow", "catchlight"],
        "reflection_dominant": False,
    },
    "unknown": {
        "highlight_width_correction": 0.0,
        "rolloff_correction": 0.0,
        "specularity_correction": 0.0,
        "specular_spread_correction": 0.0,
        "shadow_reliability": 0.7,
        "highlight_reliability": 0.7,
        "preferred_signals": ["catchlight", "shadow", "highlight_rolloff"],
        "reflection_dominant": False,
    },
}

# Confidence weights for signal sources
_SIGNAL_WEIGHTS = {
    "catchlights": 0.95,        # HIGH confidence
    "highlight_rolloff": 0.90,  # HIGH confidence
    "shadow_vector": 0.70,      # MEDIUM confidence
    "background_gradient": 0.65, # MEDIUM confidence
    "specular_surface": 0.65,   # MEDIUM confidence
}

# Modifier size estimation from shadow edge gradient + highlight rolloff
_MODIFIER_SIZE_BREAKPOINTS = [
    (0.0, 0.2, "small"),    # Very hard edges → small source
    (0.2, 0.45, "medium"),  # Moderate edges → medium source
    (0.45, 0.7, "large"),   # Soft edges → large source
    (0.7, 1.0, "very_large"),  # Very soft → very large source
]


def reconstruction_pass(
    geometry: Optional[Dict[str, Any]] = None,
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    catchlight: Optional[Dict[str, Any]] = None,
    background: Optional[Dict[str, Any]] = None,
    specular: Optional[Dict[str, Any]] = None,
    pose_solver: Optional[Dict[str, Any]] = None,
    surface_class: Optional[Dict[str, Any]] = None,
    light_role: Optional[Dict[str, Any]] = None,
    # ── New v2 pass inputs (all optional for backward compat) ──
    light_direction_field: Optional[Dict[str, Any]] = None,
    inverse_square: Optional[Dict[str, Any]] = None,
    solar: Optional[Dict[str, Any]] = None,
    window: Optional[Dict[str, Any]] = None,
    bounce: Optional[Dict[str, Any]] = None,
    reflection: Optional[Dict[str, Any]] = None,
    penumbra: Optional[Dict[str, Any]] = None,
    occlusion: Optional[Dict[str, Any]] = None,
    color_temp: Optional[Dict[str, Any]] = None,
    environment: Optional[Dict[str, Any]] = None,
    modifier_shape: Optional[Dict[str, Any]] = None,
    hypothesis: Optional[Dict[str, Any]] = None,
    physics: Optional[Dict[str, Any]] = None,
    existing_catchlights: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Combine all pass signals to estimate lighting setup parameters.

    Uses confidence-weighted merging when signals conflict.
    Priority: catchlights > highlight_rolloff > shadow_vector > background > specular

    When pose_solver data is available, produces BOTH raw and pose-corrected
    key light angles.  Self-shadow regions identified by the pose solver
    suppress those shadow/highlight signals rather than treating them as
    lighting cues.

    When surface_class data is available, applies surface response profile
    corrections to modifier size estimation.

    When light_role data is available, can override fill/negative_fill/
    background_light determinations with higher-confidence estimates.

    Returns estimates for:
        key_light_angle_deg_raw, key_light_angle_deg_pose_corrected,
        key_light_angle_deg (alias for pose-corrected when available),
        key_light_height, modifier_size_class, modifier_size_class_raw,
        modifier_size_class_surface_corrected, modifier_certainty,
        modifier_distance_ft, fill_present, negative_fill,
        background_light, background_distance_ft,
        camera_height_relative_to_subject,
        pose_complexity_score, likely_light_count, light_roles
    """
    geo = geometry or {}
    shd = shadow or {}
    hlt = highlight or {}
    cat = catchlight or {}
    bg = background or {}
    spec = specular or {}
    pose = pose_solver or {}
    surf = surface_class or {}
    lr = light_role or {}

    notes: List[str] = []
    has_pose = pose.get("ok", False)
    has_surface = surf.get("ok", False)
    has_light_role = lr.get("ok", False)

    # ── Surface response profile lookup ─────────────────────────────────
    surface_bias = surf.get("global_surface_bias", "unknown") if has_surface else "unknown"
    surface_profile = _SURFACE_RESPONSE_PROFILES.get(
        surface_bias, _SURFACE_RESPONSE_PROFILES["unknown"]
    )
    if has_surface and surface_profile["reflection_dominant"]:
        notes.append(
            f"reflection-dominant surface ({surface_bias}): "
            "highlight/shadow signals less reliable"
        )

    # ── Self-shadow suppression ─────────────────────────────────────────
    # When the pose solver identifies self-shadow regions, those shadow
    # signals are artifacts of body pose, NOT lighting direction.
    # We reduce shadow weight when pose-induced interference is detected.
    shadow_weight_modifier = 1.0
    if has_pose:
        self_shadow_regions = pose.get("self_shadow_regions", [])
        if pose.get("pose_shadow_interference"):
            shadow_weight_modifier = 0.5
            notes.append(
                f"shadow weight halved: pose_shadow_interference in "
                f"{self_shadow_regions}"
            )

    # -- Key light angle --
    # Measurement is FACE-relative, not camera-relative.
    # The face and its shadow pattern are the reference surface.
    # Shoulder/torso rotation is irrelevant — the face can be straight
    # to camera regardless of body angle.  Signals are weighted by how
    # directly they read the face surface:
    #   1. Catchlight clock position (highest) — light direction encoded in iris
    #   2. Nose shadow centroid offset (lr_asym proxy) — face shadow geometry
    #   3. Shadow vector from full image (lowest) — scene-level, less precise
    weighted_angles: list = []  # (angle_deg, weight)
    key_angle_raw = None

    # ── 1. Per-eye catchlight clock position (face-direct, highest weight) ──
    # Use the per-catchlight list when available (from vision_data catchlights).
    # Clock position in the iris directly encodes where the light source sits
    # relative to the eye — independent of body pose entirely.
    _cl_list = []
    if existing_catchlights and isinstance(existing_catchlights, dict):
        _cl_list = existing_catchlights.get("catchlights", [])
    _clock_to_angle = {
        1: 30.0, 2: 60.0, 3: 90.0, 4: 60.0, 5: 30.0,
        6: 0.0,
        7: 30.0, 8: 60.0, 9: 90.0, 10: 60.0, 11: 30.0, 12: 0.0,
    }
    for _cl in _cl_list:
        if _cl.get("role") not in ("key", None):
            continue
        _pos = _cl.get("position", "")
        try:
            _hour = int(_pos.split()[0])
            _cl_angle = _clock_to_azimuth_angle = _clock_to_angle.get(_hour, 45.0)
            weighted_angles.append((_cl_angle, 2.5))
            notes.append(f"key_angle from catchlight clock {_hour}: {_cl_angle:.0f}°")
        except (ValueError, IndexError):
            pass

    # Fallback: coarser catchlight_position string from earlier pass
    if not weighted_angles:
        cat_pos = cat.get("catchlight_position", "")
        if cat_pos and cat_pos != "unknown":
            _coarse_map = {
                "upper_left": 45.0, "upper_right": 45.0,
                "left": 90.0, "right": 90.0,
                "center_top": 0.0, "center": 0.0,
                "10_oclock": 60.0, "2_oclock": 60.0,
                "11_oclock": 30.0, "1_oclock": 30.0,
                "9_oclock": 90.0, "3_oclock": 90.0,
            }
            for _key, _angle in _coarse_map.items():
                if _key in cat_pos.lower().replace(" ", "_"):
                    weighted_angles.append((_angle, 2.0))
                    notes.append(f"key_angle from catchlight_position {cat_pos}: {_angle:.0f}°")
                    break

    # ── 2. Left/right illumination asymmetry → face angle estimate ──────
    # lr_asym measures how unequal the two halves of the face are lit.
    # More asymmetry = steeper off-axis angle.  This reads shadow position
    # directly from the face surface — pose-independent.
    #   lr_asym ≈ 0.00–0.05 → frontal (~0–10°)
    #   lr_asym ≈ 0.10–0.18 → loop range (~25–40°)
    #   lr_asym ≈ 0.20–0.35 → broad/short range (~40–55°)
    #   lr_asym ≈ 0.40+     → split territory (~60°+)
    _ls_for_angle = getattr(getattr(existing_catchlights, "cue_report", None), "light_structure", None) if existing_catchlights is not None and hasattr(existing_catchlights, "cue_report") else None
    _lr_asym_angle = None
    if _ls_for_angle is not None:
        _lra = getattr(_ls_for_angle, "left_right_asymmetry", None)
        if _lra is not None:
            # Linear mapping: asym 0→0°, asym 0.5→70°
            _lr_asym_angle = min(70.0, float(_lra) * 140.0)
            weighted_angles.append((_lr_asym_angle, 1.5))
            notes.append(f"key_angle from lr_asym {_lra:.3f}: {_lr_asym_angle:.0f}°")

    # ── 3. Shadow vector (scene-level, lower weight) ─────────────────────
    if shd.get("shadow_vector_deg") is not None:
        sv = shd["shadow_vector_deg"]
        sv_angle = abs(sv - 180.0) if sv > 180 else sv
        sv_angle = min(sv_angle, 180.0)
        weighted_angles.append((sv_angle, 1.0))
        notes.append(f"key_angle from shadow_vector {sv}°: {sv_angle:.0f}°")

    # ── Weighted average ──────────────────────────────────────────────────
    if weighted_angles:
        _total_w = sum(w for _, w in weighted_angles)
        key_angle_raw = sum(a * w for a, w in weighted_angles) / _total_w
    else:
        key_angle_raw = 30.0  # default moderate angle
        notes.append("key_angle defaulted to 30°")

    # ── Face-relative angle — no pose correction ─────────────────────────
    # Shadow and catchlight measurements on the face ARE already face-relative.
    # Shoulders can be turned while head is straight; the face surface is the
    # reference frame.  Do NOT subtract torso or head rotation — those are
    # camera-relative corrections that do not apply to face-surface measurements.
    key_angle_corrected = round(max(0.0, min(180.0, key_angle_raw)), 1)
    notes.append(f"key_angle_face_relative={key_angle_corrected:.1f}° (no pose correction applied)")

    if has_pose and pose.get("pose_highlight_interference"):
        notes.append("highlight_interference noted (catchlight weight already dominant)")

    # -- Key light height --
    key_height = "eye_level"  # default
    shd_vert = shd.get("shadow_vertical_angle_deg")
    if shd_vert is not None:
        if shd_vert > 50:
            key_height = "high"
        elif shd_vert < 20:
            key_height = "low"
        notes.append(f"key_height from shadow_vertical: {shd_vert}°")

    # ── Chin/head pitch correction for height estimate ──────────────────
    # cat_pos may not have been assigned if the primary clock-based
    # catchlight parsing succeeded (the fallback at line ~6199 is inside
    # an `if not weighted_angles` block).  Use cat dict directly.
    _cat_pos_h = cat.get("catchlight_position", "")
    if has_pose:
        chin_pitch = pose.get("chin_pitch", "neutral")
        if chin_pitch in ("down", "slightly_down") and key_height == "high":
            # Chin down makes shadows LOOK like they come from higher.
            # Moderate confidence in "high" unless catchlights confirm it.
            if not (_cat_pos_h and "upper" in _cat_pos_h.lower()):
                key_height = "eye_level"
                notes.append(
                    "height downgraded: chin_down mimics high-light shadow"
                )

    # -- Elevation above eye (numeric) --
    # Two methods, in priority order:
    #   1. Catchlight elevation_ratio — direct measurement from iris reflection
    #   2. Nose shadow length ratio — geometric: shorter shadow = higher light
    import math as _m

    key_elevation_above_eye_deg = None
    _elev_source = None

    # Method 1: catchlight position in iris
    _cat_list = cat.get("catchlights", [])
    _key_cl = None
    _best_score = -1
    for _cl in _cat_list:
        _s = (_cl.get("intensity", 0) or 0) * (_cl.get("size_ratio", 0) or 0)
        if _s > _best_score:
            _best_score = _s
            _key_cl = _cl
    if _key_cl and _key_cl.get("elevation_ratio") is not None:
        _er = max(-1.0, min(1.0, _key_cl["elevation_ratio"]))
        key_elevation_above_eye_deg = round(_m.degrees(_m.asin(_er)), 1)
        _elev_source = "catchlight"

    # Method 2: nose shadow length (always available from shadow analysis)
    # Shadow length ratio ≈ 1/tan(elevation_angle):
    #   ratio 0.2 → tan(elev) ≈ 5 → elev ≈ 79° (very high, butterfly)
    #   ratio 0.5 → tan(elev) ≈ 2 → elev ≈ 63° (high)
    #   ratio 0.8 → tan(elev) ≈ 1.25 → elev ≈ 51° (medium-high)
    #   ratio 1.0 → tan(elev) ≈ 1 → elev ≈ 45° (medium)
    #   ratio 1.5 → tan(elev) ≈ 0.67 → elev ≈ 34° (low)
    # Clamp to [5°, 75°] — below 5° is physically at eye level; above 75°
    # is directly overhead (butterfly territory).
    if key_elevation_above_eye_deg is None:
        _sl = shd.get("shadow_length_ratio")
        if isinstance(_sl, (int, float)) and _sl > 0.05:
            _elev_raw = _m.degrees(_m.atan(1.0 / _sl))
            key_elevation_above_eye_deg = round(max(5.0, min(75.0, _elev_raw)), 1)
            _elev_source = "shadow_length"

    if key_elevation_above_eye_deg is not None:
        notes.append(f"elevation_above_eye={key_elevation_above_eye_deg}° (source={_elev_source})")

    # -- Modifier size class --
    # Combine shadow softness, edge gradient, and highlight rolloff
    softness_signals = []
    sw_base = _SIGNAL_WEIGHTS["shadow_vector"] * shadow_weight_modifier
    if shd.get("shadow_softness") is not None:
        softness_signals.append((shd["shadow_softness"], sw_base))
    if shd.get("shadow_edge_gradient") is not None:
        softness_signals.append((shd["shadow_edge_gradient"], sw_base))

    hl_weight = _SIGNAL_WEIGHTS["highlight_rolloff"]
    if has_pose and pose.get("pose_highlight_interference"):
        # Boost highlight rolloff weight when pose distorts shadows
        hl_weight *= 1.3
    if hlt.get("highlight_rolloff_rate") is not None:
        # Low rolloff → larger/closer source
        rolloff_as_softness = 1.0 - hlt["highlight_rolloff_rate"]
        softness_signals.append((rolloff_as_softness, hl_weight))

    if softness_signals:
        weighted_sum = sum(v * w for v, w in softness_signals)
        weight_total = sum(w for _, w in softness_signals)
        avg_softness = weighted_sum / weight_total
    else:
        avg_softness = 0.5

    modifier_size_raw = "medium"
    for lo, hi, label in _MODIFIER_SIZE_BREAKPOINTS:
        if lo <= avg_softness < hi:
            modifier_size_raw = label
            break

    notes.append(f"modifier_size from weighted softness={avg_softness:.2f}")

    # ── Surface-corrected modifier size ─────────────────────────────────
    modifier_size_corrected = modifier_size_raw
    modifier_certainty = "moderate"

    if has_surface:
        hlw_corr = surface_profile["highlight_width_correction"]
        rolloff_corr = surface_profile["rolloff_correction"]
        corrected_softness = max(0.0, min(1.0, avg_softness + hlw_corr + rolloff_corr))

        for lo, hi, label in _MODIFIER_SIZE_BREAKPOINTS:
            if lo <= corrected_softness < hi:
                modifier_size_corrected = label
                break

        if modifier_size_corrected != modifier_size_raw:
            notes.append(
                f"surface correction ({surface_bias}): "
                f"modifier {modifier_size_raw} → {modifier_size_corrected}"
            )

        # Certainty based on surface complexity
        surface_complexity = surf.get("surface_complexity_score", 0.0)
        if surface_complexity > 0.6:
            modifier_certainty = "low"
        elif surface_complexity > 0.3:
            modifier_certainty = "moderate"
        else:
            modifier_certainty = "high"

    # Use the corrected value as the primary modifier_size
    modifier_size = modifier_size_corrected

    # -- Modifier distance --
    # Estimate from specular spread and catchlight size
    modifier_distance = 5.0  # default
    spec_spread = spec.get("specular_highlight_spread")
    cat_size = cat.get("catchlight_size_ratio")

    if spec_spread is not None and spec_spread > 0:
        # Larger spread → closer light
        modifier_distance = max(2.0, 10.0 - spec_spread * 8.0)
        notes.append(f"distance from specular_spread: {spec_spread}")
    elif cat_size is not None and cat_size > 0:
        # Larger catchlight → closer modifier
        modifier_distance = max(2.0, 8.0 - cat_size * 15.0)
        notes.append(f"distance from catchlight_size: {cat_size}")

    # -- Fill present --
    fill_present = None
    hlt_width = hlt.get("highlight_width_ratio")
    if hlt_width is not None:
        if hlt_width > 0.7:
            fill_present = True
            notes.append("fill detected: highlight_width_ratio > 0.7")
        elif hlt_width < 0.35:
            fill_present = False
            notes.append("no fill: highlight_width_ratio < 0.35")

    # -- Negative fill --
    negative_fill = False
    if hlt_width is not None and hlt_width < 0.3:
        # Very narrow highlight → could be negative fill
        if shd.get("shadow_softness") is not None and shd["shadow_softness"] < 0.3:
            negative_fill = True
            notes.append("negative_fill: narrow highlight + hard shadows")

    # -- Background light --
    bg_light = False
    bg_direction = bg.get("background_direction", "")
    bg_spread = bg.get("background_gradient_spread", 0.0)
    bg_intensity = bg.get("background_intensity_ratio", 0.0)

    if bg_spread > 0.3 and bg_intensity > 0.4:
        bg_light = True
        notes.append(f"background_light: spread={bg_spread}, intensity={bg_intensity}")

    # -- Background distance --
    bg_distance = 8.0  # default moderate
    if bg_intensity > 0.6:
        bg_distance = 5.0  # bright bg → likely closer
    elif bg_intensity < 0.2:
        bg_distance = 12.0  # dark bg → likely farther

    # -- Camera height --
    cam_height = "eye_level"
    geo_cam = geo.get("camera_height_relative_to_eyes")
    if geo_cam == "above":
        cam_height = "above_eye_level"
    elif geo_cam == "below":
        cam_height = "below_eye_level"

    # ── Light role overrides ───────────────────────────────────────────
    likely_light_count = None
    roles_dict: Dict[str, Any] = {}
    light_role_notes_list: List[str] = []

    if has_light_role:
        likely_light_count = lr.get("likely_light_count", "one")
        roles_dict = lr.get("roles", {})
        light_role_notes_list = lr.get("light_role_notes", [])

        # Override fill_present if light_role has stronger evidence
        fill_role = roles_dict.get("fill", {})
        if fill_role.get("present") and fill_role.get("confidence", 0) > 0.6:
            if fill_present is None or fill_present is False:
                fill_present = True
                notes.append("fill upgraded by light_role_pass (confidence > 0.6)")

        # Override negative_fill
        neg_fill_role = roles_dict.get("negative_fill", {})
        if neg_fill_role.get("present") and neg_fill_role.get("confidence", 0) > 0.6:
            negative_fill = True
            notes.append("negative_fill confirmed by light_role_pass")

        # Override background_light
        bg_role = roles_dict.get("background", {})
        if bg_role.get("present") and bg_role.get("confidence", 0) > 0.6:
            bg_light = True
            notes.append("background_light confirmed by light_role_pass")

    # ── Pose complexity score ───────────────────────────────────────────
    pose_complexity = pose.get("pose_complexity_score", 0.0) if has_pose else 0.0

    # ══════════════════════════════════════════════════════════════════
    # V2 ENHANCEMENTS — gated on new pass inputs being available
    # ══════════════════════════════════════════════════════════════════

    # --- Distance refinement from inverse_square ---
    distance_class = None
    source_distance_ft = modifier_distance  # start from existing estimate
    if inverse_square is not None and inverse_square.get("ok"):
        isq_dist = inverse_square.get("distance_estimate_ft")
        distance_class = inverse_square.get("distance_class")
        if isq_dist is not None:
            # Weighted average: 60% inverse-square, 40% existing specular/catchlight
            source_distance_ft = 0.6 * isq_dist + 0.4 * modifier_distance
            notes.append(
                f"distance refined by inverse_square: "
                f"{modifier_distance:.1f} → {source_distance_ft:.1f} ft"
            )

    # --- Environment-aware modifier correction ---
    env_class = None
    sun_candidate = False
    window_candidate = False
    if environment is not None and environment.get("ok"):
        env_class = environment.get("environment_class", "unknown")
        if env_class in ("window_light", "direct_sun"):
            # Natural sources are inherently very large — bias modifier upward
            _size_upgrade = {
                "small": "medium", "medium": "large", "large": "very_large",
            }
            old_mod = modifier_size
            modifier_size = _size_upgrade.get(modifier_size, modifier_size)
            if modifier_size != old_mod:
                notes.append(
                    f"modifier size upgraded for {env_class}: {old_mod} → {modifier_size}"
                )

    if solar is not None and solar.get("ok"):
        sun_candidate = solar.get("sun_candidate", False)
    if window is not None and window.get("ok"):
        window_candidate = window.get("window_candidate", False)

    # --- Hypothesis-driven overrides ---
    best_hypothesis = None
    hypotheses_list = None
    physics_score = None
    physics_violations = None
    primary_modifier_hypothesis = None
    modifier_candidates_list = None

    if hypothesis is not None and hypothesis.get("ok"):
        hypotheses_list = hypothesis.get("hypotheses")
        bi = hypothesis.get("best_hypothesis_index", 0)
        if hypotheses_list and 0 <= bi < len(hypotheses_list):
            best_hypothesis = hypotheses_list[bi]

    if physics is not None and physics.get("ok"):
        physics_score = physics.get("best_physics_score")
        physics_violations = physics.get("violation_summary", [])
        scored_hyps = physics.get("scored_hypotheses", [])
        pbi = physics.get("best_hypothesis_index", 0)
        if scored_hyps and 0 <= pbi < len(scored_hyps):
            best_hypothesis = scored_hyps[pbi].get("hypothesis", best_hypothesis)

        # If physics score is high, trust hypothesis for light count / roles
        if physics_score is not None and physics_score > 0.7 and best_hypothesis:
            hyp_lights = best_hypothesis.get("lights", [])
            if hyp_lights:
                hyp_count = len(hyp_lights)
                if likely_light_count is None or hyp_count != likely_light_count:
                    notes.append(
                        f"light count from hypothesis engine: {hyp_count} "
                        f"(physics_score={physics_score:.2f})"
                    )
                    likely_light_count = hyp_count

    # --- Modifier shape solver ---
    if modifier_shape is not None and modifier_shape.get("ok"):
        primary_modifier_hypothesis = modifier_shape.get("primary_modifier")
        modifier_candidates_list = modifier_shape.get("modifier_candidates")

    # --- Penumbra-refined modifier size ---
    if penumbra is not None and penumbra.get("ok"):
        apparent_size = penumbra.get("apparent_source_size")
        if apparent_size:
            _penumbra_size_map = {
                "point": "small", "small": "small", "medium": "medium",
                "large": "large", "very_large": "very_large",
            }
            pen_size = _penumbra_size_map.get(apparent_size)
            if pen_size and pen_size != modifier_size:
                # Blend: 50% current, 50% penumbra
                _size_order = ["small", "medium", "large", "very_large"]
                cur_idx = _size_order.index(modifier_size) if modifier_size in _size_order else 1
                pen_idx = _size_order.index(pen_size) if pen_size in _size_order else 1
                blend_idx = round((cur_idx + pen_idx) / 2.0)
                blend_idx = max(0, min(len(_size_order) - 1, blend_idx))
                old_mod = modifier_size
                modifier_size = _size_order[blend_idx]
                if modifier_size != old_mod:
                    notes.append(
                        f"penumbra refinement: {old_mod} → {modifier_size} "
                        f"(apparent_source_size={apparent_size})"
                    )

    # --- Mixed CCT flagging ---
    mixed_lighting = False
    dominant_cct = None
    if color_temp is not None and color_temp.get("ok"):
        mixed_lighting = color_temp.get("mixed_lighting", False)
        dominant_cct = color_temp.get("dominant_cct_kelvin")
        if mixed_lighting:
            notes.append(
                f"mixed color temperature detected "
                f"(dominant={dominant_cct}K, spread={color_temp.get('cct_spread_kelvin', 0)}K)"
            )

    # --- Occlusion detection ---
    occlusion_detected = False
    if occlusion is not None and occlusion.get("ok"):
        occlusion_detected = occlusion.get("occlusion_detected", False)

    # --- Light direction consistency ---
    ldf_consistency = None
    if light_direction_field is not None and light_direction_field.get("ok"):
        ldf_consistency = light_direction_field.get("vector_consistency")

    return {
        "ok": True,
        "key_light_angle_deg_raw": round(key_angle_raw, 1),
        "key_light_angle_deg_pose_corrected": round(key_angle_corrected, 1),
        "key_light_angle_deg": round(key_angle_corrected, 1),
        "key_light_height": key_height,
        "key_elevation_above_eye_deg": key_elevation_above_eye_deg,
        "modifier_size_class": modifier_size,
        "modifier_size_class_raw": modifier_size_raw,
        "modifier_size_class_surface_corrected": modifier_size_corrected,
        "modifier_certainty": modifier_certainty,
        "modifier_distance_ft": round(modifier_distance, 1),
        "fill_present": fill_present,
        "negative_fill": negative_fill,
        "background_light": bg_light,
        "background_distance_ft": round(bg_distance, 1),
        "camera_height_relative_to_subject": cam_height,
        "pose_complexity_score": round(pose_complexity, 3),
        "surface_complexity_score_from_surface": (
            round(surf.get("surface_complexity_score", 0.0), 3)
            if has_surface else None
        ),
        "likely_light_count": likely_light_count,
        "light_roles": roles_dict if has_light_role else None,
        "light_role_notes": light_role_notes_list if has_light_role else None,
        # ── V2 keys (additive) ──
        "light_direction_consistency": ldf_consistency,
        "estimated_source_distance_ft": round(source_distance_ft, 1),
        "distance_class": distance_class,
        "environment_class": env_class,
        "sun_candidate": sun_candidate,
        "window_candidate": window_candidate,
        "occlusion_detected": occlusion_detected,
        "dominant_cct_kelvin": dominant_cct,
        "mixed_lighting": mixed_lighting,
        "modifier_candidates": modifier_candidates_list,
        "primary_modifier_hypothesis": primary_modifier_hypothesis,
        "hypotheses": hypotheses_list,
        "best_hypothesis": best_hypothesis,
        "physics_score": physics_score,
        "physics_violations": physics_violations,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 7. NGW VALIDATION PASS
# ═══════════════════════════════════════════════════════════════════════════

def ngw_validation_pass(
    reconstruction: Dict[str, Any],
    shadow: Optional[Dict[str, Any]] = None,
    highlight: Optional[Dict[str, Any]] = None,
    catchlight: Optional[Dict[str, Any]] = None,
    pose_solver: Optional[Dict[str, Any]] = None,
    surface_class: Optional[Dict[str, Any]] = None,
    light_role: Optional[Dict[str, Any]] = None,
    # ── New v2 inputs (optional for backward compat) ──
    hypothesis: Optional[Dict[str, Any]] = None,
    physics: Optional[Dict[str, Any]] = None,
    environment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate reconstruction estimates for internal consistency.

    Checks for conflicting signals, flags low-confidence estimates,
    and adjusts confidence based on pose complexity, surface complexity,
    light role consistency, hypothesis physics score, and environment.
    Uses the pose-corrected key_light_angle_deg when available.

    Returns:
        valid: bool
        confidence: overall confidence (0-1)
        warnings: list of inconsistencies found
        pose_adjusted: whether confidence was adjusted for pose complexity
        surface_adjusted: whether confidence was adjusted for surface complexity
    """
    warnings: List[str] = []
    confidence_factors: List[float] = []
    pose = pose_solver or {}
    has_pose = pose.get("ok", False)

    # Use pose-corrected angle when available
    recon_angle = reconstruction.get("key_light_angle_deg", 0)

    # Check key angle consistency
    if shadow and catchlight:
        # If catchlight says center but shadow says far off-axis → conflict
        cat_pos = catchlight.get("catchlight_position", "")
        if ("center" in cat_pos or "12" in cat_pos) and recon_angle > 60:
            warnings.append(
                f"Conflict: catchlight at {cat_pos} but key_angle={recon_angle}°"
            )
            confidence_factors.append(0.4)
        else:
            confidence_factors.append(0.8)

    # Check modifier size vs shadow softness
    if shadow:
        softness = shadow.get("shadow_softness", 0.5)
        mod_size = reconstruction.get("modifier_size_class", "medium")
        # When pose creates self-shadows, relax the softness check
        softness_threshold_low = 0.2
        softness_threshold_high = 0.7
        if has_pose and pose.get("pose_shadow_interference"):
            softness_threshold_low = 0.1
            softness_threshold_high = 0.8

        if softness < softness_threshold_low and mod_size in ("large", "very_large"):
            warnings.append(
                f"Conflict: hard shadows (softness={softness}) with {mod_size} modifier"
            )
            confidence_factors.append(0.3)
        elif softness > softness_threshold_high and mod_size == "small":
            warnings.append(
                f"Conflict: soft shadows (softness={softness}) with {mod_size} modifier"
            )
            confidence_factors.append(0.3)
        else:
            confidence_factors.append(0.8)

    # Check fill detection consistency
    if highlight:
        width = highlight.get("highlight_width_ratio", 0.5)
        fill = reconstruction.get("fill_present")
        if fill is True and width < 0.3:
            warnings.append(
                f"Conflict: fill detected but highlight_width_ratio={width}"
            )
            confidence_factors.append(0.5)
        else:
            confidence_factors.append(0.7)

    # ── Pose-aware confidence adjustment ────────────────────────────────
    # Higher pose complexity = less reliable naive lighting inference.
    # Catchlights and highlight rolloff are weighted MORE; raw shadow
    # direction is weighted LESS.
    pose_adjusted = False
    if has_pose:
        complexity = pose.get("pose_complexity_score", 0.0)

        if complexity > 0.6:
            # High complexity: significantly reduce confidence in
            # shadow-based estimates.  If catchlights are present,
            # maintain moderate confidence.
            cat_count = (catchlight or {}).get("catchlight_count", 0)
            if cat_count > 0:
                confidence_factors.append(0.55)
                notes_msg = (
                    f"high pose complexity ({complexity:.2f}) "
                    "but catchlights provide anchor"
                )
            else:
                confidence_factors.append(0.3)
                notes_msg = (
                    f"high pose complexity ({complexity:.2f}), "
                    "no catchlight anchor — low confidence"
                )
            warnings.append(notes_msg)
            pose_adjusted = True

        elif complexity > 0.35:
            confidence_factors.append(0.65)
            warnings.append(
                f"moderate pose complexity ({complexity:.2f}), "
                "confidence slightly reduced"
            )
            pose_adjusted = True

        # Pose-corrected vs raw angle divergence check
        raw_angle = reconstruction.get("key_light_angle_deg_raw")
        corrected_angle = reconstruction.get("key_light_angle_deg_pose_corrected")
        if raw_angle is not None and corrected_angle is not None:
            delta = abs(raw_angle - corrected_angle)
            if delta > 20:
                warnings.append(
                    f"Large pose correction: raw={raw_angle}° → "
                    f"corrected={corrected_angle}° (delta={delta:.0f}°)"
                )

    # ── Surface-aware confidence adjustment ────────────────────────────
    surface_adjusted = False
    surf = surface_class or {}
    if surf.get("ok"):
        surface_complexity = surf.get("surface_complexity_score", 0.0)
        if surface_complexity > 0.6:
            confidence_factors.append(0.5)
            warnings.append(
                f"high surface complexity ({surface_complexity:.2f}): "
                "modifier size estimate less reliable"
            )
            surface_adjusted = True
        elif surface_complexity > 0.3:
            confidence_factors.append(0.7)
            surface_adjusted = True

        # Flag reflection-dominant regions
        reflection_regions = surf.get("reflection_dominant_regions", [])
        if reflection_regions:
            warnings.append(
                f"reflection-dominant regions: {', '.join(reflection_regions)} "
                "— highlight/specular signals may be surface artifacts"
            )

    # ── Light role consistency ─────────────────────────────────────────
    lr = light_role or {}
    if lr.get("ok"):
        light_count = lr.get("likely_light_count", "one")
        false_risk = lr.get("false_multi_light_risk", 0.0)

        # Check: if reconstruction says fill_present but light count is one
        recon_fill = reconstruction.get("fill_present")
        if recon_fill and light_count == "one":
            warnings.append("Conflict: fill detected but light count is one")
            confidence_factors.append(0.5)

        # Check: high false_multi_light_risk degrades confidence
        if false_risk > 0.5:
            confidence_factors.append(0.6)
            warnings.append(
                f"high false multi-light risk ({false_risk:.2f}): "
                "light count may be overestimated"
            )

        # Check: weak rim detection
        rim_role = lr.get("roles", {}).get("rim", {})
        if rim_role.get("present") and rim_role.get("confidence", 0) < 0.5:
            warnings.append("weak rim detection — may be surface reflection")

    # ── Hypothesis physics consistency ──────────────────────────────────
    if physics is not None and physics.get("ok"):
        phys_score = physics.get("best_physics_score", 0.5)
        violations = physics.get("violation_summary", [])
        if phys_score > 0.7:
            confidence_factors.append(0.85)
        elif phys_score < 0.3:
            confidence_factors.append(0.35)
            warnings.append(
                f"physics consistency low ({phys_score:.2f}): "
                f"{len(violations)} violation(s)"
            )
        else:
            confidence_factors.append(0.6)

    # ── Environment consistency ──────────────────────────────────────
    if environment is not None and environment.get("ok"):
        env_conf = environment.get("environment_confidence", 0.5)
        env_class = environment.get("environment_class", "unknown")
        if env_class == "unknown":
            warnings.append("environment class unknown — reconstruction less certain")
            confidence_factors.append(0.45)
        elif env_conf > 0.7:
            confidence_factors.append(0.8)
        else:
            confidence_factors.append(0.6)

    # ── Hypothesis / reconstruction agreement ────────────────────────
    if hypothesis is not None and hypothesis.get("ok"):
        hyp_count = hypothesis.get("likely_light_count")
        recon_count = reconstruction.get("likely_light_count")
        if hyp_count and recon_count and hyp_count != recon_count:
            warnings.append(
                f"light count disagreement: hypothesis={hyp_count}, "
                f"reconstruction={recon_count}"
            )
            confidence_factors.append(0.5)

    # Overall confidence
    if confidence_factors:
        confidence = float(np.mean(confidence_factors))
    else:
        confidence = 0.5

    return {
        "ok": True,
        "valid": len(warnings) == 0,
        "confidence": round(confidence, 3),
        "warnings": warnings,
        "pose_adjusted": pose_adjusted,
        "surface_adjusted": surface_adjusted,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

def run_extended_pipeline(
    img_bgr: np.ndarray,
    person_mask: Optional[np.ndarray] = None,
    skin_mask: Optional[np.ndarray] = None,
    background_mask: Optional[np.ndarray] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    existing_catchlights: Optional[Dict[str, Any]] = None,
    existing_geometry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the full extended vision pipeline.

    Pipeline order:
        geometry (from existing) → pose_solver → camera_geometry → surface_class → shadow →
        highlight → catchlight → background → specular_surface →
        ── NEW SIGNAL PASSES ──
        light_direction_field → inverse_square → solar_geometry →
        window_geometry → bounce_geometry → reflection_geometry →
        shadow_penumbra → occlusion_shadow → color_temperature →
        environment_light →
        ── NEW SYNTHESIS PASSES ──
        modifier_shape_solver → lighting_hypothesis_engine →
        physics_consistency_engine →
        ── EXISTING ENHANCED ──
        reconstruction → vlm_reconstruction (optional) →
        pattern_matches → reference_matches →
        lighting_knowledge_library → validation

    Each pass runs in its own try/except — one failure never breaks others.
    ``results["light_role"]`` is aliased to ``results["hypothesis"]`` for
    backward compatibility.
    """
    from engine.reference_matcher import match_reference_images as reference_match_fn
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[str, Any] = {}

    # ── Geometry (from existing pipeline) ────────────────────────────
    results["geometry"] = existing_geometry or {}

    # ── Pose solver pass ─────────────────────────────────────────────
    try:
        results["pose_solver"] = pose_solver_pass(
            img_bgr,
            geometry=results.get("geometry"),
            person_mask=person_mask,
            face_box=face_box,
        )
    except Exception as exc:
        logger.warning("pose_solver_pass failed: %s", exc)
        results["pose_solver"] = {"ok": False, "error": str(exc)}

    # ── Camera geometry (CV-based height + horizontal angle) ─────────
    try:
        results["camera_geometry"] = camera_geometry_pass(
            face_geometry=existing_catchlights.get("face_geometry") if existing_catchlights else None,
            pose_solver=results.get("pose_solver"),
        )
    except Exception as exc:
        logger.warning("camera_geometry_pass failed: %s", exc)
        results["camera_geometry"] = {"ok": False, "error": str(exc)}

    # ── Wave 1: Independent passes — run concurrently ────────────────
    # These passes read only img_bgr + masks; none depend on each other.
    _wave1_tasks = {
        "surface_class": lambda: surface_class_pass(
            img_bgr, person_mask=person_mask, skin_mask=skin_mask,
            face_box=face_box, background_mask=background_mask,
        ),
        "shadow": lambda: shadow_pass(
            img_bgr, person_mask=person_mask,
            skin_mask=skin_mask, face_box=face_box,
        ),
        "highlight": lambda: highlight_pass(
            img_bgr, person_mask=person_mask,
            skin_mask=skin_mask, face_box=face_box,
        ),
        "catchlight": lambda: catchlight_pass(
            img_bgr, face_box=face_box,
            existing_catchlights=existing_catchlights,
        ),
        "background": lambda: background_pass(
            img_bgr, background_mask=background_mask,
        ),
        "specular_surface": lambda: specular_surface_pass(
            img_bgr, person_mask=person_mask,
            skin_mask=skin_mask, face_box=face_box,
        ),
    }
    with ThreadPoolExecutor(max_workers=len(_wave1_tasks)) as _pool:
        _futures = {_pool.submit(fn): key for key, fn in _wave1_tasks.items()}
        for _fut in as_completed(_futures):
            _key = _futures[_fut]
            try:
                results[_key] = _fut.result()
            except Exception as exc:
                logger.warning("%s_pass failed: %s", _key, exc)
                results[_key] = {"ok": False, "error": str(exc)}

    # ── Patch highlight_axis_deg from shadow_vector_deg ──────────────
    # Both passed run in Wave 1 concurrently, so shadow_vector_deg is now available.
    # Replace the fitEllipse fallback with the geometric derivation.
    _shd_res = results.get("shadow", {})
    _hl_res = results.get("highlight", {})
    if _shd_res.get("ok") and _hl_res.get("ok"):
        _sv = _shd_res.get("shadow_vector_deg")
        if isinstance(_sv, (int, float)):
            _hl_res["highlight_axis_deg"] = round(
                90.0 * abs(math.cos(math.radians(float(_sv)))), 1
            )

    # ── Catchlight topology pass (multi-catchlight analysis) ─────────
    try:
        results["catchlight_topology"] = catchlight_topology_pass(
            img_bgr, face_box=face_box,
            existing_catchlights=existing_catchlights,
            catchlight_data=results.get("catchlight"),
        )
    except Exception as exc:
        logger.warning("catchlight_topology_pass failed: %s", exc)
        results["catchlight_topology"] = {"ok": False, "error": str(exc)}

    # ── Highlight axis map pass ───────────────────────────────────────
    try:
        results["highlight_axis_map"] = highlight_axis_map_pass(
            img_bgr, face_box=face_box,
            person_mask=person_mask,
            skin_mask=skin_mask,
            highlight_data=results.get("highlight"),
        )
    except Exception as exc:
        logger.warning("highlight_axis_map_pass failed: %s", exc)
        results["highlight_axis_map"] = {"ok": False, "error": str(exc)}

    # ── Highlight symmetry pass ───────────────────────────────────────
    try:
        results["highlight_symmetry"] = highlight_symmetry_pass(
            img_bgr, face_box=face_box,
            highlight_data=results.get("highlight"),
            highlight_axis_data=results.get("highlight_axis_map"),
        )
    except Exception as exc:
        logger.warning("highlight_symmetry_pass failed: %s", exc)
        results["highlight_symmetry"] = {"ok": False, "error": str(exc)}

    # ── Continuous source heuristic pass ──────────────────────────────
    try:
        results["continuous_source"] = continuous_source_heuristic_pass(
            img_bgr,
            catchlight_data=results.get("catchlight"),
            catchlight_topology_data=results.get("catchlight_topology"),
            highlight_data=results.get("highlight"),
            color_temp_data=results.get("color_temp"),
        )
    except Exception as exc:
        logger.warning("continuous_source_heuristic_pass failed: %s", exc)
        results["continuous_source"] = {"ok": False, "error": str(exc)}

    # ── Bounce contributor pass ──────────────────────────────────────
    try:
        results["bounce_contributor"] = bounce_contributor_pass(
            img_bgr,
            shadow_data=results.get("shadow"),
            highlight_data=results.get("highlight"),
            bounce_data=results.get("bounce"),
            person_mask=person_mask,
            face_box=face_box,
        )
    except Exception as exc:
        logger.warning("bounce_contributor_pass failed: %s", exc)
        results["bounce_contributor"] = {"ok": False, "error": str(exc)}

    # ── Separation light pass ────────────────────────────────────────
    try:
        results["separation_light"] = separation_light_pass(
            img_bgr,
            person_mask=person_mask,
            face_box=face_box,
            edge_highlights=results.get("edge_highlights"),
            background_data=results.get("background"),
        )
    except Exception as exc:
        logger.warning("separation_light_pass failed: %s", exc)
        results["separation_light"] = {"ok": False, "error": str(exc)}

    # ── Off-axis key pass ────────────────────────────────────────────
    try:
        results["off_axis_key"] = off_axis_key_pass(
            img_bgr,
            shadow_data=results.get("shadow"),
            highlight_data=results.get("highlight"),
            highlight_axis_data=results.get("highlight_axis_map"),
            catchlight_data=results.get("catchlight"),
            face_box=face_box,
        )
    except Exception as exc:
        logger.warning("off_axis_key_pass failed: %s", exc)
        results["off_axis_key"] = {"ok": False, "error": str(exc)}

    # ── Light structure pass ─────────────────────────────────────────
    try:
        results["light_structure"] = light_structure_pass(
            img_bgr,
            shadow_data=results.get("shadow"),
            face_box=face_box,
            highlight_symmetry_data=results.get("highlight_symmetry"),
        )
    except Exception as exc:
        logger.warning("light_structure_pass failed: %s", exc)
        results["light_structure"] = {"ok": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════
    # NEW SIGNAL EXTRACTION PASSES
    # ══════════════════════════════════════════════════════════════════

    # ── Light direction field ────────────────────────────────────────
    try:
        results["light_direction_field"] = light_direction_field_pass(
            img_bgr, person_mask=person_mask, face_box=face_box,
            shadow=results.get("shadow"),
            highlight=results.get("highlight"),
        )
    except Exception as exc:
        logger.warning("light_direction_field_pass failed: %s", exc)
        results["light_direction_field"] = {"ok": False, "error": str(exc)}

    # ── Inverse square solver ────────────────────────────────────────
    try:
        results["inverse_square"] = inverse_square_solver_pass(
            img_bgr, person_mask=person_mask, face_box=face_box,
            highlight=results.get("highlight"),
            specular=results.get("specular_surface"),
            catchlight=results.get("catchlight"),
        )
    except Exception as exc:
        logger.warning("inverse_square_solver_pass failed: %s", exc)
        results["inverse_square"] = {"ok": False, "error": str(exc)}

    # ── Solar geometry ───────────────────────────────────────────────
    try:
        results["solar"] = solar_geometry_pass(
            img_bgr, shadow=results.get("shadow"),
            background=results.get("background"),
            person_mask=person_mask,
        )
    except Exception as exc:
        logger.warning("solar_geometry_pass failed: %s", exc)
        results["solar"] = {"ok": False, "error": str(exc)}

    # ── Window geometry ──────────────────────────────────────────────
    try:
        results["window"] = window_geometry_pass(
            img_bgr, background=results.get("background"),
            highlight=results.get("highlight"),
            person_mask=person_mask,
        )
    except Exception as exc:
        logger.warning("window_geometry_pass failed: %s", exc)
        results["window"] = {"ok": False, "error": str(exc)}

    # ── Bounce geometry ──────────────────────────────────────────────
    try:
        results["bounce"] = bounce_geometry_pass(
            img_bgr, shadow=results.get("shadow"),
            highlight=results.get("highlight"),
            person_mask=person_mask, face_box=face_box,
        )
    except Exception as exc:
        logger.warning("bounce_geometry_pass failed: %s", exc)
        results["bounce"] = {"ok": False, "error": str(exc)}

    # ── Reflection geometry ──────────────────────────────────────────
    try:
        results["reflection"] = reflection_geometry_pass(
            img_bgr, specular=results.get("specular_surface"),
            person_mask=person_mask, skin_mask=skin_mask,
        )
    except Exception as exc:
        logger.warning("reflection_geometry_pass failed: %s", exc)
        results["reflection"] = {"ok": False, "error": str(exc)}

    # ── Shadow penumbra ──────────────────────────────────────────────
    try:
        results["penumbra"] = shadow_penumbra_pass(
            img_bgr, shadow=results.get("shadow"),
            person_mask=person_mask, face_box=face_box,
        )
    except Exception as exc:
        logger.warning("shadow_penumbra_pass failed: %s", exc)
        results["penumbra"] = {"ok": False, "error": str(exc)}

    # ── Occlusion shadow ─────────────────────────────────────────────
    try:
        results["occlusion"] = occlusion_shadow_pass(
            img_bgr, shadow=results.get("shadow"),
            background=results.get("background"),
            person_mask=person_mask,
        )
    except Exception as exc:
        logger.warning("occlusion_shadow_pass failed: %s", exc)
        results["occlusion"] = {"ok": False, "error": str(exc)}

    # ── Color temperature ────────────────────────────────────────────
    try:
        results["color_temp"] = color_temperature_pass(
            img_bgr, person_mask=person_mask,
            skin_mask=skin_mask, face_box=face_box,
        )
    except Exception as exc:
        logger.warning("color_temperature_pass failed: %s", exc)
        results["color_temp"] = {"ok": False, "error": str(exc)}

    # ── Environment light ────────────────────────────────────────────
    try:
        results["environment"] = environment_light_pass(
            img_bgr, shadow=results.get("shadow"),
            highlight=results.get("highlight"),
            background=results.get("background"),
            solar=results.get("solar"),
            window=results.get("window"),
            bounce=results.get("bounce"),
            color_temp=results.get("color_temp"),
            person_mask=person_mask,
        )
    except Exception as exc:
        logger.warning("environment_light_pass failed: %s", exc)
        results["environment"] = {"ok": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════
    # NEW SYNTHESIS PASSES
    # ══════════════════════════════════════════════════════════════════

    # ── Modifier shape solver ────────────────────────────────────────
    try:
        results["modifier_shape"] = modifier_shape_solver_pass(
            img_bgr, catchlight=results.get("catchlight"),
            reflection=results.get("reflection"),
            specular=results.get("specular_surface"),
            highlight=results.get("highlight"),
            penumbra=results.get("penumbra"),
            face_box=face_box,
        )
    except Exception as exc:
        logger.warning("modifier_shape_solver_pass failed: %s", exc)
        results["modifier_shape"] = {"ok": False, "error": str(exc)}

    # ── Lighting hypothesis engine (replaces light_role_pass) ────────
    try:
        results["hypothesis"] = lighting_hypothesis_engine(
            shadow=results.get("shadow"),
            highlight=results.get("highlight"),
            catchlight=results.get("catchlight"),
            background=results.get("background"),
            specular=results.get("specular_surface"),
            pose_solver=results.get("pose_solver"),
            surface_class=results.get("surface_class"),
            light_direction_field=results.get("light_direction_field"),
            inverse_square=results.get("inverse_square"),
            solar=results.get("solar"),
            window=results.get("window"),
            bounce_geo=results.get("bounce"),
            reflection=results.get("reflection"),
            penumbra=results.get("penumbra"),
            occlusion=results.get("occlusion"),
            color_temp=results.get("color_temp"),
            environment=results.get("environment"),
            modifier_shape=results.get("modifier_shape"),
            img_bgr=img_bgr,
            person_mask=person_mask,
            face_box=face_box,
        )
    except Exception as exc:
        logger.warning("lighting_hypothesis_engine failed: %s", exc)
        results["hypothesis"] = {"ok": False, "error": str(exc)}

    # Backward compat: alias light_role → hypothesis
    results["light_role"] = results["hypothesis"]

    # ── Physics consistency engine ───────────────────────────────────
    try:
        hyp_list = results.get("hypothesis", {}).get("hypotheses")
        results["physics"] = physics_consistency_engine(
            hypotheses=hyp_list,
            shadow=results.get("shadow"),
            highlight=results.get("highlight"),
            catchlight=results.get("catchlight"),
            specular=results.get("specular_surface"),
            light_direction_field=results.get("light_direction_field"),
            inverse_square=results.get("inverse_square"),
            penumbra=results.get("penumbra"),
            color_temp=results.get("color_temp"),
            reflection=results.get("reflection"),
        )
    except Exception as exc:
        logger.warning("physics_consistency_engine failed: %s", exc)
        results["physics"] = {"ok": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════
    # RECONSTRUCTION + KNOWLEDGE LIBRARY + VALIDATION
    # ══════════════════════════════════════════════════════════════════

    # ── Reconstruction pass (enhanced with all new inputs) ───────────
    try:
        results["reconstruction"] = reconstruction_pass(
            geometry=results.get("geometry"),
            shadow=results.get("shadow"),
            highlight=results.get("highlight"),
            catchlight=results.get("catchlight"),
            background=results.get("background"),
            specular=results.get("specular_surface"),
            pose_solver=results.get("pose_solver"),
            surface_class=results.get("surface_class"),
            light_role=results.get("light_role"),
            # v2 inputs
            light_direction_field=results.get("light_direction_field"),
            inverse_square=results.get("inverse_square"),
            solar=results.get("solar"),
            window=results.get("window"),
            bounce=results.get("bounce"),
            reflection=results.get("reflection"),
            penumbra=results.get("penumbra"),
            occlusion=results.get("occlusion"),
            color_temp=results.get("color_temp"),
            environment=results.get("environment"),
            modifier_shape=results.get("modifier_shape"),
            hypothesis=results.get("hypothesis"),
            physics=results.get("physics"),
            existing_catchlights=existing_catchlights,
        )
    except Exception as exc:
        logger.warning("reconstruction_pass failed: %s", exc)
        results["reconstruction"] = {"ok": False, "error": str(exc)}

    # ── VLM Reconstruction (optional, best-effort) ──────────────────
    try:
        from engine.vlm_reconstruction import vlm_reconstruct
        vlm_recon = vlm_reconstruct(results)
        if vlm_recon is not None:
            results["vlm_reconstruction"] = vlm_recon.model_dump() if hasattr(vlm_recon, "model_dump") else {}
        else:
            results["vlm_reconstruction"] = None
    except Exception as exc:
        logger.warning("vlm_reconstruct failed: %s", exc)
        results["vlm_reconstruction"] = None

    # ── Reference matching ───────────────────────────────────────────
    try:
        results["reference_matches"] = reference_match_fn(
            results.get("reconstruction", {}),
        )
    except Exception as exc:
        logger.warning("match_reference_images failed: %s", exc)
        results["reference_matches"] = {"closest_references": [], "top_reference": None, "top_similarity": 0.0}

    # ── Validation pass (enhanced with hypothesis/physics/environment)
    try:
        results["validation"] = ngw_validation_pass(
            reconstruction=results.get("reconstruction", {}),
            shadow=results.get("shadow"),
            highlight=results.get("highlight"),
            catchlight=results.get("catchlight"),
            pose_solver=results.get("pose_solver"),
            surface_class=results.get("surface_class"),
            light_role=results.get("light_role"),
            hypothesis=results.get("hypothesis"),
            physics=results.get("physics"),
            environment=results.get("environment"),
        )
    except Exception as exc:
        logger.warning("ngw_validation_pass failed: %s", exc)
        results["validation"] = {"ok": False, "error": str(exc)}

    return results
