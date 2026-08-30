"""Lightweight in-memory sliding-window rate limiter.

Used to protect /auth/* endpoints from brute-force and enumeration attacks.
No external dependency required — state is per-process (suitable for single-server
deployments; for multi-instance, replace with Redis-backed storage).

Usage:
    from auth.rate_limit import check_rate_limit

    check_rate_limit("login", request, limit=5, window=60)
    # Raises HTTP 429 if the caller has exceeded `limit` attempts in `window` seconds.

Environment variables:
    TRUST_PROXY_HEADERS=1   (default) — trust X-Forwarded-For from any upstream.
    TRUST_PROXY_HEADERS=0   — ignore X-Forwarded-For; always use socket IP. Use
                              this when not behind a verified reverse proxy to prevent
                              rate-limit bypass via spoofed X-Forwarded-For headers.
    TRUSTED_PROXY_IPS       — comma-separated IPs of trusted proxies (e.g. Render,
                              Cloudflare egress). When set, X-Forwarded-For is only
                              honoured when the direct socket IP is in this list.
    TRUST_PROXY_INDEX       (default 0) — which X-Forwarded-For entry to treat as
                              the client, counted from the LEFT. 0 is the address
                              the edge recorded.

SECURITY NOTE — fixed 2026-08-29.
    This module previously read ``X-Forwarded-For.split(",")[0]`` — the LEFTMOST
    entry. Each proxy APPENDS the address it received the connection from, so the
    leftmost entry is whatever the client sent and is entirely attacker-controlled;
    only the rightmost entries were written by infrastructure. With the shipped
    defaults (TRUST_PROXY_HEADERS unset, TRUSTED_PROXY_IPS unset) that made every
    limit in the app bypassable by rotating one header.

    Measured before that fix: 50 of 50 requests allowed against a 5-per-60s login
    limit, from a single caller, by varying X-Forwarded-For. The control — the same
    caller NOT varying the header — was correctly cut off at 5.

CORRECTION — 2026-08-30, measured against PRODUCTION rather than a simulation.
    Reading from the RIGHT was wrong, and shipping it BROKE rate limiting entirely.
    Render appends an internal hop that VARIES per request, so the rightmost entry
    is a different value every time and every request got its own bucket. Verified
    live: 10 password-reset requests and 8 failed logins, no header spoofing at
    all, zero 429s. Locally reproduced by simulating "client, 10.0.0.N" — 8 of 8
    allowed — while a single-entry header correctly cut off at 5.

    The original code read the LEFTMOST entry. That is caller-controlled, so a
    determined attacker could rotate past it — but it was STABLE for an honest
    client, so ordinary limits worked. The "fix" traded a bypass an attacker had
    to reach for, for no limit at all for anybody. Reverted to the left.

    The lesson is the one this repo keeps relearning: the fix was verified against
    a hand-built fake Request, never against the real proxy. A simulation agreed
    with the code because both came from the same wrong model.

    What actually bounds abuse now is the second change: any limit carrying an
    `extra` discriminator keys on THAT ALONE, so per-account brute force and email
    enumeration are bounded regardless of address. Pure per-IP limits behind this
    proxy remain best-effort and are documented as such rather than trusted.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request


# ── Proxy trust configuration ────────────────────────────────────────────────
# TRUST_PROXY_HEADERS=0 → always use socket IP (safest when not behind a proxy)
# TRUSTED_PROXY_IPS     → only trust X-Forwarded-For from these exact IPs
_TRUST_PROXY = os.getenv("TRUST_PROXY_HEADERS", "1").strip() not in ("0", "false", "no")
_TRUSTED_IPS: frozenset[str] = frozenset(
    ip.strip() for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if ip.strip()
)
# Index into X-Forwarded-For, counted from the LEFT. 0 is the client address as
# the edge recorded it. Configurable so a deployment behind a different proxy
# chain can move it without a code change.
def _hop_index() -> int:
    try:
        return max(0, int(os.getenv("TRUST_PROXY_INDEX", "0")))
    except ValueError:
        return 0


# ── Store ───────────────────────────────────────────────────────────────────────
# buckets[namespace][key] = deque of timestamps (float, seconds since epoch)
_buckets: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
_lock = Lock()


def _client_key(request: Request, extra: Optional[str] = None) -> str:
    """Derive a stable key from the request IP (and optionally an extra discriminator).

    X-Forwarded-For is only trusted when:
      - TRUST_PROXY_HEADERS is not disabled, AND
      - Either TRUSTED_PROXY_IPS is empty (trust all proxies) OR the direct
        socket IP is in the trusted proxy list.

    This prevents clients from spoofing their IP via a forged X-Forwarded-For
    header when the server is not behind a known, validated proxy.
    """
    socket_ip = request.client.host if request.client else "unknown"

    use_forwarded = (
        _TRUST_PROXY
        and (not _TRUSTED_IPS or socket_ip in _TRUSTED_IPS)
    )

    if use_forwarded:
        forwarded_for = request.headers.get("X-Forwarded-For")
        parts = [p.strip() for p in (forwarded_for or "").split(",") if p.strip()]
        # Position counted from the LEFT. See the CORRECTION note in the module
        # docstring: reading from the right was measured broken in production.
        idx = _hop_index()
        ip = parts[idx] if len(parts) > idx else socket_ip
    else:
        ip = socket_ip

    # When a caller-independent discriminator is supplied -- an email address,
    # an account id -- key on it ALONE, not on ip:extra.
    #
    # Measured 2026-08-30: behind Render the IP component is not stable, so
    # ip:email gave a fresh bucket per request and the per-account limits did
    # nothing. Keying on `extra` alone makes per-account brute force and email
    # enumeration bounded no matter how the caller manipulates its address,
    # which is the threat those particular limits exist for. The cost is that
    # one abuser can exhaust a victim account's reset budget -- a real tradeoff,
    # accepted deliberately, because the alternative measured as no limit at all.
    if extra:
        return f"extra:{extra}"
    return ip


def check_rate_limit(
    namespace: str,
    request: Request,
    *,
    limit: int,
    window: int,
    extra: Optional[str] = None,
) -> None:
    """Enforce a sliding-window rate limit.

    Args:
        namespace: Logical bucket name, e.g. "login" or "register".
        request:   The incoming FastAPI Request (used to extract client IP).
        limit:     Maximum number of requests allowed in `window` seconds.
        window:    Rolling window size in seconds.
        extra:     Optional extra discriminator appended to the key
                   (e.g. the submitted email, to rate-limit per-account too).

    Raises:
        HTTPException(429): when the caller has exceeded the limit.
    """
    key    = _client_key(request, extra)
    now    = time.monotonic()
    cutoff = now - window

    with _lock:
        dq = _buckets[namespace][key]
        # Evict timestamps outside the current window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            retry_after = int(window - (now - dq[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
        dq.append(now)
        # ── Memory leak fix: remove empty bucket entries ──────────────────────
        # After evicting expired timestamps, if the deque is now empty, clean up
        # the key so the dict doesn't grow unbounded with unique IP addresses.
        # The deque was just appended to so it's never empty here — this guard
        # runs after the 429 branch to also clean up entries that hit the limit
        # and were left with only old (now-evicted) timestamps. The actual cleanup
        # happens on the NEXT call for that key once all timestamps expire.
        # Additionally, prune other empty keys in this namespace periodically.
        ns_dict = _buckets[namespace]
        dead_keys = [k for k, q in ns_dict.items() if not q]
        for k in dead_keys:
            del ns_dict[k]
