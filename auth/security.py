"""JWT token creation / verification and password hashing."""
from __future__ import annotations

import logging
import os
import time
import uuid
from threading import Lock
from typing import Optional

logger = logging.getLogger("ngw.auth.security")

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from db.database import get_user_by_id

# ── Configuration ──────────────────────────────────────────

_NGW_JWT_SECRET = os.getenv("NGW_JWT_SECRET")
_INSECURE_DEFAULT = "ngw-dev-secret-change-in-production"
if not _NGW_JWT_SECRET or _NGW_JWT_SECRET.strip() == _INSECURE_DEFAULT:
    raise RuntimeError(
        "NGW_JWT_SECRET is not set or is using the insecure dev default. "
        "Generate a safe value: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
SECRET_KEY = _NGW_JWT_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


# ── Password ───────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password, failing CLOSED on an unreadable stored hash.

    passlib raises rather than returning False when the stored value is not a
    recognisable hash — UnknownHashError for an empty or malformed string,
    ValueError for a corrupted bcrypt cost field. That propagated out of the
    login handler as a 500, which is both an availability bug on the auth
    boundary and a distinguishable response: a row with a damaged hash answers
    differently from a row with a good one, which is exactly the shape of an
    account-enumeration oracle.

    Found 2026-09-03 by tests/test_auth_boundary.py, written as the gate for a
    library swap and finding this before the swap happened.
    """
    if not plain or not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        # Deliberately broad: the failure modes are library-specific and this
        # boundary must never answer anything but False for a bad hash.
        logger.warning("[auth] unreadable password hash — failing closed")
        return False


# ── JWT revocation (in-memory JTI blocklist) ────────────────
# Survives within a process lifetime. On restart the blocklist clears, but
# tokens also expire after ACCESS_TOKEN_EXPIRE_SECONDS (7 days) so the window
# of exposure is bounded. For persistent revocation, swap this set for a
# Redis SETEX store keyed by jti with TTL = token expiry.

_revoked_jtis: set[str] = set()
_revoked_lock = Lock()


def revoke_token(jti: str) -> None:
    """Add a token's JTI to the in-process revocation list."""
    with _revoked_lock:
        _revoked_jtis.add(jti)


def is_revoked(jti: str) -> bool:
    with _revoked_lock:
        return jti in _revoked_jtis


# ── JWT ────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "iat": int(time.time()),
        "exp": int(time.time()) + ACCESS_TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Return user_id or None. Also checks JTI revocation."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti and is_revoked(jti):
            logger.warning("[jwt] revoked token used jti=%s", jti)
            return None
        return payload.get("sub")
    except JWTError as exc:
        # "Not enough segments" means the value isn't a JWT at all (stale
        # localStorage token, magic-link code, etc.) — not a security event.
        msg = str(exc)
        if "not enough segments" in msg.lower() or "not a valid jwt" in msg.lower():
            logger.debug("[jwt] decode skipped — not a JWT: %s", msg)
        else:
            logger.warning("[jwt] decode failed: %s", exc)
        return None


def decode_token_payload(token: str) -> Optional[dict]:
    """Return full payload dict or None (no revocation check — use for logout)."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── Dev mode ───────────────────────────────────────────────

_DEV_MODE_USER = {"id": "dev-mode", "email": "dev@localhost", "name": "Dev Mode", "username": "Dev Mode"}


def _dev_mode_active() -> bool:
    """Return True when NGW_DEV_MODE is set to a truthy value."""
    return os.getenv("NGW_DEV_MODE", "").strip().lower() in ("1", "true", "yes")


# ── Dependency ─────────────────────────────────────────────

async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)):
    """FastAPI dependency — returns user dict or raises 401.

    When NGW_DEV_MODE=1, bypasses all token checks and returns a mock dev user.
    Never enable NGW_DEV_MODE in production.
    """
    if _dev_mode_active():
        return _DEV_MODE_USER
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = decode_token(creds.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)):
    """FastAPI dependency — returns user dict or None (no error)."""
    if _dev_mode_active():
        return _DEV_MODE_USER
    if not creds:
        return None
    user_id = decode_token(creds.credentials)
    if not user_id:
        return None
    return get_user_by_id(user_id)
