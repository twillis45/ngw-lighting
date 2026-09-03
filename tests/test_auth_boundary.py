"""The public auth boundary, pinned by behaviour rather than by library.

Written 2026-09-03 as the PREREQUISITE for review-board condition C6's second
half. The board found python-jose 3.3.0 (released 2021, effectively
unmaintained, carrying the known algorithm-confusion advisories) and passlib
1.7.4 (2020, forcing bcrypt back to 3.2.2) verifying every JWT and hashing every
password on a public surface — and NO test file exercising any of it.

Swapping a JWT library with no gate is how a working login becomes a broken one
silently, so the gate is written first and must pass BEFORE and AFTER any swap.
Everything here is asserted through auth/security.py's own functions, never
against jose or passlib directly, so the tests survive the replacement they
exist to enable.
"""
import time

import pytest

from auth import security as S


class TestPasswordHashing:
    def test_round_trip(self):
        h = S.hash_password("correct horse battery staple")
        assert S.verify_password("correct horse battery staple", h)

    def test_a_wrong_password_is_rejected(self):
        h = S.hash_password("right")
        assert not S.verify_password("wrong", h)

    def test_the_hash_is_not_the_password(self):
        h = S.hash_password("plaintext-must-not-appear")
        assert "plaintext-must-not-appear" not in h

    def test_salted_so_equal_passwords_hash_differently(self):
        assert S.hash_password("same") != S.hash_password("same")

    def test_a_garbage_hash_does_not_crash_the_login(self):
        """An unparseable stored hash must fail closed, not 500."""
        for junk in ("", "not-a-hash", "$2b$xx$broken"):
            try:
                assert S.verify_password("anything", junk) is False
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"verify_password raised on {junk!r}: {exc!r}")


class TestTokenRoundTrip:
    def test_create_then_decode_returns_the_subject(self):
        t = S.create_access_token("user-123")
        assert S.decode_token(t) == "user-123"

    def test_payload_carries_sub_jti_iat_exp(self):
        p = S.decode_token_payload(S.create_access_token("u"))
        assert p and {"sub", "jti", "iat", "exp"} <= set(p)

    def test_each_token_has_its_own_jti(self):
        a = S.decode_token_payload(S.create_access_token("u"))["jti"]
        b = S.decode_token_payload(S.create_access_token("u"))["jti"]
        assert a != b, "a shared jti would revoke every session at once"


class TestForgeryIsRejected:
    """The properties that actually make this a boundary."""

    def test_garbage_is_rejected(self):
        for junk in ("", "abc", "a.b.c", "not.a.jwt"):
            assert S.decode_token(junk) is None

    def test_a_tampered_payload_is_rejected(self):
        t = S.create_access_token("user-A")
        head, payload, sig = t.split(".")
        forged = f"{head}.{payload[:-2] + ('AA' if payload[-2:] != 'AA' else 'BB')}.{sig}"
        assert S.decode_token(forged) is None

    def test_a_token_signed_with_another_secret_is_rejected(self, monkeypatch):
        t = S.create_access_token("user-A")
        monkeypatch.setattr(S, "SECRET_KEY", S.SECRET_KEY + "-different")
        assert S.decode_token(t) is None

    def test_alg_none_is_rejected(self):
        """THE python-jose advisory: an unsigned token claiming alg=none must
        not authenticate anybody. This is the specific property that makes the
        library's maintenance status matter."""
        import base64, json

        def b64(d):
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        forged = f'{b64({"alg": "none", "typ": "JWT"})}.' \
                 f'{b64({"sub": "attacker", "jti": "x", "iat": int(time.time()), "exp": int(time.time()) + 3600})}.'
        assert S.decode_token(forged) is None, "alg=none token authenticated a user"
        assert S.decode_token_payload(forged) is None

    def test_an_expired_token_is_rejected(self, monkeypatch):
        monkeypatch.setattr(S, "ACCESS_TOKEN_EXPIRE_SECONDS", -10)
        assert S.decode_token(S.create_access_token("u")) is None


class TestRevocation:
    def test_a_revoked_token_stops_working(self):
        t = S.create_access_token("user-rev")
        assert S.decode_token(t) == "user-rev"
        S.revoke_token(S.decode_token_payload(t)["jti"])
        assert S.decode_token(t) is None, "logout did not actually revoke"

    def test_revoking_one_token_does_not_revoke_another(self):
        a, b = S.create_access_token("u1"), S.create_access_token("u2")
        S.revoke_token(S.decode_token_payload(a)["jti"])
        assert S.decode_token(a) is None
        assert S.decode_token(b) == "u2"
