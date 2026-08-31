"""
GET  /api/flags                     — evaluated flags for this session
POST /api/flags/{name}/rollout      — update rollout % (admin only)
GET  /api/flags/all                 — full flag definitions (admin only)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.security import get_current_user, get_optional_user
from db.experiments import assign_flag, init_experiments_tables

logger = logging.getLogger(__name__)
router = APIRouter(tags=["flags"])

FLAGS_PATH = Path("data/flags.json")
from config.admin import is_admin

_flags_cache: Optional[Dict[str, Any]] = None


def load_flags() -> Dict[str, Any]:
    global _flags_cache
    if _flags_cache is None:
        try:
            _flags_cache = json.loads(FLAGS_PATH.read_text())
        except Exception:
            logger.exception("Failed to load flags.json")
            _flags_cache = {}
    return _flags_cache


def get_flags_for_session(session_id: str) -> Dict[str, Any]:
    """Evaluated flag state for one session.

    Extracted 2026-08-30. This logic existed only INSIDE the get_flags route
    handler, while api/routes/paywall.py (three call sites) and
    api/routes/recommend.py imported `get_flags_for_session` from `db.flags`
    — a module that does not exist and never has.

    Every one of those imports sits inside `try: ... except Exception: flags = {}`,
    so the ImportError was swallowed and each call silently returned no flags.
    The consequence is not a crash: it is that NO experiment event was ever
    recorded for any pricing, paywall_timing, cta_messaging or paywall_value
    flag. The experiments ran and produced zero data, and nothing said so.

    Returns {flag_name: {enabled, variant, group, config}} — the exact shape
    those callers already expect, which is why the fix is an extraction rather
    than a rewrite.
    """
    out: Dict[str, Any] = {}
    for flag_name, flag_def in load_flags().items():
        variant = assign_flag(session_id, flag_name, flag_def)
        out[flag_name] = {
            "enabled": flag_def.get("enabled", False),
            "variant": variant,
            "group": flag_def.get("group", ""),
            "config": flag_def.get("config", {}) if variant == "treatment" else {},
        }
    return out


def reload_flags() -> Dict[str, Any]:
    global _flags_cache
    _flags_cache = None
    return load_flags()


@router.get("/flags")
async def get_flags(
    session_id: Optional[str] = Query(None),
    user=Depends(get_optional_user),
):
    """
    Return evaluated flag state for this session.
    Each flag: { enabled, variant, group, config (treatment only) }.
    """
    effective_session = session_id or (user["id"] if user else "anonymous")
    return {"session_id": effective_session,
            "flags": get_flags_for_session(effective_session)}


@router.get("/flags/all")
async def get_all_flags(user=Depends(get_current_user)):
    """Return full flag definitions including rollout %. Admin only."""
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    return load_flags()


class RolloutUpdate(BaseModel):
    rollout_pct: int
    enabled: Optional[bool] = None


@router.post("/flags/{flag_name}/rollout")
async def update_flag_rollout(
    flag_name: str,
    body: RolloutUpdate,
    user=Depends(get_current_user),
):
    """Update a flag's rollout % and enabled state. Admin only."""
    if not is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="Admin only")
    if not 0 <= body.rollout_pct <= 100:
        raise HTTPException(status_code=400, detail="rollout_pct must be 0–100")

    flags = reload_flags()
    if flag_name not in flags:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")

    flags[flag_name]["rollout_pct"] = body.rollout_pct
    if body.enabled is not None:
        flags[flag_name]["enabled"] = body.enabled

    FLAGS_PATH.write_text(json.dumps(flags, indent=2))
    reload_flags()

    logger.info(
        "Flag %s updated: rollout=%d enabled=%s by %s",
        flag_name, body.rollout_pct, body.enabled, user.get("email"),
    )
    return {
        "flag_name": flag_name,
        "rollout_pct": body.rollout_pct,
        "enabled": flags[flag_name]["enabled"],
    }
