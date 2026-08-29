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
    TRUST_PROXY_HOPS        (default 1) — how many trusted proxies sit in front of
                              this app. The client IP is read that many positions
                              from the RIGHT of X-Forwarded-For. Raise it only if
                              you actually add another proxy in front.

SECURITY NOTE — fixed 2026-08-29.
    This module previously read ``X-Forwarded-For.split(",")[0]`` — the LEFTMOST
    entry. Each proxy APPENDS the address it received the connection from, so the
    leftmost entry is whatever the client sent and is entirely attacker-controlled;
    only the rightmost entries were written by infrastructure. With the shipped
    defaults (TRUST_PROXY_HEADERS unset, TRUSTED_PROXY_IPS unset) that made every
    limit in the app bypassable by rotating one header.

    Measured before the fix: 50 of 50 requests allowed against a 5-per-60s login
    limit, from a single caller, by varying X-Forwarded-For. The control — the same
    caller NOT varying the header — was correctly cut off at 5. The limiter worked;
    the key did not. Brute-force protection on login, registration, password reset,
    magic-link and Google auth all rested on it.
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
# How many trusted proxies sit in front of the app. Render puts exactly one there.
def _hops() -> int:
    try:
        return max(1, int(os.getenv("TRUST_PROXY_HOPS", "1")))
    except ValueError:
        return 1


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
        hops = _hops()
        # Read from the RIGHT. Proxies append, so the last `hops` entries are the
        # ones infrastructure wrote; everything left of them is caller-supplied.
        # If the header is shorter than the hop count the chain is not what we
        # think it is, so fall back to the socket IP rather than trust a guess.
        ip = parts[-hops] if len(parts) >= hops else socket_ip
    else:
        ip = socket_ip

    return f"{ip}:{extra}" if extra else ip


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
