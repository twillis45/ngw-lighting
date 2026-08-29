"""Authentication routes: register, login, me, email verification, logout."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("ngw.auth")

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from auth.rate_limit import check_rate_limit
from auth.security import (
    hash_password, verify_password, create_access_token, get_current_user,
    get_optional_user, revoke_token, decode_token_payload,
)

import os
from auth.email import send_verification_email, send_magic_link_email, send_password_reset_email
from db.database import (
    create_user, get_user_by_email, get_or_create_passwordless_user,
    create_verification_token, consume_verification_token,
    mark_email_verified,
    create_magic_link_token, consume_magic_link_token,
    create_password_reset_token, consume_password_reset_token, update_user_password,
    delete_user_account,
    get_active_subscription, get_subscription_by_stripe_session,
    log_admin_change,
)

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


class RegisterBody(BaseModel):
    email: str = Field(..., min_length=3)
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)


class LoginBody(BaseModel):
    email: str
    password: str


class VerifyBody(BaseModel):
    token: str


class TokenResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    email_verified: bool = False


def _user_public(user: dict) -> dict:
    from db.provenance import get_internal_emails
    email = user.get("email", "")
    return {
        "id": user.get("id", ""),
        "email": email,
        "username": user.get("username", "") or user.get("name", "") or email,
        "email_verified": bool(user.get("email_verified", 0)),
        "is_admin": email.lower() in get_internal_emails(),
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterBody, request: Request):
    # 10 registrations per IP per hour — prevents mass account creation
    check_rate_limit("register", request, limit=10, window=3600)
    existing = get_user_by_email(body.email)
    if existing:
        logger.info("[register] rejected — email already registered: %s", body.email)
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = hash_password(body.password)
    user = create_user(body.email, body.username, hashed)
    token = create_access_token(user["id"])
    logger.info("[register] new user id=%s email=%s", user["id"], body.email)

    # Send verification email (non-blocking — failure doesn't break registration)
    try:
        verif_token = create_verification_token(user["id"])
        send_verification_email(body.email, verif_token)
    except Exception as exc:
        logger.error("[register] verification email failed for %s: %s", body.email, exc)

    return {"token": token, "user": _user_public(user)}


@router.post("/login", response_model=TokenResponse)
def login(body: LoginBody, request: Request):
    # 5 attempts per IP per 60 s + 10 per-account per 15 min — brute-force protection
    check_rate_limit("login_ip",      request, limit=5,  window=60)
    check_rate_limit("login_account", request, limit=10, window=900, extra=body.email.lower())
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["hashed_pw"]):
        logger.warning("[login] failed for %s", body.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"])
    logger.info("[login] success user_id=%s email=%s", user["id"], body.email)
    try:
        log_admin_change("auth", user["id"], "login", {"email": body.email})
    except Exception:
        pass
    return {"token": token, "user": _user_public(user)}


@router.get("/me", response_model=UserResponse)
def me(user=Depends(get_current_user)):
    return _user_public(user)


@router.post("/verify-email")
def verify_email(body: VerifyBody, request: Request):
    # 10 verification attempts per IP per hour — prevents token brute-force
    check_rate_limit("verify_email", request, limit=10, window=3600)
    user = consume_verification_token(body.token)
    if not user:
        logger.warning("[verify-email] invalid/expired token")
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    logger.info("[verify-email] verified user_id=%s", user["id"])
    token = create_access_token(user["id"])
    return {"token": token, "user": _user_public(user)}


@router.get("/subscription-status")
def subscription_status(
    stripe_session: str | None = None,
    email: str | None = None,
    user=Depends(get_optional_user),
):
    """
    Validate whether a user has an active paid subscription.

    Checks in priority order:
      1. stripe_session param — direct checkout session lookup (post-payment redirect)
      2. authenticated user's email — most recent active subscription

    Security: the `email` query-param is accepted ONLY when a valid JWT is present
    and the requested email matches the authenticated user's email.  Unauthenticated
    callers or callers requesting a different user's status always get is_paid=false.
    This prevents unauthenticated enumeration of paid subscribers.

    Returns:
      { "is_paid": bool, "plan": str | None, "billing_period": str | None,
        "stripe_session_id": str | None }
    """
    _not_paid = {
        "is_paid": False, "plan": None, "billing_period": None,
        "stripe_session_id": None, "stripe_customer_id": None,
        "stripe_subscription_id": None, "status": "none",
    }

    def _paid_response(sub: dict) -> dict:
        return {
            "is_paid":               True,
            "plan":                  sub.get("plan"),
            "billing_period":        sub.get("billing_period"),
            "stripe_session_id":     sub.get("stripe_session_id"),
            "stripe_customer_id":    sub.get("stripe_customer_id"),
            "stripe_subscription_id": sub.get("stripe_subscription_id"),
            "status":                sub.get("status", "active"),
        }

    # 1. Direct session lookup (most trusted — Stripe session IDs are unguessable)
    if stripe_session:
        sub = get_subscription_by_stripe_session(stripe_session)
        if sub and sub.get("status") == "active":
            return _paid_response(sub)

    # 2. Email lookup — requires authentication.
    # Determine the email to look up: authenticated user's own email only.
    # If an email param is provided, it must match the JWT user's email exactly.
    jwt_email = user.get("email") if user else None

    if email:
        # Caller passed an explicit email — only allow if it matches their own JWT.
        if not jwt_email or jwt_email.lower() != email.strip().lower():
            return _not_paid
        lookup_email = jwt_email
    else:
        lookup_email = jwt_email

    if lookup_email:
        sub = get_active_subscription(lookup_email)
        if sub:
            return _paid_response(sub)

    return _not_paid


@router.post("/logout", status_code=200)
def logout(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    """Revoke the current JWT by adding its JTI to the in-process blocklist.

    The token is invalid for the remainder of its lifetime (up to 7 days).
    On server restart the blocklist clears; for durable revocation, swap the
    in-memory store in auth/security.py for a Redis SETEX store.
    """
    if creds:
        payload = decode_token_payload(creds.credentials)
        if payload:
            jti = payload.get("jti")
            if jti:
                revoke_token(jti)
                logger.info("[logout] revoked jti=%s", jti)
    return {"detail": "Logged out"}


# ── Magic Link ─────────────────────────────────────────────

class MagicLinkRequestBody(BaseModel):
    email: str = Field(..., min_length=3)

class MagicLinkVerifyBody(BaseModel):
    token: str

@router.post("/magic-link/request")
def request_magic_link(body: MagicLinkRequestBody, request: Request):
    check_rate_limit("magic_link", request, limit=5, window=900, extra=body.email.lower())
    token = create_magic_link_token(body.email.lower())
    logger.info("[magic-link] request for %s", body.email.lower())
    try:
        send_magic_link_email(body.email.lower(), token)
        logger.info("[magic-link] email sent to %s", body.email.lower())
    except Exception as exc:
        logger.error("[magic-link] email send FAILED for %s: %s", body.email.lower(), exc)
    return {"detail": "Magic link sent. Check your email."}

@router.post("/magic-link/verify")
def verify_magic_link(body: MagicLinkVerifyBody, request: Request):
    email = consume_magic_link_token(body.token)
    if not email:
        logger.warning("[magic-link] verify failed — invalid/expired token")
        raise HTTPException(status_code=401, detail="Invalid or expired magic link.")
    user = get_or_create_passwordless_user(email)
    token = create_access_token(user["id"])
    logger.info("[magic-link] verified user_id=%s email=%s", user["id"], email)
    return {"token": token, "user": _user_public(user)}


# ── Google OAuth ────────────────────────────────────────────

class GoogleAuthBody(BaseModel):
    credential: str  # Google ID token

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

@router.get("/providers")
def auth_providers() -> dict:
    """Which third-party sign-in routes are actually usable right now.

    The login screen renders a provider button ONLY when this says the
    provider is configured. That is the point: on 2026-08-28 the stage-4
    heuristics gate found "Continue with Google" and "Continue with Apple"
    rendering as real buttons with nothing behind them, each firing a
    POSITIVE haptic and returning. A button whose existence is conditioned
    on server state cannot drift back into lying — if the credential is
    absent the control is absent, and nobody has to remember to check.

    Deliberately unauthenticated: the signed-out login screen is the only
    consumer, so it cannot require a token. The client ID it returns is a
    PUBLIC value by design — every site using Google Sign-In ships it in
    page source; the secret half of the pair is the client SECRET, which
    lives only in the server env and is never returned here.

    apple is hard-false: Sign in with Apple has no route, no config and no
    code. Recorded as a deferral due at iOS launch, since Apple requires it
    of App Store apps that offer any third-party sign-in.
    """
    return {
        "google": bool(GOOGLE_CLIENT_ID),
        "google_client_id": GOOGLE_CLIENT_ID or None,
        "apple": False,
    }


@router.post("/google")
def google_auth(body: GoogleAuthBody, request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google auth is not configured.")
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        idinfo = google_id_token.verify_oauth2_token(
            body.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        logger.warning("[google] credential verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Google credential.")

    email = idinfo.get("email", "")
    name  = idinfo.get("name") or email.split("@")[0]
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email.")

    check_rate_limit("google_auth", request, limit=20, window=900, extra=email.lower())
    user  = get_or_create_passwordless_user(email, username=name)
    token = create_access_token(user["id"])
    logger.info("[google] auth success user_id=%s email=%s", user["id"], email)
    return {"token": token, "user": _user_public(user)}


# ── Password Reset ──────────────────────────────────────────

class PasswordResetRequestBody(BaseModel):
    email: str = Field(..., min_length=3)

class PasswordResetConfirmBody(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=128)

@router.post("/password-reset/request")
def request_password_reset(body: PasswordResetRequestBody, request: Request):
    """Send a password-reset link. Always returns success to avoid email enumeration.

    Admin/internal emails bypass the passwordless guard — they can always set a
    password regardless of how the account was originally created.
    """
    check_rate_limit("password_reset", request, limit=3, window=900, extra=body.email.lower())
    from db.provenance import get_internal_emails
    email_lower = body.email.lower()
    user = get_user_by_email(email_lower)
    is_admin = email_lower in get_internal_emails()
    logger.info("[password-reset] request for %s | user_found=%s is_admin=%s",
                email_lower, user is not None, is_admin)
    # Send reset for password-based accounts AND for admin emails (even if passwordless)
    if user and (user.get("hashed_pw") != "__passwordless__" or is_admin):
        token = create_password_reset_token(email_lower)
        try:
            send_password_reset_email(email_lower, token)
            logger.info("[password-reset] email sent to %s", email_lower)
        except Exception as exc:
            logger.error("[password-reset] email send FAILED for %s: %s", email_lower, exc)
    else:
        logger.info("[password-reset] skipped — %s",
                     "no user" if not user else "passwordless account (non-admin)")
    return {"detail": "If that email has an account, a reset link was sent."}

@router.post("/password-reset/confirm")
def confirm_password_reset(body: PasswordResetConfirmBody, request: Request):
    """Validate reset token, update password, return new JWT."""
    email = consume_password_reset_token(body.token)
    if not email:
        logger.warning("[password-reset] confirm failed — invalid/expired token")
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    user = get_user_by_email(email)
    if not user:
        logger.warning("[password-reset] confirm failed — account not found for %s", email)
        raise HTTPException(status_code=400, detail="Account not found.")
    hashed = hash_password(body.new_password)
    update_user_password(user["id"], hashed)
    token = create_access_token(user["id"])
    logger.info("[password-reset] password updated for %s", email)
    return {"token": token, "user": _user_public(user)}


@router.delete("/me", status_code=200)
def delete_account(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    user=Depends(get_current_user),
):
    """Permanently delete the authenticated user's account and all their data."""
    # Revoke the JWT immediately so it can't be reused after deletion
    if creds:
        payload = decode_token_payload(creds.credentials)
        if payload:
            jti = payload.get("jti")
            if jti:
                revoke_token(jti)
    delete_user_account(user["id"], user["email"])
    logger.info("[delete-account] user_id=%s email=%s", user["id"], user["email"])
    return {"detail": "Account deleted"}


@router.post("/resend-verification")
def resend_verification(user=Depends(get_current_user)):
    if user.get("email_verified"):
        raise HTTPException(status_code=400, detail="Email already verified")
    try:
        verif_token = create_verification_token(user["id"])
        send_verification_email(user["email"], verif_token)
        logger.info("[resend-verification] sent to user_id=%s email=%s", user["id"], user["email"])
    except Exception as exc:
        logger.error("[resend-verification] failed for %s: %s", user["email"], exc)
        raise HTTPException(status_code=500, detail="Failed to send email") from exc
    return {"detail": "Verification email sent"}
