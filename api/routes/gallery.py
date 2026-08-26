"""Public accuracy gallery — known-truth setups, including the misses.

The product's whole claim is that it reads light correctly. Until now that
claim sat behind a sign-in wall, so nobody could audit it before paying. The
Working Photographer seat put it plainly: "I will not pay a cent for an oracle
I can't audit."

Everything served here already existed on disk, unserved: data/reference_dataset
holds curated entries with an image, a thumbnail, our stored analysis
(signals.json) and — the part that matters — human-verified ground truth.

The endpoint is deliberately public and deliberately shows misses. A gallery of
only hits is indistinguishable from a gallery of cherry-picks, and photographers
can smell curated results. Publishing the misses is what makes the hits
believable.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gallery", tags=["gallery"])

DATASET_DIR = Path("data/reference_dataset")

#: Only entries a human approved are eligible. An unreviewed entry is not
#: evidence, and this page exists to be evidence.
_APPROVED = "approved"


def _entry_dirs() -> List[Path]:
    if not DATASET_DIR.is_dir():
        return []
    return sorted(
        d for parent in DATASET_DIR.iterdir() if parent.is_dir()
        for d in parent.iterdir()
        if d.is_dir() and (d / "metadata.json").exists()
    )


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _verdict(meta: Dict[str, Any], signals: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare our stored read against human-verified ground truth.

    Returns the comparison honestly: `match` is None when we have no stored read
    rather than defaulting to a pass. An absent result is not a passing one.
    """
    gt = meta.get("ground_truth") or {}
    expected = gt.get("expected_pattern")
    acceptable = gt.get("acceptable_patterns") or ([expected] if expected else [])

    read_pattern = None
    read_confidence = None
    if signals:
        ls = signals.get("light_structure") or {}
        read_pattern = ls.get("pattern_name")
        read_confidence = ls.get("confidence")

    if read_pattern is None:
        return {"expected": expected, "read": None, "match": None,
                "note": "no stored read for this entry"}
    return {
        "expected": expected,
        "read": read_pattern,
        "confidence": read_confidence,
        "match": read_pattern in acceptable,
        "exact": read_pattern == expected,
    }


@router.get("")
def list_gallery() -> Dict[str, Any]:
    """Every approved entry, with ground truth and our read side by side."""
    items: List[Dict[str, Any]] = []
    for d in _entry_dirs():
        meta = _read_json(d / "metadata.json")
        if not meta or meta.get("approval_status") != _APPROVED:
            continue
        if not (d / "thumbnail.jpg").exists():
            continue
        signals = _read_json(d / "signals.json")
        gt = meta.get("ground_truth") or {}
        items.append({
            "id": meta.get("reference_id") or d.name,
            "pattern": meta.get("pattern_id"),
            "environment": meta.get("environment"),
            "source_type": meta.get("source_type"),
            "light_count": meta.get("light_count"),
            "key_direction_deg": meta.get("key_direction_deg"),
            "expected_light_count": gt.get("expected_light_count"),
            "thumbnail_url": f"/api/gallery/{meta.get('reference_id') or d.name}/thumbnail",
            "has_overlay": (d / "debug_overlay.png").exists(),
            "verdict": _verdict(meta, signals),
        })

    scored = [i for i in items if i["verdict"]["match"] is not None]
    hits = sum(1 for i in scored if i["verdict"]["match"])
    exact = sum(1 for i in scored if i["verdict"].get("exact"))
    return {
        "count": len(items),
        "scored": len(scored),
        "hits": hits,
        "misses": len(scored) - hits,
        # Reported separately on purpose. `hits` counts a read inside the
        # ground truth's acceptable_patterns list, which is deliberately broad;
        # `exact` counts the expected pattern itself. Publishing only `hits`
        # would overstate — the two numbers are far apart on this corpus, and a
        # buyer-facing claim must carry the stricter one.
        "exact": exact,
        "accuracy_note": (
            f"{hits} of {len(scored)} scored entries fell within the accepted pattern "
            f"range; {exact} of {len(scored)} matched the expected pattern exactly. "
            f"{len(items) - len(scored)} entries have no stored read and are not counted."
        ) if scored else "No entries carry a stored read yet.",
        "entries": items,
    }


def _find(entry_id: str) -> Path:
    for d in _entry_dirs():
        meta = _read_json(d / "metadata.json")
        if meta and (meta.get("reference_id") or d.name) == entry_id:
            if meta.get("approval_status") != _APPROVED:
                raise HTTPException(404, "Entry not found.")
            return d
    raise HTTPException(404, "Entry not found.")


@router.get("/{entry_id}/thumbnail")
def gallery_thumbnail(entry_id: str):
    d = _find(entry_id)
    p = d / "thumbnail.jpg"
    if not p.exists():
        raise HTTPException(404, "Thumbnail not found.")
    return FileResponse(str(p), media_type="image/jpeg")


@router.get("/{entry_id}/overlay")
def gallery_overlay(entry_id: str):
    """The debug overlay — what the engine actually saw."""
    d = _find(entry_id)
    p = d / "debug_overlay.png"
    if not p.exists():
        raise HTTPException(404, "Overlay not found.")
    return FileResponse(str(p), media_type="image/png")
