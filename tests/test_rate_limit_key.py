"""What the rate-limit key must and must not depend on.

HISTORY, because this file has been wrong twice and the reasons matter.

2026-08-29 — found that `_client_key` read the LEFTMOST X-Forwarded-For entry,
which a caller controls, so rotating one header gave 50 of 50 requests against a
5-per-60s login limit. Changed to read from the RIGHT and shipped it.

2026-08-30 — measured against PRODUCTION and found that change had BROKEN rate
limiting entirely. Render appends an internal hop that VARIES per request, so
the rightmost entry differs every time and every request got its own bucket.
Ten password-reset requests and eight failed logins, no spoofing at all, zero
429s. The previous behaviour at least held for honest clients; the "fix" traded
a bypass an attacker had to reach for, for no limit at all for anyone.

The lesson: the first fix was verified against a hand-built fake Request and
never against the real proxy, so a simulation agreed with the code because both
came from the same wrong model. These tests now assert the SHAPE production
actually sends.

What bounds abuse now is that any limit carrying an `extra` discriminator keys
on that alone, so per-account brute force and enumeration hold regardless of
address. Pure per-IP limits behind this proxy are best-effort and are asserted
here as such rather than pretended to be more.
"""
import types

import pytest
from fastapi import HTTPException

from auth.rate_limit import _client_key, check_rate_limit

# What Render actually sends: the client, then an internal hop that varies.
def _req(client="198.51.100.9", hop=None, socket_ip="10.0.0.1"):
    xff = f"{client}, {hop}" if hop else client
    r = types.SimpleNamespace()
    r.client = types.SimpleNamespace(host=socket_ip)
    r.headers = {"X-Forwarded-For": xff}
    return r


def test_a_varying_appended_hop_does_not_change_the_key():
    """The regression that broke production. One client, many internal hops."""
    keys = {_client_key(_req(hop=f"10.0.0.{i}")) for i in range(50)}
    assert len(keys) == 1, (
        f"a varying proxy hop produced {len(keys)} keys — every request would "
        "get its own bucket and nothing would ever be limited")


def test_the_limit_holds_under_a_varying_hop():
    allowed = 0
    for i in range(50):
        try:
            check_rate_limit("t_hop", _req(hop=f"10.0.0.{i}"), limit=5, window=60)
            allowed += 1
        except HTTPException:
            pass
    assert allowed == 5, f"{allowed}/50 allowed against a limit of 5"


def test_distinct_clients_do_not_share_a_bucket():
    """The failure mode in the other direction: over-collapsing keys would let
    one abuser lock every user out."""
    keys = {_client_key(_req(client=f"203.0.113.{i}", hop="10.0.0.7")) for i in range(20)}
    assert len(keys) == 20


def test_an_account_scoped_limit_ignores_the_address_entirely():
    """This is what actually bounds brute force and enumeration. Rotating the
    client address must NOT buy more attempts against one account."""
    allowed = 0
    for i in range(30):
        try:
            check_rate_limit("t_acct", _req(client=f"9.9.9.{i}", hop=f"10.0.0.{i}"),
                             limit=3, window=900, extra="victim@example.com")
            allowed += 1
        except HTTPException:
            pass
    assert allowed == 3, f"{allowed}/30 allowed against a per-account limit of 3"


def test_different_accounts_are_still_independent():
    a = _client_key(_req(), extra="alice@example.com")
    b = _client_key(_req(), extra="bob@example.com")
    assert a != b


def test_no_forwarded_header_falls_back_to_the_socket():
    r = types.SimpleNamespace()
    r.client = types.SimpleNamespace(host="203.0.113.9")
    r.headers = {}
    assert _client_key(r) == "203.0.113.9"
