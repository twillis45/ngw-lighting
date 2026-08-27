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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from auth.security import get_optional_user

logger = logging.getLogger(__name__)

def is_internal(user: Optional[Dict[str, Any]]) -> bool:
    """Same internal-account test the analyze route uses for debug output."""
    if not user:
        return False
    from db.provenance import get_internal_emails
    return (user.get("email") or "").strip().lower() in get_internal_emails()


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


def _verdict(meta: Dict[str, Any], signals: Optional[Dict[str, Any]],
             resolved: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compare our stored read against human-verified ground truth.

    Returns the comparison honestly: `match` is None when we have no stored read
    rather than defaulting to a pass. An absent result is not a passing one.
    """
    gt = meta.get("ground_truth") or {}
    expected = gt.get("expected_pattern")
    acceptable = gt.get("acceptable_patterns") or ([expected] if expected else [])

    read_pattern = None
    read_confidence = None
    if resolved:
        # The engine's ANSWER -- classifier, solver and reconciler applied on
        # top of the vision passes. This is what the product claims.
        read_pattern = resolved.get("authoritative_pattern")
        read_confidence = resolved.get("pattern_confidence")
    if read_pattern in (None, "unknown") and signals:
        # Fall back to the single light_structure pass only when there is no
        # stored resolved read. It is ONE of 30 passes, not the answer, so a
        # gallery scored on it understates the engine badly -- it reported
        # 2/29 exact where the engine resolves 17/34.
        ls = signals.get("light_structure") or {}
        read_pattern = read_pattern or ls.get("pattern_name")
        read_confidence = read_confidence if read_confidence is not None else ls.get("confidence")

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
            # source_type deliberately NOT exposed: it reads "found_online"
            # on 32 of 34 entries, which is provenance detail a public
            # viewer has no use for and we should not broadcast.
            "light_count": meta.get("light_count"),
            "key_direction_deg": meta.get("key_direction_deg"),
            "expected_light_count": gt.get("expected_light_count"),
            "thumbnail_url": f"/api/gallery/{meta.get('reference_id') or d.name}/thumbnail",
            "has_overlay": (d / "debug_overlay.png").exists(),
            "verdict": _verdict(meta, signals, _read_json(d / "resolved.json")),
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
def gallery_overlay(entry_id: str, user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """The debug overlay — what the engine actually saw.

    INTERNAL ONLY. This router is mounted public so a visitor can audit the
    accuracy claim without an account, but a debug overlay is the same class
    of material the analyze route already restricts: "complete model dumps --
    curator/dev material, never a customer's." It was reachable
    unauthenticated (200, 457KB PNG) while the identical material was 403 on
    /api/analyze?debug=true. Found by the promote-surface gate, which exists
    because a surface promoted from internal to public carries every
    assumption it made while it was internal.

    The public accuracy screen does not request it -- it reads `has_overlay`
    and nothing else.
    """
    if not is_internal(user):
        raise HTTPException(
            status_code=403,
            detail="Debug overlays are restricted to internal accounts.",
        )
    d = _find(entry_id)
    p = d / "debug_overlay.png"
    if not p.exists():
        raise HTTPException(404, "Overlay not found.")
    return FileResponse(str(p), media_type="image/png")
