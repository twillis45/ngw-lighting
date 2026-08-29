"""The rate-limit key must not be attacker-controlled.

Regression test for a live bypass found 2026-08-29. `_client_key` read the
LEFTMOST X-Forwarded-For entry. Proxies APPEND the address they received the
connection from, so the leftmost entry is whatever the caller sent. With the
shipped defaults every limit in the app was bypassable by rotating one header:
50 of 50 requests were allowed against a 5-per-60s login limit.

That covered login brute-force, registration, password reset, magic-link and
Google auth — and it is the whole basis on which anonymous analysis (build b7)
would ever rest.
"""
import types

import pytest

from auth.rate_limit import _client_key, check_rate_limit
from fastapi import HTTPException

PROXY = "10.0.0.7"


def _req(socket_ip=PROXY, xff=None):
    r = types.SimpleNamespace()
    r.client = types.SimpleNamespace(host=socket_ip)
    r.headers = {"X-Forwarded-For": xff} if xff else {}
    return r


def test_rotating_forwarded_for_does_not_change_the_key():
    """One caller behind one proxy is ONE key, however they forge the header."""
    keys = {
        _client_key(_req(xff=f"9.9.9.{i}, {PROXY}"))
        for i in range(50)
    }
    assert len(keys) == 1, f"key is attacker-controlled: {len(keys)} distinct keys"


def test_limit_actually_holds_against_a_rotating_header(monkeypatch):
    allowed = 0
    for i in range(50):
        try:
            check_rate_limit(
                "test_rotate", _req(xff=f"9.9.9.{i}, {PROXY}"), limit=5, window=60
            )
            allowed += 1
        except HTTPException:
            pass
    assert allowed == 5, f"{allowed}/50 allowed against a limit of 5"


def test_real_client_ip_is_still_distinguished():
    """The fix must not collapse genuinely different callers into one bucket."""
    a = _client_key(_req(xff=f"1.1.1.1"))
    b = _client_key(_req(xff=f"2.2.2.2"))
    assert a != b, "distinct callers must not share a bucket"


def test_short_header_falls_back_to_socket_ip():
    """A chain shorter than the hop count is not the chain we think it is."""
    assert _client_key(_req(socket_ip="203.0.113.9", xff="")) == "203.0.113.9"


def test_extra_discriminator_still_applies():
    a = _client_key(_req(xff=f"1.1.1.1"), extra="alice@example.com")
    b = _client_key(_req(xff=f"1.1.1.1"), extra="bob@example.com")
    assert a != b
