"""
/api/waitlist  — Early access waitlist capture.

POST  /api/waitlist   { email, first_name?, shoot_type? }
GET   /api/waitlist   (admin only) — list all entries

Stores submissions in data/waitlist.json (append-only, never deletes).
Sends a confirmation email via SMTP/Resend on successful sign-up.
Duplicate emails are silently accepted (200 + already_registered flag)
so the UX is unchanged from the user's perspective.
"""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

# ── Storage ──────────────────────────────────────────────────────────────────
# Writable state belongs on the persistent disk, not in image storage.
# Was Path("data/waitlist.json") — relative, so it resolved to /app/data in
# the container, which is image content rebuilt on every deploy. Every signup
# was therefore destroyed by the next deploy, independently of the corruption
# bug fixed earlier today. DATA_DIR follows NGW_DATA_DIR to the mounted disk.
from db.database import DATA_DIR as _DATA_DIR
WAITLIST_PATH = _DATA_DIR / "waitlist.json"

VALID_SHOOT_TYPES = {
    "portraits_headshots",
    "studio",
    "events",
    "content_social",
    "product",
    "mixed",
    "",          # empty = not answered
}


class WaitlistUnreadable(RuntimeError):
    """The waitlist file exists but cannot be read as a list of entries."""


def _load() -> list[dict]:
    """Load all waitlist entries from disk.

    Raises WaitlistUnreadable when the file is PRESENT but unusable. That
    distinction is the whole point of this function.

    Until 2026-08-30 this swallowed every exception and returned [], so an
    unreadable file read as "nobody has signed up" and the very next _save
    wrote only the new entry — silently destroying every prior signup and
    returning HTTP 200. Reproduced three ways: a truncated file, a file with
    permissions removed, and a zero-byte file left by a crash between rename
    and fsync. On Render this lives on a mounted persistent disk, so the loss
    is everything ever collected, not merely since the last deploy.

    An empty file is a real state and stays empty. A missing file is a real
    state and stays []. Anything else is a fault, and a fault must not be
    indistinguishable from "no data".
    """
    if not WAITLIST_PATH.exists():
        return []
    try:
        raw = WAITLIST_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise WaitlistUnreadable(f"cannot read waitlist file: {exc}") from exc
    if not raw.strip():
        # A zero-byte file is ambiguous: it is what a crash between rename and
        # fsync leaves behind, and also what an empty list would never produce
        # (json.dumps([]) is "[]"). Treat it as a fault, not as empty.
        raise WaitlistUnreadable("waitlist file is empty — treating as corrupt, not as zero signups")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise WaitlistUnreadable(f"waitlist file is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise WaitlistUnreadable(f"waitlist file holds {type(data).__name__}, expected list")
    return data


def _save(entries: list[dict]) -> None:
    """Persist waitlist entries to disk (atomic write)."""
    WAITLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAITLIST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    tmp.replace(WAITLIST_PATH)


def _email_exists(entries: list[dict], email: str) -> bool:
    email_lower = email.lower()
    return any(e.get("email", "").lower() == email_lower for e in entries)


# ── Email ─────────────────────────────────────────────────────────────────────
def _send_confirmation(email: str, first_name: str) -> None:
    """Send a confirmation email via SMTP (Resend)."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.resend.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "resend")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("FROM_EMAIL", "noreply@noguessworksystems.com")
    app_url    = os.getenv("APP_URL", "https://noguessworksystems.com")

    if not smtp_pass:
        logger.warning("waitlist: SMTP_PASS not set — skipping confirmation email")
        return

    greeting = f"Hi {first_name}," if first_name else "Hey,"

    subject = "You're on the No Guesswork Lighting waitlist 📸"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/></head>
<body style="margin:0;padding:0;background:#0E0F12;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0E0F12;padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#17191F;border:1px solid #2A2E38;border-radius:12px;padding:40px;">
        <tr><td>
          <!-- Logo -->
          <div style="margin-bottom:28px;">
            <span style="font-size:1.25rem;font-weight:700;color:#F4F6F8;">No Guesswork Lighting</span>
          </div>

          <!-- Greeting -->
          <p style="color:#F4F6F8;font-size:1rem;line-height:1.6;margin:0 0 16px;">
            {greeting}
          </p>
          <p style="color:#F4F6F8;font-size:1rem;line-height:1.6;margin:0 0 24px;">
            You're on the list. We'll reach out as soon as your early access spot is ready.
          </p>

          <!-- What to expect -->
          <div style="background:#1E2129;border-radius:8px;padding:20px;margin-bottom:24px;">
            <p style="color:#A9AFBB;font-size:0.875rem;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;margin:0 0 12px;">
              What happens next
            </p>
            <ul style="color:#F4F6F8;font-size:0.9375rem;line-height:1.7;margin:0;padding-left:20px;">
              <li>We're onboarding photographers in small batches</li>
              <li>First 500 get <strong>3 months free</strong> + locked-in pricing</li>
              <li>You'll get a personal invite link when your spot opens</li>
            </ul>
          </div>

          <!-- CTA -->
          <p style="margin:0 0 28px;">
            <a href="{app_url}/early-access"
               style="display:inline-block;background:#4DA3FF;color:#fff;font-weight:700;font-size:0.9375rem;padding:12px 24px;border-radius:8px;text-decoration:none;">
              View your spot →
            </a>
          </p>

          <p style="color:#A9AFBB;font-size:0.8125rem;line-height:1.6;margin:0;">
            Questions? Reply to this email — it goes straight to the builder.<br/>
            <a href="{app_url}/early-access" style="color:#4DA3FF;">noguessworksystems.com</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_body = f"""{greeting}

You're on the No Guesswork Lighting waitlist.

We're onboarding photographers in small batches. First 500 get 3 months free + locked-in pricing.
You'll get a personal invite link when your spot opens.

Questions? Reply to this email — it goes straight to the builder.

{app_url}/early-access
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"No Guesswork <{from_email}>"
    msg["To"]      = email

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [email], msg.as_string())
        logger.info("waitlist: confirmation sent to %s", email)
    except Exception as exc:
        logger.error("waitlist: email send failed for %s — %s", email, exc)


# ── Schemas ───────────────────────────────────────────────────────────────────
class WaitlistRequest(BaseModel):
    email:       str
    first_name:  Optional[str] = ""
    shoot_type:  Optional[str] = ""

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("first_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return (v or "").strip()[:80]

    @field_validator("shoot_type")
    @classmethod
    def validate_shoot_type(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in VALID_SHOOT_TYPES:
            return ""
        return v


# ── Routes ────────────────────────────────────────────────────────────────────
@router.post("")
async def join_waitlist(payload: WaitlistRequest):
    """
    Join the early access waitlist.
    Idempotent — duplicate emails return 200 without re-sending the email.
    """
    try:
        entries = _load()
    except WaitlistUnreadable as exc:
        # Refuse rather than overwrite. Losing one signup to a 503 the caller
        # can retry is recoverable; silently replacing the whole list is not.
        logger.error("waitlist: REFUSING to write — %s", exc)
        raise HTTPException(
            status_code=503,
            detail="The waitlist is temporarily unavailable. Please try again shortly.",
        )

    if _email_exists(entries, payload.email):
        return {"status": "ok", "already_registered": True}

    entry = {
        "email":      payload.email,
        "first_name": payload.first_name,
        "shoot_type": payload.shoot_type,
        "joined_at":  datetime.now(timezone.utc).isoformat(),
    }
    entries.append(entry)
    _save(entries)

    # Fire-and-forget confirmation email (best effort — never blocks the response)
    try:
        _send_confirmation(payload.email, payload.first_name)
    except Exception as exc:
        logger.error("waitlist: unexpected email error — %s", exc)

    logger.info(
        "waitlist: new signup — %s (%s) shoot=%s total=%d",
        payload.email, payload.first_name or "anon", payload.shoot_type or "-", len(entries)
    )

    return {"status": "ok", "already_registered": False}


def _get_admin_secret() -> str:
    """Return the admin secret for waitlist endpoints.

    Prefer the dedicated NGW_ADMIN_SECRET env var (set this in production).
    Falls back to NGW_JWT_SECRET only when the dedicated var is absent, so
    existing deployments keep working without an immediate config change.
    Separating the two secrets means a compromised JWT key doesn't also
    expose admin endpoints, and vice-versa.
    """
    return os.getenv("NGW_ADMIN_SECRET") or os.getenv("NGW_JWT_SECRET", "")


@router.get("")
async def list_waitlist(request: Request):
    """
    Admin endpoint — returns all waitlist entries as JSON.
    Requires ?secret=<NGW_ADMIN_SECRET> or the X-Admin-Token header.
    Set NGW_ADMIN_SECRET in the environment; falls back to NGW_JWT_SECRET.
    """
    admin_secret = _get_admin_secret()
    provided     = (
        request.query_params.get("secret", "")
        or request.headers.get("X-Admin-Token", "")
    )
    if not admin_secret or provided != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        entries = _load()
    except WaitlistUnreadable as exc:
        # An admin reading "0 entries" off a corrupt file is the worst possible
        # answer here: it looks like nobody signed up rather than like a fault.
        logger.error("waitlist: admin list failed — %s", exc)
        raise HTTPException(status_code=503, detail=f"Waitlist file unreadable: {exc}")
    return {"count": len(entries), "entries": entries}


@router.post("/run-sequence")
async def run_sequence(request: Request):
    """
    Admin endpoint — manually trigger the follow-up email sequence check.
    Requires ?secret=<NGW_ADMIN_SECRET> or the X-Admin-Token header.
    Useful for testing and forcing a check without waiting for the 4-hour loop.
    """
    admin_secret = _get_admin_secret()
    provided     = (
        request.query_params.get("secret", "")
        or request.headers.get("X-Admin-Token", "")
    )
    if not admin_secret or provided != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        from engine.email_sequence import check_and_send_follow_ups
        result = check_and_send_follow_ups()
        return {"status": "ok", **result}
    except Exception as exc:
        logger.error("waitlist run-sequence error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
