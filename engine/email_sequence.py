"""
Waitlist Follow-Up Email Sequence
==================================
Sends 4 timed follow-up emails after the day-0 confirmation (which fires
immediately in waitlist.py / _send_confirmation).

Schedule (days since joined_at):
  Day  2 — Feature spotlight: how the VLM pipeline actually works
  Day  5 — Social proof: pattern detection demo
  Day 10 — Urgency: spots are filling up
  Day 14 — Last call: final nudge before spot closes

State is tracked inside each entry in data/waitlist.json under the key
`follow_ups_sent` (list of email IDs already delivered, e.g. ["day2", "day5"]).

Entry example after day-2 email is sent:
  { "email": "...", "joined_at": "...", "follow_ups_sent": ["day2"] }

Background loop
---------------
Called by main.py lifespan. Runs every SEQUENCE_CHECK_INTERVAL_HOURS hours
(default 4) when WAITLIST_SEQUENCE_ENABLED=1.

Manual trigger
--------------
  POST /api/waitlist/run-sequence   (admin — same secret as GET /api/waitlist)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Was Path("data/waitlist.json") — relative, so it resolved against WORKDIR
# into /app/data, which is IMAGE storage rebuilt on every deploy. This file
# holds the sequence's own sent-state, so every deploy reset that state to the
# git-tracked copy and the whole sequence re-sent from day 2.
#
# Measured from production logs 2026-08-31: a single startup sent EIGHT emails
# — day2/day5/day10/day14 to each of two entries — and that repeated on every
# deploy. The two recipients are smoketest@test.com and
# wltest+1776725917@ngw.test: undeliverable domains, so each send is a hard
# bounce against a Resend sender with no reputation to spend.
#
# This is the second copy of the same bug; api/routes/waitlist.py had the
# identical line and was fixed earlier today. One was fixed, the other was not
# looked for.
from db.database import DATA_DIR as _DATA_DIR
WAITLIST_PATH = _DATA_DIR / "waitlist.json"
SEQUENCE_CHECK_INTERVAL_HOURS = int(os.getenv("SEQUENCE_CHECK_INTERVAL_HOURS", "4"))

# ── Sequence definition ───────────────────────────────────────────────────────

SEQUENCE: List[Dict[str, Any]] = [
    {
        "id": "day2",
        "day": 2,
        "subject": "How we read lighting from a single photo",
        "preview": "The 7-stage pipeline behind your analysis results.",
    },
    {
        "id": "day5",
        "day": 5,
        "subject": "Can you identify this lighting setup? (We can — in seconds)",
        "preview": "Rembrandt, loop, butterfly, split — and 24 more patterns.",
    },
    {
        "id": "day10",
        "day": 10,
        "subject": "47 photographers joined the waitlist this week",
        "preview": "Your early access spot is still open — but it won't be forever.",
    },
    {
        "id": "day14",
        "day": 14,
        "subject": "Last chance: 3 months free closes soon",
        "preview": "Your spot is reserved. Here's how to claim it.",
    },
]


# ── Email templates ───────────────────────────────────────────────────────────

def _base_html(preview: str, body_html: str, app_url: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>No Guesswork Lighting</title>
</head>
<body style="margin:0;padding:0;background:#0E0F12;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <!-- preview text (hidden) -->
  <div style="display:none;max-height:0;overflow:hidden;color:#0E0F12;font-size:1px;">{preview}&nbsp;‌&nbsp;‌&nbsp;‌&nbsp;‌&nbsp;‌&nbsp;‌&nbsp;‌&nbsp;‌&nbsp;</div>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0E0F12;padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#17191F;border:1px solid #2A2E38;border-radius:12px;padding:40px;">
        <tr><td>
          <div style="margin-bottom:28px;">
            <span style="font-size:1.25rem;font-weight:700;color:#F4F6F8;">No Guesswork Lighting</span>
          </div>
          {body_html}
          <hr style="border:none;border-top:1px solid #2A2E38;margin:28px 0;"/>
          <p style="color:#A9AFBB;font-size:0.8125rem;line-height:1.6;margin:0;">
            You're receiving this because you joined the No Guesswork waitlist.<br/>
            <a href="{app_url}/early-access" style="color:#4DA3FF;">noguessworksystems.com</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _cta_button(url: str, label: str) -> str:
    return (
        f'<p style="margin:0 0 28px;">'
        f'<a href="{url}" style="display:inline-block;background:#4DA3FF;color:#fff;'
        f'font-weight:700;font-size:0.9375rem;padding:12px 24px;border-radius:8px;text-decoration:none;">'
        f'{label}</a></p>'
    )


def _body_text(color: str = "#F4F6F8") -> str:
    return f'style="color:{color};font-size:1rem;line-height:1.7;margin:0 0 16px;"'


def _build_day2(greeting: str, app_url: str) -> tuple[str, str]:
    """Day 2 — Feature spotlight: the analysis pipeline."""
    html_body = f"""
      <p {_body_text()}>{greeting}</p>
      <p {_body_text()}>
        You joined the waitlist because you want to stop guessing at lighting setups.
        Here's how it actually works — no fluff.
      </p>
      <div style="background:#1E2129;border-radius:8px;padding:20px;margin-bottom:24px;">
        <p style="color:#A9AFBB;font-size:0.875rem;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;margin:0 0 12px;">
          The 7-stage analysis pipeline
        </p>
        <ol style="color:#F4F6F8;font-size:0.9375rem;line-height:1.8;margin:0;padding-left:20px;">
          <li><strong>Face & Region Detection</strong> — isolates subject from background</li>
          <li><strong>Shadow Direction Analysis</strong> — maps key light position from shadow cast</li>
          <li><strong>Catchlight Reading</strong> — identifies modifier shape from eye reflections</li>
          <li><strong>Tone &amp; Contrast Mapping</strong> — measures fill ratio and wrap quality</li>
          <li><strong>Pattern Classification</strong> — resolves to 1 of 28 named lighting patterns</li>
          <li><strong>Gear Matching</strong> — finds real equipment that recreates the detected setup</li>
          <li><strong>Blueprint Generation</strong> — outputs a ready-to-shoot diagram</li>
        </ol>
      </div>
      <p {_body_text()}>
        The whole pipeline runs in under 8 seconds. You upload a photo.
        You get a complete lighting breakdown with gear recommendations — not "it looks like soft light from the left."
      </p>
      {_cta_button(f"{app_url}/early-access", "See your spot on the waitlist →")}
    """
    text = f"""{greeting}

Here's how the analysis actually works (no fluff):

1. Face & Region Detection — isolates subject from background
2. Shadow Direction Analysis — maps key light from shadow cast
3. Catchlight Reading — identifies modifier shape from eye reflections
4. Tone & Contrast Mapping — measures fill ratio and wrap
5. Pattern Classification — resolves to 1 of 28 named patterns
6. Gear Matching — finds real equipment that recreates the setup
7. Blueprint Generation — ready-to-shoot diagram output

The whole pipeline runs in under 8 seconds. Not "it looks like soft light." A complete breakdown with gear.

{app_url}/early-access
"""
    return _base_html(SEQUENCE[0]["preview"], html_body, app_url), text


def _build_day5(greeting: str, app_url: str) -> tuple[str, str]:
    """Day 5 — Social proof: pattern detection demo."""
    html_body = f"""
      <p {_body_text()}>{greeting}</p>
      <p {_body_text()}>
        Quick question: when you look at a portrait, can you immediately name the lighting pattern?
      </p>
      <p {_body_text()}>
        Most photographers can't — and that's not a skill gap, it's a practice gap.
        Rembrandt, loop, butterfly, split, broad, short — 28 named patterns,
        each with different gear, positions, and looks. Knowing which you're looking at (or shooting)
        changes everything about your setup decisions.
      </p>
      <div style="background:#1E2129;border-radius:8px;padding:20px;margin-bottom:24px;">
        <p style="color:#A9AFBB;font-size:0.875rem;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;margin:0 0 12px;">
          What gets detected in every photo
        </p>
        <ul style="color:#F4F6F8;font-size:0.9375rem;line-height:1.8;margin:0;padding-left:20px;">
          <li>Lighting pattern (28 classifications)</li>
          <li>Modifier family — octabox, beauty dish, strip, parabolic, reflector</li>
          <li>Key light position — front, 45°, 90°, backlit</li>
          <li>Fill method — reflector, second light, ambient, none</li>
          <li>Light count and background separation</li>
          <li>Skin tone and catchlight shape</li>
        </ul>
      </div>
      <p {_body_text()}>
        Upload any portrait — reference shot, inspiration image, your own work — and get the full breakdown in seconds.
      </p>
      {_cta_button(f"{app_url}/early-access", "Claim your early access spot →")}
    """
    text = f"""{greeting}

Quick question: when you look at a portrait, can you immediately name the lighting pattern?

Most photographers can't — and that's not a skill gap, it's a practice gap.

What gets detected in every photo:
- Lighting pattern (28 classifications)
- Modifier family — octabox, beauty dish, strip, parabolic, reflector
- Key light position — front, 45°, 90°, backlit
- Fill method — reflector, second light, ambient, none
- Light count and background separation
- Skin tone and catchlight shape

Upload any portrait. Get the full breakdown in seconds.

{app_url}/early-access
"""
    return _base_html(SEQUENCE[1]["preview"], html_body, app_url), text


def _build_day10(greeting: str, app_url: str) -> tuple[str, str]:
    """Day 10 — Urgency: spots filling up."""
    html_body = f"""
      <p {_body_text()}>{greeting}</p>
      <p {_body_text()}>
        A quick update on where things stand.
      </p>
      <div style="background:#1E2129;border-radius:8px;padding:20px;margin-bottom:24px;">
        <p style="color:#A9AFBB;font-size:0.875rem;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;margin:0 0 12px;">
          Waitlist update
        </p>
        <ul style="color:#F4F6F8;font-size:0.9375rem;line-height:1.8;margin:0;padding-left:20px;">
          <li>Onboarding in batches of 50</li>
          <li>First 500 get <strong>3 months free + price lock</strong></li>
          <li>Your spot is still reserved — but the batches are moving</li>
        </ul>
      </div>
      <p {_body_text()}>
        We're keeping early access small on purpose. A smaller first group means faster feedback,
        better support, and a tighter product. Everyone who gets in early shapes what we build next.
      </p>
      <p {_body_text()}>
        When your batch opens, you'll get a personal invite link.
        No generic sign-up page — direct access.
      </p>
      {_cta_button(f"{app_url}/early-access", "Check your waitlist position →")}
    """
    text = f"""{greeting}

A quick update on where things stand.

Waitlist status:
- Onboarding in batches of 50
- First 500 get 3 months free + price lock
- Your spot is still reserved — but the batches are moving

We're keeping early access small on purpose. A smaller first group means faster feedback,
better support, and a tighter product. Everyone who gets in early shapes what we build next.

When your batch opens, you'll get a personal invite link. No generic sign-up — direct access.

{app_url}/early-access
"""
    return _base_html(SEQUENCE[2]["preview"], html_body, app_url), text


def _build_day14(greeting: str, app_url: str) -> tuple[str, str]:
    """Day 14 — Last call."""
    html_body = f"""
      <p {_body_text()}>{greeting}</p>
      <p {_body_text()}>
        This is the last email I'll send before we close early access to new signups.
      </p>
      <p {_body_text()}>
        Your spot is still reserved. The deal is still on the table:
      </p>
      <div style="background:#1E2129;border-radius:8px;padding:20px;margin-bottom:24px;">
        <p style="color:#A9AFBB;font-size:0.875rem;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;margin:0 0 12px;">
          Early access offer (first 500)
        </p>
        <ul style="color:#F4F6F8;font-size:0.9375rem;line-height:1.8;margin:0;padding-left:20px;">
          <li><strong>3 months free</strong> when your invite opens</li>
          <li><strong>Price locked</strong> for life — never goes up for you</li>
          <li><strong>Direct line</strong> to the builder — feature requests actually get built</li>
          <li><strong>Studio tier access</strong> before public release</li>
        </ul>
      </div>
      <p {_body_text()}>
        Once the waitlist closes, the 3-months-free offer disappears with it.
        No exceptions — it's how we keep early access meaningful for the people who got in first.
      </p>
      {_cta_button(f"{app_url}/early-access", "Claim your spot now →")}
      <p {_body_text(color="#A9AFBB")}>
        If you've already decided this isn't for you, no worries — you won't hear from me again.
        If you're in, your invite link is coming soon.
      </p>
    """
    text = f"""{greeting}

This is the last email I'll send before we close early access to new signups.

Your spot is still reserved. The deal is still on the table:

Early access offer (first 500):
- 3 months free when your invite opens
- Price locked for life — never goes up for you
- Direct line to the builder — feature requests actually get built
- Studio tier access before public release

Once the waitlist closes, the 3-months-free offer disappears with it.

{app_url}/early-access

If you've already decided this isn't for you, no worries — you won't hear from me again.
If you're in, your invite link is coming soon.
"""
    return _base_html(SEQUENCE[3]["preview"], html_body, app_url), text


_BUILDERS = {
    "day2":  _build_day2,
    "day5":  _build_day5,
    "day10": _build_day10,
    "day14": _build_day14,
}


# ── SMTP sender ───────────────────────────────────────────────────────────────

def _smtp_send(to_email: str, subject: str, html: str, text: str) -> None:
    smtp_host  = os.getenv("SMTP_HOST", "smtp.resend.com")
    smtp_port  = int(os.getenv("SMTP_PORT", "587"))
    smtp_user  = os.getenv("SMTP_USER", "resend")
    smtp_pass  = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("FROM_EMAIL", "noreply@noguessworksystems.com")

    if not smtp_pass:
        logger.warning("email_sequence: SMTP_PASS not set — skipping send to %s", to_email)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"No Guesswork <{from_email}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to_email], msg.as_string())


# ── State helpers ─────────────────────────────────────────────────────────────

def _load() -> List[Dict]:
    if not WAITLIST_PATH.exists():
        return []
    try:
        return json.loads(WAITLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: List[Dict]) -> None:
    WAITLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAITLIST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    tmp.replace(WAITLIST_PATH)


# ── Core check-and-send ───────────────────────────────────────────────────────

# RFC 2606 / RFC 6761 reserved names plus this project's own test domain.
# These can never receive mail, so sending to them only generates bounces.
_UNDELIVERABLE_DOMAINS = frozenset({
    "test.com", "example.com", "example.org", "example.net",
    "test", "example", "invalid", "localhost", "ngw.test",
})


def _is_undeliverable(email: str) -> bool:
    """True when the address cannot receive mail by definition."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    if domain in _UNDELIVERABLE_DOMAINS:
        return True
    # Any .test / .invalid / .example / .localhost TLD — reserved by RFC 6761.
    return domain.rsplit(".", 1)[-1] in {"test", "invalid", "example", "localhost"}


def check_and_send_follow_ups() -> Dict[str, Any]:
    """
    Iterate all waitlist entries and send any due follow-up emails.
    Returns a summary dict: {checked, sent, skipped, errors}.
    """
    app_url = os.getenv("APP_URL", "https://noguessworksystems.com")
    entries = _load()
    now     = datetime.now(timezone.utc)

    sent   = 0
    skipped = 0
    errors  = 0

    changed = False

    for entry in entries:
        email      = entry.get("email", "")
        first_name = entry.get("first_name", "")
        joined_raw = entry.get("joined_at", "")

        if not email or not joined_raw:
            skipped += 1
            continue

        # Never mail an undeliverable address. Added 2026-08-31 after every
        # deploy re-sent the full sequence to smoketest@test.com and
        # wltest+...@ngw.test — reserved and internal domains, so each send is
        # a hard bounce charged against a Resend sender with no reputation to
        # spend. Defence in depth: the state-persistence fix above stops the
        # re-sending, this stops the mail regardless of state.
        if _is_undeliverable(email):
            logger.info("email_sequence: skipping undeliverable address %s", email)
            skipped += 1
            continue

        try:
            joined_at = datetime.fromisoformat(joined_raw)
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=timezone.utc)
        except Exception:
            skipped += 1
            continue

        already_sent: List[str] = entry.get("follow_ups_sent", [])
        greeting = f"Hi {first_name}," if first_name else "Hey,"

        for step in SEQUENCE:
            step_id  = step["id"]
            day      = step["day"]
            due_at   = joined_at + timedelta(days=day)

            if step_id in already_sent:
                continue  # already delivered

            if now < due_at:
                continue  # not due yet

            # Due — build and send
            builder = _BUILDERS.get(step_id)
            if not builder:
                continue

            try:
                html, text = builder(greeting, app_url)
                _smtp_send(email, step["subject"], html, text)
                already_sent.append(step_id)
                entry["follow_ups_sent"] = already_sent
                changed = True
                sent += 1
                logger.info(
                    "email_sequence: sent %s to %s (day %d)",
                    step_id, email, day,
                )
            except Exception as exc:
                errors += 1
                logger.error(
                    "email_sequence: failed to send %s to %s — %s",
                    step_id, email, exc,
                )

    if changed:
        _save(entries)

    result = {
        "checked": len(entries),
        "sent":    sent,
        "skipped": skipped,
        "errors":  errors,
    }
    logger.info("email_sequence: check complete — %s", result)
    return result


# ── Background loop ───────────────────────────────────────────────────────────

_seq_task: Optional[asyncio.Task] = None


async def _sequence_loop() -> None:
    """Run check_and_send_follow_ups() every SEQUENCE_CHECK_INTERVAL_HOURS hours."""
    interval = SEQUENCE_CHECK_INTERVAL_HOURS * 3600
    logger.info(
        "email_sequence: background loop started — interval=%dh",
        SEQUENCE_CHECK_INTERVAL_HOURS,
    )
    while True:
        try:
            check_and_send_follow_ups()
        except Exception as exc:
            logger.exception("email_sequence: loop iteration error — %s", exc)
        await asyncio.sleep(interval)


def boot_sequence() -> None:
    """
    Called from FastAPI lifespan. Auto-starts only when
    WAITLIST_SEQUENCE_ENABLED=1 and SMTP_PASS is set.
    """
    global _seq_task
    if os.getenv("WAITLIST_SEQUENCE_ENABLED", "").strip() not in ("1", "true", "yes"):
        logger.info("email_sequence: disabled (set WAITLIST_SEQUENCE_ENABLED=1 to enable)")
        return
    if not os.getenv("SMTP_PASS", ""):
        logger.warning("email_sequence: SMTP_PASS not set — sequence will not send emails")

    _seq_task = asyncio.create_task(_sequence_loop(), name="ngw-email-sequence")
    logger.info("email_sequence: background task started")


def stop_sequence() -> None:
    global _seq_task
    if _seq_task and not _seq_task.done():
        _seq_task.cancel()
        logger.info("email_sequence: background task cancelled")
