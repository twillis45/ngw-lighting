"""Reference Ingestion — validates, stores, and indexes reference images.

Provides a clean ingestion workflow for adding reference images to the NGW
reference library.  Images are stored under:

    data/reference_library/<pattern_id>/<basename>.jpg
    data/reference_library/<pattern_id>/<basename>.json  (sidecar metadata)

A central index at data/reference_index.json is rebuilt automatically after
each ingestion.  The index aggregates:
  1. Sidecar metadata from pattern folders (image-backed references)
  2. Existing entries from data/reference_library/references.json (legacy)

The reference_matcher module can load from either source.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REFERENCE_LIBRARY_DIR = _DATA_DIR / "reference_library"
REFERENCE_INDEX_PATH = _DATA_DIR / "reference_index.json"
LEGACY_REFERENCES_PATH = REFERENCE_LIBRARY_DIR / "references.json"
PATTERN_CATALOG_PATH = _DATA_DIR / "patterns" / "pattern_catalog.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

# ═══════════════════════════════════════════════════════════════════════════
# VALID PATTERN IDS
# ═══════════════════════════════════════════════════════════════════════════

_PATTERN_IDS_CACHE: Optional[List[str]] = None


def _load_valid_pattern_ids() -> List[str]:
    """Valid pattern IDs, from the TAXONOMY — the declared enum authority.

    Was read from data/patterns/pattern_catalog.json, a second source of truth
    that had drifted 9 patterns behind: axial, flat, gobo_projection, hybrid,
    projected, rim, silhouette_key, triangle and unknown were all valid in
    engine/taxonomy.py and rejected by this validator.

    Found 2026-08-31: four dataset entries already on disk could not pass the
    gate meant to protect them — including the two remapped to "projected"
    earlier the same session, since the remap updated ground_truth and this
    file had never heard of the new name. A gate that rejects the corpus it
    guards proves nothing about that corpus.

    CLAUDE.md names docs/TAXONOMY_TRUTH.md and the taxonomy enum as authority
    for canonical pattern names. The JSON catalog duplicated that list for one
    purpose — this check — while its other fields (name, category, description,
    canonical_setup) are read by nothing in the codebase. Reading the enum
    directly removes the drift permanently rather than resyncing two files that
    will drift again.

    The JSON remains as the fallback so a broken import degrades rather than
    rejecting everything.
    """
    global _PATTERN_IDS_CACHE
    if _PATTERN_IDS_CACHE is not None:
        return _PATTERN_IDS_CACHE
    try:
        from engine.taxonomy import LightingPattern
        _PATTERN_IDS_CACHE = [p.value for p in LightingPattern]
        return _PATTERN_IDS_CACHE
    except Exception as exc:
        logger.warning("Taxonomy unavailable, falling back to the JSON catalog: %s", exc)
    try:
        with open(PATTERN_CATALOG_PATH, "r") as f:
            catalog = json.load(f)
        _PATTERN_IDS_CACHE = [p["pattern_id"] for p in catalog.get("patterns", [])]
        return _PATTERN_IDS_CACHE
    except Exception as exc:
        logger.warning("Failed to load pattern catalog: %s", exc)
        return []


# ═══════════════════════════════════════════════════════════════════════════
# METADATA SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED_FIELDS = {
    "reference_id",
    "pattern_id",
    "photographer",
    "dataset_tier",
    "entry_trust_score",
}

OPTIONAL_FIELDS = {
    "title",
    "source_type",
    "source_url",
    "environment",
    "light_count",
    "key_direction_deg",
    "key_height_relative",
    "shadow_pattern",
    "modifier_family",
    "estimated_distance_ft",
    "matched_setup_ids",
    "notes",
    # Legacy fields (carried from references.json entries)
    "lighting_pattern",
    "lights",
    "shadow_signature",
    "camera",
    "use_cases",
    "lighting_notes",
    # Archetype-related fields
    "style_family",
    "catchlight_pattern",
    "underfill_ev",
    "separation_light_type",
    "source_type_candidates",
    "light_technology",
    "master_profile_id",
}

ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

VALID_DATASET_TIERS = {"gold", "community", "synthetic"}
VALID_SOURCE_TYPES = {"original_photo", "screenshot", "studio_test", "found_online", "book_scan", "ai_generated"}
VALID_ENVIRONMENTS = {"studio", "natural", "window_light", "outdoor", "mixed", "unknown"}
VALID_KEY_HEIGHTS = {"below_eye_level", "eye_level", "above_eye_level", "high", "overhead"}


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate_metadata(metadata: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate reference metadata against the schema.

    Returns (is_valid, list_of_error_messages).
    """
    errors: List[str] = []

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in metadata or metadata[field] is None:
            errors.append(f"Missing required field: '{field}'")

    if errors:
        return False, errors

    # Type checks
    ref_id = metadata.get("reference_id", "")
    if not isinstance(ref_id, str) or not ref_id.strip():
        errors.append("reference_id must be a non-empty string")

    pattern_id = metadata.get("pattern_id", "")
    if not isinstance(pattern_id, str) or not pattern_id.strip():
        errors.append("pattern_id must be a non-empty string")
    else:
        valid_patterns = _load_valid_pattern_ids()
        if valid_patterns and pattern_id not in valid_patterns:
            errors.append(
                f"pattern_id '{pattern_id}' not found in pattern catalog. "
                f"Valid patterns: {', '.join(sorted(valid_patterns))}"
            )

    tier = metadata.get("dataset_tier", "")
    if tier not in VALID_DATASET_TIERS:
        errors.append(f"dataset_tier must be one of {sorted(VALID_DATASET_TIERS)}, got '{tier}'")

    trust = metadata.get("entry_trust_score")
    if not isinstance(trust, (int, float)) or not (0.0 <= trust <= 1.0):
        errors.append(f"entry_trust_score must be a number between 0.0 and 1.0, got {trust!r}")

    # Optional field validation
    source_type = metadata.get("source_type")
    if source_type is not None and source_type not in VALID_SOURCE_TYPES:
        errors.append(f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}, got '{source_type}'")

    environment = metadata.get("environment")
    if environment is not None and environment not in VALID_ENVIRONMENTS:
        errors.append(f"environment must be one of {sorted(VALID_ENVIRONMENTS)}, got '{environment}'")

    key_height = metadata.get("key_height_relative")
    if key_height is not None and key_height not in VALID_KEY_HEIGHTS:
        errors.append(f"key_height_relative must be one of {sorted(VALID_KEY_HEIGHTS)}, got '{key_height}'")

    key_dir = metadata.get("key_direction_deg")
    if key_dir is not None:
        if not isinstance(key_dir, (int, float)) or not (0 <= key_dir <= 360):
            errors.append(f"key_direction_deg must be a number 0-360, got {key_dir!r}")

    light_count = metadata.get("light_count")
    if light_count is not None:
        if not isinstance(light_count, int) or light_count < 0:
            errors.append(f"light_count must be a non-negative integer, got {light_count!r}")

    distance = metadata.get("estimated_distance_ft")
    if distance is not None:
        if not isinstance(distance, (int, float)) or distance <= 0:
            errors.append(f"estimated_distance_ft must be a positive number, got {distance!r}")

    matched_ids = metadata.get("matched_setup_ids")
    if matched_ids is not None and not isinstance(matched_ids, list):
        errors.append("matched_setup_ids must be a list")

    return len(errors) == 0, errors


def validate_filename_consistency(
    image_path: Path,
    metadata: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """Validate that image filename and pattern folder are consistent.

    Checks:
    - Image extension is valid
    - If image is already in a pattern folder, the folder matches pattern_id
    - reference_id doesn't conflict with existing entries

    Returns (is_valid, list_of_error_messages).
    """
    errors: List[str] = []

    # Extension check
    if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
        errors.append(
            f"Image extension '{image_path.suffix}' not supported. "
            f"Use one of: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )

    # Folder consistency (if image is already in a pattern subfolder)
    pattern_id = metadata.get("pattern_id", "")
    if image_path.parent.name != "reference_library" and image_path.parent.name != pattern_id:
        # Only warn if the image is inside the reference_library tree
        if REFERENCE_LIBRARY_DIR in image_path.parents or str(REFERENCE_LIBRARY_DIR) in str(image_path):
            errors.append(
                f"Image is in folder '{image_path.parent.name}' "
                f"but pattern_id is '{pattern_id}'. They should match."
            )

    return len(errors) == 0, errors


# ═══════════════════════════════════════════════════════════════════════════
# INGESTION
# ═══════════════════════════════════════════════════════════════════════════

def ingest_reference(
    image_path: str | Path,
    metadata: Dict[str, Any],
    *,
    reference_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Ingest a reference image into the library.

    Steps:
    1. Validate metadata
    2. Validate filename consistency
    3. Create pattern folder if needed
    4. Copy image to pattern folder (unless already there)
    5. Write sidecar JSON
    6. Rebuild the central index

    Args:
        image_path: Path to the source image file.
        metadata: Reference metadata dict.
        reference_dir: Override for the reference library root directory.
        overwrite: If True, overwrite existing sidecar/image files.

    Returns:
        Dict with 'status', 'reference_id', 'image_path', 'sidecar_path',
        'pattern_folder', 'index_path', and 'errors' (if any warnings).

    Raises:
        ValueError: If metadata validation fails.
        FileNotFoundError: If the source image doesn't exist.
    """
    image_path = Path(image_path)
    ref_dir = reference_dir or REFERENCE_LIBRARY_DIR

    # Validate
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    valid, meta_errors = validate_metadata(metadata)
    if not valid:
        raise ValueError(f"Metadata validation failed:\n  " + "\n  ".join(meta_errors))

    valid_file, file_errors = validate_filename_consistency(image_path, metadata)
    # File errors are warnings, not fatal
    warnings = file_errors[:]

    pattern_id = metadata["pattern_id"]
    reference_id = metadata["reference_id"]

    # Create pattern folder
    pattern_folder = ref_dir / pattern_id
    pattern_folder.mkdir(parents=True, exist_ok=True)

    # Determine target image path
    target_image = pattern_folder / image_path.name
    if target_image.exists() and not overwrite:
        warnings.append(f"Image already exists at {target_image}, skipping copy")
    elif image_path.resolve() != target_image.resolve():
        shutil.copy2(str(image_path), str(target_image))
        logger.info("Copied image to %s", target_image)
    # else: image is already in the right place

    # Write sidecar JSON
    sidecar_path = pattern_folder / f"{image_path.stem}.json"
    sidecar_data = {**metadata}
    sidecar_data["image_file"] = image_path.name

    if sidecar_path.exists() and not overwrite:
        warnings.append(f"Sidecar already exists at {sidecar_path}, skipping write")
    else:
        with open(sidecar_path, "w") as f:
            json.dump(sidecar_data, f, indent=2)
        logger.info("Wrote sidecar to %s", sidecar_path)

    # Rebuild index
    index = rebuild_index(reference_dir=ref_dir)

    return {
        "status": "ok",
        "reference_id": reference_id,
        "image_path": str(target_image),
        "sidecar_path": str(sidecar_path),
        "pattern_folder": str(pattern_folder),
        "index_path": str(REFERENCE_INDEX_PATH),
        "index_entry_count": index.get("total_entries", 0),
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════
# INDEX MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def rebuild_index(
    *,
    reference_dir: Optional[Path] = None,
    include_legacy: bool = True,
) -> Dict[str, Any]:
    """Rebuild data/reference_index.json from sidecar files and legacy entries.

    Scans all pattern subfolders for *.json sidecar files, merges with
    legacy references.json entries that don't have image backing.

    Args:
        reference_dir: Override for reference library root.
        include_legacy: Whether to include legacy references.json entries.

    Returns:
        The index dict that was written to disk.
    """
    ref_dir = reference_dir or REFERENCE_LIBRARY_DIR
    entries: List[Dict[str, Any]] = []
    seen_ids: set = set()

    # Phase 1: Scan pattern subfolders for sidecar files
    if ref_dir.exists():
        for pattern_folder in sorted(ref_dir.iterdir()):
            if not pattern_folder.is_dir():
                continue
            # Skip hidden folders
            if pattern_folder.name.startswith("."):
                continue

            for sidecar_file in sorted(pattern_folder.glob("*.json")):
                try:
                    with open(sidecar_file, "r") as f:
                        sidecar = json.load(f)

                    ref_id = sidecar.get("reference_id")
                    if not ref_id:
                        logger.warning("Sidecar %s missing reference_id, skipping", sidecar_file)
                        continue

                    if ref_id in seen_ids:
                        logger.warning("Duplicate reference_id '%s' in %s, skipping", ref_id, sidecar_file)
                        continue

                    # Ensure backward-compatible fields are present
                    # pattern_id → lighting_pattern (matcher uses lighting_pattern)
                    if "lighting_pattern" not in sidecar and "pattern_id" in sidecar:
                        sidecar["lighting_pattern"] = sidecar["pattern_id"]
                    if "pattern_id" not in sidecar and "lighting_pattern" in sidecar:
                        sidecar["pattern_id"] = sidecar["lighting_pattern"]

                    # Add image path relative to data/
                    image_file = sidecar.get("image_file")
                    if image_file:
                        image_path = pattern_folder / image_file
                        sidecar["image_path"] = str(image_path.relative_to(ref_dir.parent))
                        sidecar["has_image"] = image_path.exists()
                    else:
                        sidecar["has_image"] = False

                    sidecar["_source"] = "sidecar"
                    sidecar["_sidecar_path"] = str(sidecar_file.relative_to(ref_dir.parent))

                    entries.append(sidecar)
                    seen_ids.add(ref_id)

                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Failed to parse sidecar %s: %s", sidecar_file, exc)

    # Phase 2: Merge legacy references.json entries (those not already in index)
    if include_legacy and LEGACY_REFERENCES_PATH.exists():
        try:
            with open(LEGACY_REFERENCES_PATH, "r") as f:
                legacy_entries = json.load(f)

            for entry in legacy_entries:
                ref_id = entry.get("reference_id")
                if not ref_id or ref_id in seen_ids:
                    continue

                entry["has_image"] = False
                entry["_source"] = "legacy"
                # Map legacy field names for consistency
                if "lighting_pattern" in entry and "pattern_id" not in entry:
                    entry["pattern_id"] = entry["lighting_pattern"]

                entries.append(entry)
                seen_ids.add(ref_id)

        except Exception as exc:
            logger.warning("Failed to load legacy references: %s", exc)

    # Sort by reference_id for stable output
    entries.sort(key=lambda e: e.get("reference_id", ""))

    # Build index
    index = {
        "_schema_version": "1.0.0",
        "_description": (
            "Auto-generated reference image index. "
            "DO NOT EDIT — rebuilt by engine/reference_ingestion.py"
        ),
        "total_entries": len(entries),
        "image_backed_count": sum(1 for e in entries if e.get("has_image")),
        "legacy_count": sum(1 for e in entries if e.get("_source") == "legacy"),
        "entries": entries,
    }

    # Write index
    index_path = REFERENCE_INDEX_PATH
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

    logger.info(
        "Rebuilt reference index: %d entries (%d image-backed, %d legacy)",
        len(entries),
        index["image_backed_count"],
        index["legacy_count"],
    )

    return index


def get_index() -> Dict[str, Any]:
    """Load the current reference index from disk.

    If the index doesn't exist, rebuild it first.
    """
    if not REFERENCE_INDEX_PATH.exists():
        return rebuild_index()

    try:
        with open(REFERENCE_INDEX_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load reference index, rebuilding: %s", exc)
        return rebuild_index()


def get_indexed_entries() -> List[Dict[str, Any]]:
    """Return all entries from the reference index."""
    index = get_index()
    return index.get("entries", [])


# ═══════════════════════════════════════════════════════════════════════════
# SIDECAR GENERATION (for migrating legacy entries)
# ═══════════════════════════════════════════════════════════════════════════

def generate_legacy_sidecars(
    *,
    reference_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> List[Dict[str, str]]:
    """Generate sidecar stub files for legacy references.json entries.

    Creates pattern subfolders and sidecar JSON files for each legacy entry
    that doesn't already have one.  No image files are created — the sidecars
    will have has_image=False until real images are added.

    Returns list of {reference_id, pattern_id, sidecar_path, status}.
    """
    ref_dir = reference_dir or REFERENCE_LIBRARY_DIR
    results: List[Dict[str, str]] = []

    if not LEGACY_REFERENCES_PATH.exists():
        return results

    try:
        with open(LEGACY_REFERENCES_PATH, "r") as f:
            legacy_entries = json.load(f)
    except Exception:
        return results

    for entry in legacy_entries:
        ref_id = entry.get("reference_id", "")
        pattern_id = entry.get("lighting_pattern", "") or entry.get("pattern_id", "")

        if not ref_id or not pattern_id:
            results.append({
                "reference_id": ref_id,
                "pattern_id": pattern_id,
                "sidecar_path": "",
                "status": "skipped_no_id",
            })
            continue

        pattern_folder = ref_dir / pattern_id
        sidecar_path = pattern_folder / f"{ref_id}.json"

        if sidecar_path.exists():
            results.append({
                "reference_id": ref_id,
                "pattern_id": pattern_id,
                "sidecar_path": str(sidecar_path),
                "status": "already_exists",
            })
            continue

        if dry_run:
            results.append({
                "reference_id": ref_id,
                "pattern_id": pattern_id,
                "sidecar_path": str(sidecar_path),
                "status": "would_create",
            })
            continue

        # Build sidecar from legacy entry
        sidecar = {
            "reference_id": ref_id,
            "pattern_id": pattern_id,
            "photographer": entry.get("photographer", ""),
            "dataset_tier": entry.get("dataset_tier", "gold"),
            "entry_trust_score": entry.get("entry_trust_score", 1.0),
            "environment": entry.get("environment", "studio"),
            "notes": entry.get("lighting_notes", ""),
        }

        # Carry forward rich fields from legacy
        for field in ("lights", "shadow_signature", "camera", "use_cases"):
            if field in entry:
                sidecar[field] = entry[field]

        # Compute derived fields from legacy light data
        lights = entry.get("lights", [])
        if lights:
            sidecar["light_count"] = len(lights)
            key_light = next((l for l in lights if l.get("role") == "key"), None)
            if key_light:
                if "angle_deg" in key_light:
                    sidecar["key_direction_deg"] = key_light["angle_deg"]
                if "modifier" in key_light:
                    sidecar["modifier_family"] = key_light["modifier"]
                if "distance_ft" in key_light:
                    sidecar["estimated_distance_ft"] = key_light["distance_ft"]

        shadow_sig = entry.get("shadow_signature", {})
        if shadow_sig:
            sidecar["shadow_pattern"] = entry.get("lighting_pattern", "")

        camera = entry.get("camera", {})
        if camera.get("height_relative"):
            sidecar["key_height_relative"] = camera["height_relative"]

        # Write
        pattern_folder.mkdir(parents=True, exist_ok=True)
        with open(sidecar_path, "w") as f:
            json.dump(sidecar, f, indent=2)

        results.append({
            "reference_id": ref_id,
            "pattern_id": pattern_id,
            "sidecar_path": str(sidecar_path),
            "status": "created",
        })

    return results
