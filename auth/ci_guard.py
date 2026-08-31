"""
CI authentication guard.

CI benchmark endpoints accept either:
  1. Standard dev JWT (Authorization: Bearer <token>) — same as all Lab endpoints
  2. X-CI-Secret header matching CI_BENCHMARK_SECRET env var — for headless CI runners

This lets GitHub Actions call the endpoint without a user JWT,
while still being protected from public access.
"""
from __future__ import annotations

import os
import secrets
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from auth.dev_guard import get_dev_user
from auth.security import get_optional_user

_CI_SECRET_ENV = "CI_BENCHMARK_SECRET"
_CI_USER       = {"id": "ci-runner", "email": "ci@benchmark", "type": "ci"}


def _get_ci_secret() -> Optional[str]:
    s = os.environ.get(_CI_SECRET_ENV, "").strip()
    return s or None


async def get_ci_or_dev_user(
    x_ci_secret: Optional[str] = Header(None, alias="X-CI-Secret"),
    optional_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    """
    FastAPI dependency — accepts CI secret header OR a valid dev JWT.

    Order of precedence:
      1. X-CI-Secret header → validated against CI_BENCHMARK_SECRET env var
      2. Bearer JWT → validated via get_dev_user (email whitelist)
      3. NGW_DEV_MODE=1 → dev bypass
    """
    # Path 1: CI secret header
    if x_ci_secret is not None:
        expected = _get_ci_secret()
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"CI secret not configured on server. "
                    f"Set the {_CI_SECRET_ENV} environment variable."
                ),
            )
        # Constant-time. A plain != leaks the length of the shared prefix
        # through timing, and this endpoint can be called without an account.
        if not secrets.compare_digest(x_ci_secret, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid CI secret.",
            )
        return _CI_USER

    # Path 2: Normal dev JWT (re-use existing guard)
    if optional_user:
        # Run through dev guard — will raise 401/403 if not authorised
        return await get_dev_user(optional_user)  # type: ignore[arg-type]

    # Path 3: Dev mode bypass
    from auth.dev_guard import _dev_mode_active, _DEV_MODE_USER
    if _dev_mode_active():
        return _DEV_MODE_USER

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (Bearer token or X-CI-Secret header).",
    )
