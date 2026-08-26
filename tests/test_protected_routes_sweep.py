"""Enumerating auth sweep — every route must gate or justify itself.

Stage-4/5 gate from the Path to Production spine. The point is enumeration:
a test naming specific routes stops working the moment a NEW route arrives
ungated. This walks the live FastAPI route table instead, so an ungated
addition fails here without anyone remembering to update a list.

Two rules, both behavioral rather than source-based:

  1. A route not on PUBLIC_ROUTES must never answer an unauthenticated
     caller with 2xx.
  2. Every route reachable without credentials must appear on PUBLIC_ROUTES
     with a written reason.

Behavior, not decoration, because auth in this codebase is not always a
FastAPI ``Depends``:

  - ``/api/waitlist`` and ``/api/waitlist/run-sequence`` check
    NGW_ADMIN_SECRET inside the handler.
  - ``/api/lab/analysis/{id}/image`` accepts ``?token=`` because an
    ``<img src>`` cannot send an Authorization header.

Both look ungated to a dependency scan and are not. A source-only sweep
would report them as holes and be ignored for it.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

#: Routes intentionally reachable without credentials, each with a reason.
#: Adding a route here is a security decision — write why.
PUBLIC_ROUTES: dict[str, str] = {
    # ── Marketing / static shell ──
    "/": "Marketing landing page.",
    "/features": "Marketing page.",
    "/pricing": "Marketing page.",
    "/library": "Marketing page.",
    "/blog": "Marketing page.",
    "/early-access": "Marketing page.",
    "/login": "Unauthenticated by definition — the sign-in page.",
    "/signup": "Unauthenticated by definition — the registration page.",
    "/ui": "SPA shell. Its data calls are gated individually.",
    "/ghost-rembrandt.jpg": "Static marketing asset.",
    "/robots.txt": "Crawler directives — must be public.",
    "/sitemap.xml": "Crawler sitemap — must be public.",

    # ── API docs ──
    "/docs": "OpenAPI docs UI.",
    "/docs/": "OpenAPI docs UI.",
    "/docs/{page}": "Docs page renderer — static content.",
    "/docs/oauth2-redirect": "OAuth2 redirect helper for the docs UI.",
    "/redoc": "OpenAPI docs UI.",
    "/openapi.json": "OpenAPI schema.",

    # ── Health ──
    "/health": "Liveness probe — Render healthCheckPath.",
    "/api/health": "Liveness probe.",

    # ── Auth entry points — cannot require the credential they issue ──
    "/api/auth/register": "Creates the account.",
    "/api/auth/login": "Issues the token.",
    "/api/auth/google": "OAuth sign-in.",
    "/api/auth/magic-link/request": "Passwordless sign-in request.",
    "/api/auth/magic-link/verify": "Passwordless sign-in verification.",
    "/api/auth/password-reset/request": "Reset for a user who cannot sign in.",
    "/api/auth/password-reset/confirm": "Reset for a user who cannot sign in.",
    "/api/auth/verify-email": "Token-in-link email verification.",

    # ── Public product surface ──
    "/api/config": "Client bootstrap config — no user data.",
    "/api/master-modes": "Static taxonomy.",
    "/api/lab/face-preflight": (
        "CV-only face landmarks for the Studio processing animation. The shell "
        "fetches it with no Authorization header. No VLM, no pipeline, no DB "
        "write; rate-limited 20/60s. See api/routes/lab.py PUBLIC ROUTE marker."
    ),

    # ── Public accuracy gallery ──
    "/api/gallery": (
        "Deliberately public. The product's claim is that it reads light "
        "correctly, and it cannot be audited from behind a sign-in wall. "
        "Serves approved reference entries with ground truth and our read, "
        "including misses. No user data."
    ),
    "/api/gallery/{entry_id}/thumbnail": "Gallery image for a public entry.",
    "/api/gallery/{entry_id}/overlay": "Debug overlay for a public entry — what the engine saw.",

    # ── Share-token addressed ──
    "/api/shared/setup/{share_token}": "Bearer-token-in-URL share link.",
    "/api/team-sessions/{share_token}": "Bearer-token-in-URL share link.",

    # ── Third-party callback ──
    "/api/stripe/webhook": "Stripe callback; authenticated by signature.",

    # ── Anonymous clients legitimately need these ──
    "/api/flags": "Per-session flag evaluation; the shell cannot render without it.",
    "/api/auth/subscription-status": "Returns the free tier for anonymous callers.",
    "/api/auth/logout": "No-op without a session.",
    "/api/diagnostics": "Troubleshooting catalog — product content, not user data.",
    "/api/diagnostics/{failure_id}": "Troubleshooting catalog entry.",
    "/api/paywall/adaptive-pricing": "Anonymous visitors are shown the paywall.",

    # ── REVIEW: reachable anonymously; flagged for a gating decision ──
    # /api/intelligence/score, /score/history and /patterns were here and are
    # now gated with get_dev_user — their only callers are ui/src/data/labApi.js.
    "/api/intelligence/sample-calc": "REVIEW: sample scoring calculation. Demo content?",
    "/api/paywall/impression/{impression_id}/converted": (
        "REVIEW: anonymous write keyed on a caller-supplied impression id with "
        "no ownership check. No disclosure; analytics-integrity risk only."
    ),
    "/api/paywall/impression/{impression_id}/dismissed": (
        "REVIEW: anonymous write keyed on a caller-supplied impression id with "
        "no ownership check. No disclosure; analytics-integrity risk only."
    ),

    # ── Handler-level auth (not a FastAPI dependency) ──
    "/api/waitlist": "Handler checks NGW_ADMIN_SECRET; POST is public signup.",
    "/api/waitlist/run-sequence": "Handler checks NGW_ADMIN_SECRET.",
    "/api/lab/analysis/{analysis_id}/image": (
        "Handler authenticates via header or ?token= — an <img src> cannot "
        "send an Authorization header."
    ),
}


def _routes():
    """(method, path) for every real HTTP route on the app."""
    out = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if not methods:
            continue
        methods = {m for m in methods if m not in ("HEAD", "OPTIONS")}
        for m in sorted(methods):
            out.append((m, r.path))
    return sorted(set(out))


def _call_bare(method: str, path: str):
    """Issue an unauthenticated request, substituting dummy path params."""
    url = path
    while "{" in url:
        head, _, rest = url.partition("{")
        _, _, tail = rest.partition("}")
        url = head + "test" + tail
    return client.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)


@pytest.fixture(autouse=True)
def _no_dev_mode(monkeypatch):
    """Dev mode returns a mock user and would mask every gate."""
    monkeypatch.setenv("NGW_DEV_MODE", "0")


@pytest.mark.parametrize("method,path", _routes())
def test_gated_route_rejects_anonymous(method, path):
    """A non-public route must never answer an anonymous caller with 2xx."""
    if path in PUBLIC_ROUTES:
        pytest.skip(f"public by decision: {PUBLIC_ROUTES[path]}")
    resp = _call_bare(method, path)
    assert not (200 <= resp.status_code < 300), (
        f"{method} {path} returned {resp.status_code} to an anonymous caller. "
        f"Either gate it, or add it to PUBLIC_ROUTES with a written reason."
    )


def test_public_allowlist_has_no_stale_entries():
    """Every allowlisted path must still exist — stale entries hide new routes."""
    live = {p for _, p in _routes()}
    stale = sorted(set(PUBLIC_ROUTES) - live)
    assert not stale, f"PUBLIC_ROUTES names routes that no longer exist: {stale}"


def test_every_public_route_states_a_reason():
    for path, reason in PUBLIC_ROUTES.items():
        assert reason.strip(), f"{path} is allowlisted with no reason"
