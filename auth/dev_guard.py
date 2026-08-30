"""Dev guard — email whitelist for NGW Lab access.

Reads allowed emails from NGW_DEV_EMAILS env var (comma-separated).
Wraps get_current_user() with an additional 403 check.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status

from auth.security import get_current_user, get_optional_user


def _get_dev_emails() -> set:
    """Parse NGW_DEV_EMAILS env var into a set of lowercase emails."""
    raw = os.getenv("NGW_DEV_EMAILS", "")
    if not raw.strip():
        return set()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _dev_mode_active() -> bool:
    """Check if NGW_DEV_MODE env var is set to a truthy value."""
    return os.getenv("NGW_DEV_MODE", "").strip().lower() in ("1", "true", "yes")


_DEV_MODE_USER = {"id": "dev-mode", "email": "dev@localhost", "name": "Dev Mode", "username": "Dev Mode"}


def assert_lab_access(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Authorize a user for Lab access, or raise. FAILS CLOSED.

    Extracted 2026-08-30. The lab image route hand-rolled this check because it
    also accepts a token as a QUERY PARAM (an <img src> cannot send an
    Authorization header), and its copy carried a comment saying "same as
    get_dev_user" while being the opposite:

        if allowed and (user.get("email", "").lower() not in allowed):

    With NGW_DEV_EMAILS unset, `allowed` is empty, the condition is False, and
    nothing raises — so any registered free account could download Lab analysis
    images while every sibling Lab route returned 403 on the same token.
    Verified before the fix: GET /api/lab/gold-set gave 403, and
    GET /api/lab/analysis/<id>/image gave 200 with a real JPEG.

    Both call sites now share this function, because two copies of an
    authorization rule is how one of them silently becomes the wrong one.
    """
    if _dev_mode_active():
        return _DEV_MODE_USER
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    allowed = _get_dev_emails()
    # No whitelist configured means nobody is authorized. An unconfigured
    # allowlist is an absence of permission, never a grant of it.
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lab access not configured. Set NGW_DEV_EMAILS env var.",
        )
    if (user.get("email") or "").lower() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account does not have Lab access.",
        )
    return user


async def get_dev_user(user: Dict[str, Any] = Depends(get_optional_user)) -> Dict[str, Any]:
    """FastAPI dependency — returns user dict or raises 403 if not a whitelisted dev.

    Requires:
      1. Valid JWT (via get_current_user → 401 if missing/invalid)
      2. User email in NGW_DEV_EMAILS list → 403 if not whitelisted

    If NGW_DEV_MODE=1, bypasses both checks and returns a mock dev user.
    """
    return assert_lab_access(user)
