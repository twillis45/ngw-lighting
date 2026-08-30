"""Lab authorization must fail CLOSED, and every Lab route must use one rule.

Found 2026-08-30. The lab image route hand-rolled its own check because an
<img src> cannot send an Authorization header, and the copy read:

    if allowed and (user.get("email", "").lower() not in allowed):

With NGW_DEV_EMAILS unset, `allowed` is empty, the condition is False, and
nothing raised. Any registered free account could download Lab analysis
images while every sibling Lab route returned 403 on the same token. The
comment above it said "same as get_dev_user"; it was the opposite.

The rule now lives in one place. These tests assert the rule itself, and that
no second copy has grown back — because two copies of an authorization rule is
how one of them silently becomes the wrong one.
"""
import os
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from auth.dev_guard import assert_lab_access

FREE_USER = {"id": "u1", "email": "free@example.com"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("NGW_DEV_MODE", raising=False)
    monkeypatch.delenv("NGW_DEV_EMAILS", raising=False)


def test_an_unconfigured_whitelist_denies_everyone(monkeypatch):
    """An absent allowlist is an absence of permission, never a grant of it."""
    monkeypatch.setenv("NGW_DEV_EMAILS", "")
    with pytest.raises(HTTPException) as e:
        assert_lab_access(FREE_USER)
    assert e.value.status_code == 403


def test_a_missing_env_var_denies_everyone(monkeypatch):
    with pytest.raises(HTTPException) as e:
        assert_lab_access(FREE_USER)
    assert e.value.status_code == 403


def test_a_non_whitelisted_account_is_denied(monkeypatch):
    monkeypatch.setenv("NGW_DEV_EMAILS", "dev@example.com")
    with pytest.raises(HTTPException) as e:
        assert_lab_access(FREE_USER)
    assert e.value.status_code == 403


def test_a_whitelisted_account_is_allowed_case_insensitively(monkeypatch):
    monkeypatch.setenv("NGW_DEV_EMAILS", "dev@example.com")
    assert assert_lab_access({"id": "u2", "email": "DEV@Example.com"})["id"] == "u2"


def test_no_credentials_is_401_not_403(monkeypatch):
    monkeypatch.setenv("NGW_DEV_EMAILS", "dev@example.com")
    with pytest.raises(HTTPException) as e:
        assert_lab_access(None)
    assert e.value.status_code == 401


def test_no_route_has_grown_a_second_copy_of_the_rule():
    """The structural guard. The defect was a DUPLICATED rule drifting, so the
    thing worth asserting is that the duplicate has not come back."""
    root = Path(__file__).resolve().parent.parent
    offenders = []

    def code_only(src: str) -> str:
        """Strip comments and docstrings before scanning.

        Written after this test's first run flagged a COMMENT that quoted the
        old broken line. Exactly the failure the honest-controls sweep had:
        a source-level regex cannot tell code from prose about code.
        """
        out = []
        for line in src.splitlines():
            stripped = line.split("#", 1)[0]
            out.append(stripped)
        return "\n".join(out)

    for f in (root / "api").rglob("*.py"):
        src = code_only(f.read_text(encoding="utf-8"))
        # Any local re-derivation of the allowlist decision outside dev_guard.
        if re.search(r"if\s+allowed\s+and\b", src):
            offenders.append(f"{f.relative_to(root)}: re-derives the allowlist check")
        if "_get_dev_emails" in src and "assert_lab_access" not in src:
            offenders.append(f"{f.relative_to(root)}: uses _get_dev_emails directly")
    assert not offenders, offenders
