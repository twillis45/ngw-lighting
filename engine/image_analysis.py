from __future__ import annotations

import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

from engine.vision_pipeline import analyze_image_regions


# ── VLM result cache ─────────────────────────────────────────────────────────
# Cache by SHA-256 of image bytes → avoids repeat API calls during testing.
# Stored in a temp dir so it survives the process but not reboots.
_VLM_CACHE_DIR = os.path.join(tempfile.gettempdir(), "ngw_vlm_cache")
os.makedirs(_VLM_CACHE_DIR, exist_ok=True)


def _image_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _vlm_cache_path(img_hash: str) -> str:
    return os.path.join(_VLM_CACHE_DIR, f"{img_hash}.json")


def _load_vlm_cache(img_hash: str) -> Optional[Dict[str, Any]]:
    p = _vlm_cache_path(img_hash)
    try:
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_vlm_cache(img_hash: str, data: Dict[str, Any]) -> None:
    try:
        with open(_vlm_cache_path(img_hash), "w") as f:
            json.dump(data, f)
    except Exception:
        pass


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


def _is_grayscale_like(img_rgb: "Image.Image") -> bool:
    im = img_rgb.resize((96, 96))
    px = list(im.getdata())
    if not px:
        return True
    total = 0.0
    for (r, g, b) in px:
        total += abs(r - g) + abs(g - b) + abs(r - b)
    avg = total / float(len(px))
    # Threshold 18: warm-toned B&W (sepia, selenium, silver-gelatin) typically
    # has avg channel-pair diff sum of 10-15.  Pure colour images start at ~20+.
    # Previous threshold of 6 missed warm B&W entirely.
    return avg < 18.0


def _palette(img_rgb: "Image.Image", k: int = 6) -> List[Dict[str, Any]]:
    im = img_rgb.resize((160, 160)).convert("RGB")
    pal = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=k)  # type: ignore[attr-defined]
    palette = pal.getpalette() or []
    color_counts = pal.getcolors() or []
    total = sum(c for c, _ in color_counts) or 1

    out: List[Dict[str, Any]] = []
    for count, idx in sorted(color_counts, reverse=True):
        base = idx * 3
        if base + 2 >= len(palette):
            continue
        rgb = (palette[base], palette[base + 1], palette[base + 2])
        out.append(
            {
                "rgb": list(rgb),
                "hex": _rgb_to_hex(rgb),
                "name": _nearest_basic_name(rgb),
                "pct": round(100.0 * (count / float(total)), 2),
            }
        )
    return out


_MOOD_TO_RECIPE = {
    "beauty": "beauty-clamshell",
    "cinematic": "dramatic-rembrandt",
    "corporate": "corporate-clean",
    "editorial": "editorial-hard",
    "natural": "natural-window",
    "high_key": "high-key-product",
    "low_key": "low-key-dramatic",
}


def _luminance(r: int, g: int, b: int) -> float:
    """Perceived luminance (0–255)."""
    return 0.299 * r + 0.587 * g + 0.114 * b


def _classify_palette(
    palette_entries: List[Dict[str, Any]], is_grayscale: bool
) -> Dict[str, Any]:
    """Infer mood, recipe, light quality, color temp, and brightness from a 6-color palette."""

    if not palette_entries:
        return {
            "mood": "natural",
            "confidence": 0.3,
            "suggestedRecipe": None,
            "lightQuality": "soft",
            "colorTemperature": "neutral",
            "colorTemperatureKelvin": 5500,
            "brightness": "medium",
        }

    # --- brightness ---
    total_pct = sum(e["pct"] for e in palette_entries) or 1.0
    avg_lum = sum(
        _luminance(*e["rgb"]) * e["pct"] for e in palette_entries
    ) / total_pct
    norm_brightness = avg_lum / 255.0  # 0–1

    # --- contrast ---
    lums = [_luminance(*e["rgb"]) for e in palette_entries]
    contrast = (max(lums) - min(lums)) / 255.0  # 0–1

    # --- color temperature ---
    warm_bias = 0.0
    for e in palette_entries:
        r, g, b = e["rgb"]
        warm_bias += (r - b) * e["pct"]
    warm_bias /= total_pct
    if warm_bias > 20:
        color_temp = "warm"
    elif warm_bias < -20:
        color_temp = "cool"
    else:
        color_temp = "neutral"

    # Approximate Kelvin from warm_bias:
    #   warm_bias ≈ 0  → 5500K (daylight)
    #   warm_bias > 0   → lower K (warmer/tungsten)
    #   warm_bias < 0   → higher K (cooler/shade)
    color_temp_kelvin = int(max(2000, min(10000, 5500 - warm_bias * 30)))

    # --- mood scoring ---
    scores: Dict[str, float] = {
        "beauty": 0.0,
        "cinematic": 0.0,
        "corporate": 0.0,
        "editorial": 0.0,
        "natural": 0.0,
        "high_key": 0.0,
        "low_key": 0.0,
    }

    # high_key: bright + low contrast
    if norm_brightness > 0.75:
        scores["high_key"] += 3.0
    elif norm_brightness > 0.60:
        scores["high_key"] += 1.5
    if contrast < 0.3:
        scores["high_key"] += 1.0

    # low_key: dark
    if norm_brightness < 0.30:
        scores["low_key"] += 3.0
    elif norm_brightness < 0.40:
        scores["low_key"] += 1.5
    if contrast > 0.4:
        scores["low_key"] += 0.5

    # cinematic: grayscale OR dark + high contrast
    if is_grayscale:
        scores["cinematic"] += 2.5
        scores["editorial"] += 1.0
    if norm_brightness < 0.45 and contrast > 0.4:
        scores["cinematic"] += 2.0
    if contrast > 0.5:
        scores["cinematic"] += 1.0

    # editorial: high contrast, not grayscale
    if contrast > 0.5 and not is_grayscale:
        scores["editorial"] += 2.5
    if contrast > 0.4:
        scores["editorial"] += 0.5

    # beauty: medium-high brightness + low contrast + warm
    if 0.45 < norm_brightness < 0.75 and contrast < 0.4:
        scores["beauty"] += 2.0
    if color_temp == "warm":
        scores["beauty"] += 1.0
        scores["natural"] += 0.5
    if contrast < 0.3:
        scores["beauty"] += 0.5

    # corporate: medium brightness + low contrast + neutral
    if 0.40 < norm_brightness < 0.65 and contrast < 0.4:
        scores["corporate"] += 1.5
    if color_temp == "neutral":
        scores["corporate"] += 1.5

    # natural: medium brightness + warm + moderate contrast
    if 0.35 < norm_brightness < 0.65:
        scores["natural"] += 1.0
    if color_temp == "warm":
        scores["natural"] += 1.5
    if 0.2 < contrast < 0.5:
        scores["natural"] += 1.0

    # pick winner
    winner = max(scores, key=lambda k: scores[k])
    total_score = sum(scores.values()) or 1.0
    confidence = scores[winner] / total_score
    confidence = max(0.3, min(0.95, confidence))

    # brightness label
    if norm_brightness < 0.33:
        brightness_label = "low"
    elif norm_brightness < 0.66:
        brightness_label = "medium"
    else:
        brightness_label = "high"

    # light quality
    light_quality = "hard" if contrast > 0.5 else "soft"

    return {
        "mood": winner,
        "confidence": round(confidence, 2),
        "suggestedRecipe": _MOOD_TO_RECIPE.get(winner),
        "lightQuality": light_quality,
        "colorTemperature": color_temp,
        "colorTemperatureKelvin": color_temp_kelvin,
        "brightness": brightness_label,
    }


def describe_image(path: str, describe_mode: str = "basic", *, debug: bool = False, run_vlm: bool = True) -> Dict[str, Any]:
    """
    basic: safe stats + palettes (no subject claims)
    vision: adds segmentation-based palettes + pose guess (opencv+mediapipe)
    """
    if Image is None or ImageOps is None:
        return {"ok": False, "error": "Pillow not installed; cannot describe image."}

    img = Image.open(path)  # type: ignore
    img = ImageOps.exif_transpose(img)  # type: ignore
    img_rgb = img.convert("RGB")

    w, h = img_rgb.size
    aspect = (w / float(h)) if h else 0.0
    if aspect >= 1.20:
        orientation = "landscape"
    elif aspect <= 0.83:
        orientation = "portrait"
    else:
        orientation = "square-ish"

    grayscale_like = _is_grayscale_like(img_rgb)
    overall_palette = _palette(img_rgb, k=6)

    out: Dict[str, Any] = {
        "ok": True,
        "size": {"width": w, "height": h},
        "orientation": orientation,
        "aspect_ratio": round(aspect, 4),
        "is_grayscale_like": bool(grayscale_like),
        "palette": {
            "overall": overall_palette,
            "notes": [
                "Overall palette is global; it does not attribute colors to objects without vision mode.",
            ],
        },
        "subject": {
            "description": "unknown",
            "gender": "unknown",
            "pose": "unknown",
            "needs_user_confirmation": True,
        },
        "mode": describe_mode,
        "limits": [
            "basic mode does not infer subject attributes to avoid hallucination.",
        ],
    }

    out["classification"] = _classify_palette(overall_palette, grayscale_like)

    if describe_mode == "vision":
        # ── Fire VLM in parallel with CV pipeline ────────────────────
        # VLM only needs the image path — completely independent of CV.
        # Starting it here lets the API round-trip overlap with MediaPipe,
        # cue extraction, and the 30+ vision passes, cutting wall time ~40%.
        # run_vlm gates ONLY the VLM.  The CV pipeline below runs either way
        # (VL: the VLM is hinting, not ground truth -- an engine that cannot
        # analyze without it has that backwards).
        _vlm_future: Optional[Future] = None
        _vlm_executor: Optional[ThreadPoolExecutor] = None
        _img_hash = _image_hash(path) if run_vlm else None
        _vlm_cached = _load_vlm_cache(_img_hash) if run_vlm else None

        if run_vlm and _vlm_cached is None:
            try:
                from engine.vlm import describe_reference_image, vlm_available
                if vlm_available():
                    _vlm_executor = ThreadPoolExecutor(max_workers=1)
                    _vlm_future = _vlm_executor.submit(describe_reference_image, path)
            except Exception:
                pass

        vision = analyze_image_regions(path, return_masks=True)

        # ── Visual cue extraction (when masks available) ──
        cue_report = None
        if vision.get("ok") and "_masks" in vision:
            try:
                from engine.cue_extraction import extract_visual_cues

                classification_with_gs = dict(out.get("classification", {}))
                classification_with_gs["_is_grayscale_like"] = grayscale_like

                cue_report = extract_visual_cues(
                    vision["_img_bgr"],
                    vision,
                    classification_with_gs,
                )
            except Exception:
                pass  # cue extraction is best-effort

        # Preserve raw image, masks, and face_box for the extended pipeline
        # and debug overlay generation.  These are stored as underscore-prefixed
        # keys and stripped before API serialization, just like _cue_report and
        # _vlm_description.
        if vision.get("ok"):
            out["_debug_img_bgr"] = vision.get("_img_bgr")
            masks = vision.get("_masks", {})
            out["_debug_masks"] = masks
            ra = vision.get("region_attribution", {})
            fb = ra.get("face_box")
            out["_debug_face_box"] = tuple(fb) if fb else None

        # Strip internal fields before storing in output
        vision.pop("_masks", None)
        vision.pop("_img_bgr", None)
        out["vision"] = vision

        # Include cue report summary (not raw numpy data)
        if cue_report is not None:
            out["cue_report"] = cue_report.model_dump()
        else:
            out["cue_report"] = None

        # Store cue_report object for downstream use (e.g. lighting inference)
        out["_cue_report"] = cue_report

        # bubble up pose if available
        try:
            pose = vision.get("pose", {})
            if isinstance(pose, dict) and pose.get("ok"):
                out["subject"]["pose"] = pose.get("pose", "unknown")
        except Exception:
            pass

        # ── Collect VLM result (started in parallel above) ───────────
        vlm_desc = None
        _vlm_error: Optional[str] = None
        if not run_vlm:
            pass  # VLM deliberately skipped — CV-only run, not an error
        elif _vlm_cached is not None:
            # Cache hit — reconstruct from disk
            try:
                from engine.image_analysis_models import VLMDescription
                vlm_desc = VLMDescription.model_validate(_vlm_cached)
            except Exception as _ce:
                _vlm_error = f"Cache deserialize error: {_ce}"
        elif _vlm_future is not None:
            try:
                vlm_desc = _vlm_future.result(timeout=60)
                if vlm_desc is not None and getattr(vlm_desc, "ok", False):
                    _save_vlm_cache(_img_hash, vlm_desc.model_dump())
            except Exception as _vlm_exc:
                import logging as _log
                _log.getLogger(__name__).error("VLM call failed: %s", _vlm_exc)
                _vlm_error = str(_vlm_exc)
        else:
            # _vlm_future was never submitted — vlm_available() returned False or import failed
            try:
                from engine.vlm import vlm_available as _va, _VLM_PROVIDER as _provider
                if not _va():
                    _vlm_error = f"VLM not configured (provider={_provider or 'none'})"
            except Exception:
                _vlm_error = "VLM module unavailable"
        if _vlm_executor is not None:
            _vlm_executor.shutdown(wait=False)

        if vlm_desc is not None:
            out["vlm_description"] = vlm_desc.model_dump()
        else:
            out["vlm_description"] = None
        out["_vlm_description"] = vlm_desc
        out["_vlm_error"] = _vlm_error  # surfaced to UI for diagnostics

    return out
