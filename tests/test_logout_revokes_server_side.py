"""Signing out must tell the SERVER, not just the browser.

Found 2026-08-31, and found the hard way: Todd logged out of two sessions whose
JWTs had been pasted into a transcript, and both still returned 200 afterwards.

    export function logout() {
      clearAuth();          // removes two localStorage keys. That is all.
    }

/api/auth/logout exists and works — it adds the token's jti to a blocklist.
Nothing in the app had ever called it. So a copied token stayed valid for its
full 7-day life no matter how many times the user signed out.

Worse, the STUDIO shell — the default one — did not even go through logout().
It called clearAuth() directly at THREE sites, so fixing logout() alone would
have changed nothing for the shell people actually use.

These tests are structural because the defect was structural: a revocation
endpoint that exists and is never called cannot be caught by testing the
endpoint.
"""
import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "ui" / "src"


def _code(p: Path) -> str:
    """Source with // comments stripped — a comment mentioning clearAuth is not
    a call to it, and this project has been bitten by that twice."""
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        out.append(re.sub(r"//.*$", "", line))
    return "\n".join(out)


def test_logout_calls_the_revocation_endpoint():
    src = _code(UI / "data" / "authApi.js")
    m = re.search(r"export async function logout\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "logout() is not an async function that can await revocation"
    body = m.group(1)
    assert "/auth/logout" in body, (
        "logout() never calls /api/auth/logout — the server is never told, so a "
        "copied token stays valid for its full lifetime")
    assert "clearAuth()" in body, "logout() must still clear local state"


def test_no_screen_clears_auth_without_revoking():
    """The real defect. Three sign-out sites bypassed logout() entirely."""
    offenders = []
    for f in UI.rglob("*.jsx"):
        if "clearAuth()" in _code(f):
            offenders.append(str(f.relative_to(UI)))
    for f in UI.rglob("*.js"):
        if f.name == "authApi.js":
            continue
        if "clearAuth()" in _code(f):
            offenders.append(str(f.relative_to(UI)))
    assert not offenders, (
        f"these call clearAuth() directly, so signing out there never reaches "
        f"the server: {offenders}")


def test_local_state_is_cleared_even_if_the_network_fails():
    """A user who cannot reach the network must still sign out of the device."""
    src = _code(UI / "data" / "authApi.js")
    m = re.search(r"export async function logout\(\)\s*\{(.*?)\n\}", src, re.S)
    body = m.group(1)
    assert "catch" in body, "a failed revocation call must not block the local clear"
