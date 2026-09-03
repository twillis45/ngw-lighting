"""Reference Dataset — image-backed reference storage with pipeline signals.

Extends the existing reference library with full pipeline signal persistence,
VLM reconstruction storage, approval workflow, and dataset versioning.

Storage layout:

    data/reference_dataset/
      _version.json                          dataset version metadata
      <pattern_id>/
        <reference_id>/
          image.jpg                          original (resized <=2048 long edge)
          metadata.json                      user-authored fields
          signals.json                       full pipeline output (27+ pass keys)
          vlm_reconstruction.json            VLM reconstruction output
          debug_overlay.png                  visual debug composite
          thumbnail.jpg                      256px thumbnail for list view

Parallel to the existing ``data/reference_library/`` — no existing files are
modified.  The existing ``engine/reference_ingestion.py`` validation helpers
are reused.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from engine.reference_ingestion import (
    IMAGE_EXTENSIONS,
    VALID_DATASET_TIERS,
    VALID_ENVIRONMENTS,
    VALID_KEY_HEIGHTS,
    VALID_SOURCE_TYPES,
    validate_metadata as _validate_ingestion_metadata,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATASET_ROOT = _DATA_DIR / "reference_dataset"

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

VALID_APPROVAL_STATUSES = {"draft", "approved", "rejected"}
MAX_IMAGE_EDGE = 2048
THUMBNAIL_SIZE = 256

# Binary / non-JSON keys to strip from pipeline results
_STRIP_KEYS = {
    "_debug_img_bgr",
    "_debug_masks",
    "_debug_face_box",
    "_img_bgr",
    "_masks",
}


# ═══════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _now_iso() -> str:
    """Return current UTC datetime as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_dataset_root(root: Optional[Path] = None) -> Path:
    """Create dataset root and version file if they don't exist.

    `root` added 2026-09-02. Every public function here resolves
    `root = dataset_root or DATASET_ROOT` so a test can point at a tmp dir --
    and then called this helper and `_update_version_count`, both of which read
    the module GLOBAL and ignored it. So an ingest test using a tmp root still
    wrote the real repo corpus's _version.json, and every suite run left
    `M data/reference_dataset/_version.json` in the tree.

    Committing that stamp does not fix it (98b132f tried); the next run dirties
    it again. Honouring the argument does.
    """
    root = root or DATASET_ROOT
    root.mkdir(parents=True, exist_ok=True)
    version_path = root / "_version.json"
    if not version_path.exists():
        version_data = {
            "schema_version": "1.0.0",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "entry_count": 0,
        }
        with open(version_path, "w") as f:
            json.dump(version_data, f, indent=2)
    return DATASET_ROOT


def _entry_dir(pattern_id: str, reference_id: str) -> Path:
    """Return the entry directory path (may not exist yet)."""
    return DATASET_ROOT / pattern_id / reference_id


def _save_json(path: Path, data: Any) -> None:
    """Write JSON with indent=2, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path) -> Optional[Dict]:
    """Load JSON file, return None if missing or invalid."""
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types to primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        if obj.size > 200:
            return f"<ndarray shape={obj.shape}>"
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"
    # Fallback: str representation
    try:
        return str(obj)
    except Exception:
        return "<non-serializable>"


def _strip_binary(results: Dict[str, Any]) -> Dict[str, Any]:
    """Remove numpy arrays, large binary data, and internal debug keys.

    Keeps all pipeline pass results as JSON-safe primitives.
    """
    out: Dict[str, Any] = {}
    for key, val in results.items():
        if key in _STRIP_KEYS:
            continue
        out[key] = _sanitize_for_json(val)
    return out


def _resize_image(img_bgr: np.ndarray, max_edge: int = MAX_IMAGE_EDGE) -> np.ndarray:
    """Resize image so longest edge <= max_edge, preserving aspect ratio."""
    if cv2 is None:
        return img_bgr
    h, w = img_bgr.shape[:2]
    if max(h, w) <= max_edge:
        return img_bgr
    scale = max_edge / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    return cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _make_thumbnail(img_bgr: np.ndarray, size: int = THUMBNAIL_SIZE) -> np.ndarray:
    """Create a square-cropped thumbnail at the given size."""
    if cv2 is None:
        return img_bgr
    h, w = img_bgr.shape[:2]
    # Center crop to square
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    cropped = img_bgr[y0 : y0 + side, x0 : x0 + side]
    return cv2.resize(cropped, (size, size), interpolation=cv2.INTER_AREA)


def _update_version_count(root: Optional[Path] = None) -> None:
    """Recount entries and update _version.json. See _ensure_dataset_root."""
    root = root or DATASET_ROOT
    version_path = root / "_version.json"
    version = _load_json(version_path) or {}
    count = 0
    if root.exists():
        for pattern_dir in root.iterdir():
            if pattern_dir.is_dir() and not pattern_dir.name.startswith("_"):
                for entry_dir in pattern_dir.iterdir():
                    if entry_dir.is_dir() and (entry_dir / "metadata.json").exists():
                        count += 1
    version["entry_count"] = count
    version["updated_at"] = _now_iso()
    _save_json(version_path, version)


# ═══════════════════════════════════════════════════════════════════════════
# DATASET METADATA VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

# Dataset-specific required fields (subset of ingestion fields — we relax
# entry_trust_score to optional with a default)
DATASET_REQUIRED_FIELDS = {"reference_id", "pattern_id", "photographer", "dataset_tier"}

# Additional dataset-specific optional fields beyond what ingestion validates
DATASET_EXTRA_FIELDS = {
    "tags",
    "approval_status",
    "approved_by",
    "approved_at",
    "ingested_at",
    "rejection_reason",
    # Archetype-related fields
    "style_family",
    "catchlight_pattern",
    "underfill_ev",
    "separation_light_type",
    "source_type_candidates",
    "light_technology",
    "master_profile_id",
}


def validate_dataset_metadata(metadata: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate metadata for dataset ingestion.

    Reuses the core ingestion validation but relaxes entry_trust_score
    (defaults to 0.5 if missing) and accepts dataset-specific fields.
    """
    # Set defaults before validation
    meta = dict(metadata)
    if "entry_trust_score" not in meta:
        meta["entry_trust_score"] = 0.5
    if "approval_status" not in meta:
        meta["approval_status"] = "draft"

    # Validate approval_status if provided
    errors: List[str] = []
    status = meta.get("approval_status", "draft")
    if status not in VALID_APPROVAL_STATUSES:
        errors.append(
            f"approval_status must be one of {sorted(VALID_APPROVAL_STATUSES)}, "
            f"got '{status}'"
        )

    # Run base ingestion validation
    valid, base_errors = _validate_ingestion_metadata(meta)
    errors.extend(base_errors)

    return len(errors) == 0, errors


# ═══════════════════════════════════════════════════════════════════════════
# ARCHETYPE FIELD AUTO-POPULATION
# ═══════════════════════════════════════════════════════════════════════════


def _auto_populate_archetype_fields(
    meta: Dict[str, Any],
    pipeline_results: Dict[str, Any],
) -> None:
    """Auto-populate archetype-related metadata fields from pipeline results.

    Only sets fields that are not already present in the metadata (user-provided
    values always take precedence).  Modifies *meta* in place.

    Pipeline keys consulted:
        catchlight_topology  → catchlight_pattern
        highlight_symmetry   → underfill_ev
        separation_light     → separation_light_type
        continuous_source    → light_technology, source_type_candidates
    """
    # --- catchlight_pattern ---
    if "catchlight_pattern" not in meta:
        topo = pipeline_results.get("catchlight_topology", {})
        if isinstance(topo, dict) and topo.get("ok"):
            geom = topo.get("cluster_geometry")
            if geom and geom != "unknown":
                meta["catchlight_pattern"] = geom

    # --- underfill_ev ---
    if "underfill_ev" not in meta:
        sym = pipeline_results.get("highlight_symmetry", {})
        if isinstance(sym, dict) and sym.get("ok"):
            ev = sym.get("underfill_ev")
            if ev is not None:
                meta["underfill_ev"] = round(float(ev), 2)

    # --- separation_light_type ---
    if "separation_light_type" not in meta:
        sep = pipeline_results.get("separation_light", {})
        if isinstance(sep, dict) and sep.get("ok"):
            if sep.get("has_hair_light"):
                meta["separation_light_type"] = "hair"
            elif sep.get("has_rim_light"):
                meta["separation_light_type"] = "rim"
            else:
                meta["separation_light_type"] = "none"

    # --- light_technology + source_type_candidates ---
    cs = pipeline_results.get("continuous_source", {})
    if isinstance(cs, dict) and cs.get("ok"):
        if "light_technology" not in meta:
            tech = cs.get("likely_technology")
            if tech and tech != "unknown":
                meta["light_technology"] = tech
        if "source_type_candidates" not in meta:
            evidence = cs.get("evidence", [])
            if evidence:
                meta["source_type_candidates"] = list(evidence)


# ═══════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════


def ingest_reference_image(
    image_path: str | Path,
    metadata: Dict[str, Any],
    *,
    run_pipeline: bool = True,
    run_vlm: bool = True,
    generate_debug_overlay: bool = True,
    overwrite: bool = False,
    dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Full ingestion: validate, copy image, run pipeline, store everything.

    Steps:
        1. Validate metadata
        2. Read and resize image
        3. Create entry directory
        4. Save resized image + thumbnail
        5. Run extended pipeline (optional)
        6. Store pipeline signals as signals.json
        7. Store VLM reconstruction as vlm_reconstruction.json
        8. Generate debug overlay (optional)
        9. Write metadata.json with timestamps
        10. Update dataset version

    Args:
        image_path: Path to the source image file.
        metadata: Reference metadata dict.
        run_pipeline: If True, run the full extended vision pipeline.
        run_vlm: If True, allow VLM reconstruction (only if pipeline runs).
        generate_debug_overlay: If True, generate visual debug overlay.
        overwrite: If True, overwrite existing entry.
        dataset_root: Override for the dataset root directory (for testing).

    Returns:
        Dict with status info: ok, reference_id, entry_path, pipeline_ok,
        vlm_ok, overlay_path, warnings.

    Raises:
        FileNotFoundError: If the source image doesn't exist.
        ValueError: If metadata validation fails.
        FileExistsError: If entry exists and overwrite is False.
    """
    root = dataset_root or DATASET_ROOT
    image_path = Path(image_path)
    warnings: List[str] = []

    # 1. Validate
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format: {image_path.suffix}. "
            f"Supported: {sorted(IMAGE_EXTENSIONS)}"
        )

    meta = dict(metadata)
    if "entry_trust_score" not in meta:
        meta["entry_trust_score"] = 0.5
    if "approval_status" not in meta:
        meta["approval_status"] = "draft"

    valid, errors = validate_dataset_metadata(meta)
    if not valid:
        raise ValueError(
            "Metadata validation failed:\n  " + "\n  ".join(errors)
        )

    pattern_id = meta["pattern_id"]
    reference_id = meta["reference_id"]

    # 2. Read image
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required for image ingestion")

    img_bgr = cv2.imread(str(image_path))
    if img_bgr is None:
        raise ValueError(f"Failed to read image: {image_path}")

    # 3. Create entry directory
    entry_path = root / pattern_id / reference_id
    if entry_path.exists() and not overwrite:
        raise FileExistsError(
            f"Entry already exists: {entry_path}. Use overwrite=True to replace."
        )
    entry_path.mkdir(parents=True, exist_ok=True)

    # 4. Save resized image + thumbnail
    resized = _resize_image(img_bgr)
    cv2.imwrite(
        str(entry_path / "image.jpg"),
        resized,
        [cv2.IMWRITE_JPEG_QUALITY, 92],
    )
    thumb = _make_thumbnail(resized)
    cv2.imwrite(
        str(entry_path / "thumbnail.jpg"),
        thumb,
        [cv2.IMWRITE_JPEG_QUALITY, 85],
    )

    # 5. Run extended pipeline (optional)
    pipeline_results = None
    pipeline_ok = False
    if run_pipeline:
        try:
            from engine.vision_passes import run_extended_pipeline

            # Attempt to get masks from basic analysis first
            person_mask = None
            skin_mask = None
            background_mask = None
            face_box = None

            try:
                from engine.image_analysis import analyze_image_regions

                region_data = analyze_image_regions(str(image_path), return_masks=True)
                if region_data.get("ok"):
                    masks = region_data.get("_masks", {})
                    if isinstance(masks, dict):
                        person_mask = masks.get("person")
                        skin_mask = masks.get("skin")
                        background_mask = masks.get("background")
                    ra = region_data.get("region_attribution", {})
                    fb = ra.get("face_box")
                    if fb:
                        face_box = tuple(fb)
            except Exception as exc:
                warnings.append(f"Region analysis failed: {exc}")

            pipeline_results = run_extended_pipeline(
                resized,
                person_mask=person_mask,
                skin_mask=skin_mask,
                background_mask=background_mask,
                face_box=face_box,
            )
            pipeline_ok = True
        except Exception as exc:
            warnings.append(f"Pipeline failed: {exc}")
            logger.warning("Pipeline failed for %s: %s", reference_id, exc)

    # 6. Store pipeline signals
    if pipeline_results is not None:
        signals = _strip_binary(pipeline_results)
        _save_json(entry_path / "signals.json", signals)

    # 7. Store VLM reconstruction
    vlm_ok = False
    if pipeline_results is not None and run_vlm:
        vlm_recon = pipeline_results.get("vlm_reconstruction")
        if vlm_recon is not None:
            _save_json(entry_path / "vlm_reconstruction.json", vlm_recon)
            vlm_ok = True
        else:
            warnings.append("VLM reconstruction not available")

    # 8. Generate debug overlay
    overlay_path = None
    if generate_debug_overlay and pipeline_results is not None:
        try:
            from engine.vision_debug import generate_analysis_overlay

            overlay_output = str(entry_path / "debug_overlay.png")
            result_path = generate_analysis_overlay(
                resized,
                pipeline_results,
                face_box=face_box if run_pipeline else None,
                person_mask=person_mask if run_pipeline else None,
                output_path=overlay_output,
            )
            if result_path:
                overlay_path = result_path
        except Exception as exc:
            warnings.append(f"Debug overlay failed: {exc}")

    # 8b. Auto-populate archetype fields from pipeline results
    if pipeline_results is not None:
        _auto_populate_archetype_fields(meta, pipeline_results)

    # 9. Write metadata
    meta["ingested_at"] = _now_iso()
    meta["has_signals"] = pipeline_ok
    meta["has_vlm_reconstruction"] = vlm_ok
    meta["has_debug_overlay"] = overlay_path is not None
    meta["image_dimensions"] = {
        "width": resized.shape[1],
        "height": resized.shape[0],
    }
    _save_json(entry_path / "metadata.json", meta)

    # 10. Update version
    _ensure_dataset_root(root)
    _update_version_count(root)

    return {
        "ok": True,
        "reference_id": reference_id,
        "pattern_id": pattern_id,
        "entry_path": str(entry_path),
        "pipeline_ok": pipeline_ok,
        "vlm_ok": vlm_ok,
        "overlay_path": overlay_path,
        "warnings": warnings,
    }


def get_entry(
    pattern_id: str,
    reference_id: str,
    *,
    include_signals: bool = True,
    include_vlm: bool = True,
    dataset_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Load a single entry with metadata, signals, and VLM reconstruction.

    Returns None if entry doesn't exist.
    """
    root = dataset_root or DATASET_ROOT
    entry_path = root / pattern_id / reference_id

    metadata = _load_json(entry_path / "metadata.json")
    if metadata is None:
        return None

    result: Dict[str, Any] = {
        "metadata": metadata,
        "pattern_id": pattern_id,
        "reference_id": reference_id,
        "entry_path": str(entry_path),
        "has_image": (entry_path / "image.jpg").exists(),
        "has_thumbnail": (entry_path / "thumbnail.jpg").exists(),
        "has_debug_overlay": (entry_path / "debug_overlay.png").exists(),
    }

    if include_signals:
        result["signals"] = _load_json(entry_path / "signals.json")

    if include_vlm:
        result["vlm_reconstruction"] = _load_json(
            entry_path / "vlm_reconstruction.json"
        )

    return result


# Fields that only the system may write — never writable via API
_SYSTEM_LOCKED_FIELDS = {
    "reference_id", "pattern_id", "approval_status", "approved_by",
    "approved_at", "ingested_at", "rejection_reason",
}

# Enum constraints for user-editable fields
_ENUM_CONSTRAINTS: Dict[str, set] = {
    "dataset_tier": {"gold", "community", "synthetic"},
    "source_type": {"original_photo", "screenshot", "studio_test", "found_online", "book_scan", "ai_generated"},
    "environment": {"studio", "natural", "window_light", "outdoor", "mixed", "unknown"},
    "key_height_relative": {"below_eye_level", "eye_level", "above_eye_level", "high", "overhead"},
    "style_family": {"beauty", "editorial", "dramatic", "natural", "high_key", "low_key"},
    "catchlight_pattern": {"single", "dual", "triangular", "strip", "ring"},
    "separation_light_type": {"hair", "rim", "kicker", "none"},
    "light_technology": {"continuous_led", "continuous_panel", "strobe", "flash", "mixed"},
}


def update_reference_metadata(
    pattern_id: str,
    reference_id: str,
    updates: Dict[str, Any],
    *,
    dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Apply a partial metadata update to an existing reference entry.

    Validates enum fields before writing.  System-locked fields
    (reference_id, pattern_id, approval_status, ingested_at, etc.) are
    silently ignored even if present in ``updates``.

    Returns the updated metadata dict.

    Raises:
        FileNotFoundError — entry does not exist
        ValueError — one or more enum constraints violated (message lists all errors)
    """
    root = dataset_root or DATASET_ROOT
    entry_path = root / pattern_id / reference_id
    meta_path = entry_path / "metadata.json"

    if not meta_path.exists():
        raise FileNotFoundError(f"No metadata for {pattern_id}/{reference_id}")

    with open(meta_path, "r") as f:
        metadata: Dict[str, Any] = json.load(f)

    # Strip system-locked fields from the incoming update
    cleaned = {k: v for k, v in updates.items() if k not in _SYSTEM_LOCKED_FIELDS}

    # Validate enum fields
    errors: List[str] = []
    for field, valid_values in _ENUM_CONSTRAINTS.items():
        if field in cleaned and cleaned[field] is not None:
            if cleaned[field] not in valid_values:
                errors.append(
                    f"'{field}' must be one of {sorted(valid_values)}, got '{cleaned[field]}'"
                )

    # Validate numeric range fields
    trust = cleaned.get("entry_trust_score")
    if trust is not None:
        if not isinstance(trust, (int, float)) or not (0.0 <= float(trust) <= 1.0):
            errors.append(f"'entry_trust_score' must be 0.0–1.0, got {trust!r}")

    key_dir = cleaned.get("key_direction_deg")
    if key_dir is not None:
        if not isinstance(key_dir, (int, float)) or not (0 <= float(key_dir) <= 360):
            errors.append(f"'key_direction_deg' must be 0–360, got {key_dir!r}")

    light_count = cleaned.get("light_count")
    if light_count is not None:
        if not isinstance(light_count, int) or light_count < 0:
            errors.append(f"'light_count' must be a non-negative integer, got {light_count!r}")

    if errors:
        raise ValueError("; ".join(errors))

    # Merge and persist
    metadata.update(cleaned)
    _save_json(meta_path, metadata)

    logger.info("Updated metadata for %s/%s: fields=%s", pattern_id, reference_id, list(cleaned.keys()))
    return metadata


def list_entries(
    pattern_id: Optional[str] = None,
    status: Optional[str] = None,
    tier: Optional[str] = None,
    *,
    dataset_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List all entries with optional filters. Returns metadata only (no signals).

    Args:
        pattern_id: Filter by pattern (e.g., "rembrandt").
        status: Filter by approval_status ("draft", "approved", "rejected").
        tier: Filter by dataset_tier ("gold", "community", "synthetic").
        dataset_root: Override root directory (for testing).

    Returns:
        List of dicts with metadata + file presence flags.
    """
    root = dataset_root or DATASET_ROOT
    entries: List[Dict[str, Any]] = []

    if not root.exists():
        return entries

    # Determine which pattern dirs to scan
    if pattern_id:
        pattern_dirs = [root / pattern_id]
    else:
        pattern_dirs = sorted(
            d for d in root.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )

    for pdir in pattern_dirs:
        if not pdir.exists() or not pdir.is_dir():
            continue
        for edir in sorted(pdir.iterdir()):
            if not edir.is_dir():
                continue
            meta_path = edir / "metadata.json"
            meta = _load_json(meta_path)
            if meta is None:
                continue

            # Apply filters
            if status and meta.get("approval_status") != status:
                continue
            if tier and meta.get("dataset_tier") != tier:
                continue

            entries.append({
                "metadata": meta,
                "pattern_id": pdir.name,
                "reference_id": edir.name,
                "has_image": (edir / "image.jpg").exists(),
                "has_thumbnail": (edir / "thumbnail.jpg").exists(),
                "has_signals": (edir / "signals.json").exists(),
                "has_vlm_reconstruction": (edir / "vlm_reconstruction.json").exists(),
                "has_debug_overlay": (edir / "debug_overlay.png").exists(),
            })

    return entries


def approve_entry(
    pattern_id: str,
    reference_id: str,
    approved_by: str,
    *,
    dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Set approval_status to 'approved' with auditing fields.

    Returns updated metadata dict.
    Raises FileNotFoundError if entry doesn't exist.
    """
    root = dataset_root or DATASET_ROOT
    meta_path = root / pattern_id / reference_id / "metadata.json"
    meta = _load_json(meta_path)
    if meta is None:
        raise FileNotFoundError(
            f"Entry not found: {pattern_id}/{reference_id}"
        )

    meta["approval_status"] = "approved"
    meta["approved_by"] = approved_by
    meta["approved_at"] = _now_iso()
    meta.pop("rejection_reason", None)

    _save_json(meta_path, meta)
    return meta


def reject_entry(
    pattern_id: str,
    reference_id: str,
    reason: str = "",
    *,
    dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Set approval_status to 'rejected' with optional reason.

    Returns updated metadata dict.
    Raises FileNotFoundError if entry doesn't exist.
    """
    root = dataset_root or DATASET_ROOT
    meta_path = root / pattern_id / reference_id / "metadata.json"
    meta = _load_json(meta_path)
    if meta is None:
        raise FileNotFoundError(
            f"Entry not found: {pattern_id}/{reference_id}"
        )

    meta["approval_status"] = "rejected"
    meta["approved_by"] = None
    meta["approved_at"] = None
    if reason:
        meta["rejection_reason"] = reason

    _save_json(meta_path, meta)
    return meta


def reprocess_entry(
    pattern_id: str,
    reference_id: str,
    *,
    run_vlm: bool = True,
    generate_debug_overlay: bool = True,
    dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Re-run pipeline + VLM on an existing entry's image.

    Overwrites signals.json, vlm_reconstruction.json, and debug_overlay.png.
    Metadata is preserved but has_signals/has_vlm fields are updated.

    Returns status dict.
    Raises FileNotFoundError if entry or image doesn't exist.
    """
    root = dataset_root or DATASET_ROOT
    entry_path = root / pattern_id / reference_id
    image_path = entry_path / "image.jpg"
    meta_path = entry_path / "metadata.json"

    if not meta_path.exists():
        raise FileNotFoundError(f"Entry not found: {pattern_id}/{reference_id}")
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found for entry: {pattern_id}/{reference_id}")

    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required for reprocessing")

    img_bgr = cv2.imread(str(image_path))
    if img_bgr is None:
        raise ValueError(f"Failed to read image: {image_path}")

    warnings: List[str] = []
    pipeline_ok = False
    vlm_ok = False
    overlay_path = None

    # Get masks
    person_mask = None
    skin_mask = None
    background_mask = None
    face_box = None

    try:
        from engine.image_analysis import analyze_image_regions

        region_data = analyze_image_regions(str(image_path), return_masks=True)
        if region_data.get("ok"):
            masks = region_data.get("_masks", {})
            if isinstance(masks, dict):
                person_mask = masks.get("person")
                skin_mask = masks.get("skin")
                background_mask = masks.get("background")
            ra = region_data.get("region_attribution", {})
            fb = ra.get("face_box")
            if fb:
                face_box = tuple(fb)
    except Exception as exc:
        warnings.append(f"Region analysis failed: {exc}")

    # Run pipeline
    pipeline_results = None
    try:
        from engine.vision_passes import run_extended_pipeline

        pipeline_results = run_extended_pipeline(
            img_bgr,
            person_mask=person_mask,
            skin_mask=skin_mask,
            background_mask=background_mask,
            face_box=face_box,
        )
        pipeline_ok = True
    except Exception as exc:
        warnings.append(f"Pipeline failed: {exc}")

    # Store signals
    if pipeline_results is not None:
        signals = _strip_binary(pipeline_results)
        _save_json(entry_path / "signals.json", signals)

    # Store VLM reconstruction
    if pipeline_results is not None and run_vlm:
        vlm_recon = pipeline_results.get("vlm_reconstruction")
        if vlm_recon is not None:
            _save_json(entry_path / "vlm_reconstruction.json", vlm_recon)
            vlm_ok = True

    # Generate debug overlay
    if generate_debug_overlay and pipeline_results is not None:
        try:
            from engine.vision_debug import generate_analysis_overlay

            overlay_output = str(entry_path / "debug_overlay.png")
            result_path = generate_analysis_overlay(
                img_bgr,
                pipeline_results,
                face_box=face_box,
                person_mask=person_mask,
                output_path=overlay_output,
            )
            if result_path:
                overlay_path = result_path
        except Exception as exc:
            warnings.append(f"Debug overlay failed: {exc}")

    # Update metadata flags
    meta = _load_json(meta_path) or {}
    meta["has_signals"] = pipeline_ok
    meta["has_vlm_reconstruction"] = vlm_ok
    meta["has_debug_overlay"] = overlay_path is not None
    meta["reprocessed_at"] = _now_iso()
    _save_json(meta_path, meta)

    return {
        "ok": True,
        "reference_id": reference_id,
        "pattern_id": pattern_id,
        "pipeline_ok": pipeline_ok,
        "vlm_ok": vlm_ok,
        "overlay_path": overlay_path,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════
# VERSIONING
# ═══════════════════════════════════════════════════════════════════════════


def get_dataset_version(*, dataset_root: Optional[Path] = None) -> Dict[str, Any]:
    """Read _version.json for the dataset.

    Returns version dict, or defaults if file missing.
    """
    root = dataset_root or DATASET_ROOT
    version = _load_json(root / "_version.json")
    if version is None:
        return {
            "schema_version": "1.0.0",
            "created_at": None,
            "updated_at": None,
            "entry_count": 0,
        }
    return version


def bump_dataset_version(
    note: str = "",
    *,
    dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Increment the patch version and update timestamp.

    Args:
        note: Optional note to append to version history.
        dataset_root: Override root directory (for testing).

    Returns:
        Updated version dict.
    """
    root = dataset_root or DATASET_ROOT
    _ensure_dataset_root(root)
    version_path = root / "_version.json"
    version = _load_json(version_path) or {
        "schema_version": "1.0.0",
        "created_at": _now_iso(),
    }

    # Bump patch
    parts = version.get("schema_version", "1.0.0").split(".")
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        major, minor, patch = 1, 0, 0
    version["schema_version"] = f"{major}.{minor}.{patch + 1}"
    version["updated_at"] = _now_iso()

    # Count entries
    count = 0
    if root.exists():
        for pdir in root.iterdir():
            if pdir.is_dir() and not pdir.name.startswith("_"):
                for edir in pdir.iterdir():
                    if edir.is_dir() and (edir / "metadata.json").exists():
                        count += 1
    version["entry_count"] = count

    # Append note to history
    if note:
        history = version.get("history", [])
        history.append({"timestamp": _now_iso(), "note": note})
        version["history"] = history

    _save_json(version_path, version)
    return version


# ═══════════════════════════════════════════════════════════════════════════
# COMPARISON
# ═══════════════════════════════════════════════════════════════════════════


def compare_signals(
    entry_a_signals: Dict[str, Any],
    entry_b_signals: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare pipeline signals from two entries.

    Returns per-pass deltas with similarity scores.
    """
    passes = set(entry_a_signals.keys()) | set(entry_b_signals.keys())
    # Skip non-pass keys
    skip = {"_debug_img_bgr", "_debug_masks", "_debug_face_box", "ok"}
    passes -= skip

    comparison: Dict[str, Any] = {}
    for pass_name in sorted(passes):
        a_val = entry_a_signals.get(pass_name)
        b_val = entry_b_signals.get(pass_name)

        if a_val is None and b_val is None:
            continue

        entry: Dict[str, Any] = {
            "in_a": a_val is not None,
            "in_b": b_val is not None,
        }

        if isinstance(a_val, dict) and isinstance(b_val, dict):
            # Compare key-by-key for numeric values
            deltas: Dict[str, Any] = {}
            all_keys = set(a_val.keys()) | set(b_val.keys())
            for k in sorted(all_keys):
                av = a_val.get(k)
                bv = b_val.get(k)
                if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                    deltas[k] = {"a": av, "b": bv, "delta": abs(av - bv)}
                elif av != bv:
                    deltas[k] = {"a": av, "b": bv, "match": False}
                else:
                    deltas[k] = {"match": True}
            entry["deltas"] = deltas
        elif a_val != b_val:
            entry["match"] = False
        else:
            entry["match"] = True

        comparison[pass_name] = entry

    return {"passes_compared": len(comparison), "comparison": comparison}


# ═══════════════════════════════════════════════════════════════════════════
# MANIFEST / EXPORT
# ═══════════════════════════════════════════════════════════════════════════


def export_dataset_manifest(
    *, dataset_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate a full dataset manifest with statistics.

    Returns dict with entries list, pattern distribution, status counts, etc.
    """
    entries = list_entries(dataset_root=dataset_root)
    version = get_dataset_version(dataset_root=dataset_root)

    # Pattern distribution
    patterns: Dict[str, int] = {}
    statuses: Dict[str, int] = {"draft": 0, "approved": 0, "rejected": 0}
    tiers: Dict[str, int] = {"gold": 0, "community": 0, "synthetic": 0}
    with_signals = 0
    with_vlm = 0
    with_overlay = 0

    for e in entries:
        meta = e.get("metadata", {})
        pid = e.get("pattern_id", "unknown")
        patterns[pid] = patterns.get(pid, 0) + 1

        st = meta.get("approval_status", "draft")
        if st in statuses:
            statuses[st] += 1

        t = meta.get("dataset_tier", "community")
        if t in tiers:
            tiers[t] += 1

        if e.get("has_signals"):
            with_signals += 1
        if e.get("has_vlm_reconstruction"):
            with_vlm += 1
        if e.get("has_debug_overlay"):
            with_overlay += 1

    return {
        "version": version,
        "total_entries": len(entries),
        "pattern_distribution": patterns,
        "status_counts": statuses,
        "tier_counts": tiers,
        "with_signals": with_signals,
        "with_vlm_reconstruction": with_vlm,
        "with_debug_overlay": with_overlay,
        "entries": entries,
    }
