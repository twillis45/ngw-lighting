"""Admin identity resolution — single source of truth.

Admin accounts were previously hardcoded as ``todd@toddwillisphoto.com`` in ten
separate modules, so the account actually signed in
(``info@noguessworksystems.com``) was never recognized as admin.

Reads ``NGW_ADMIN_EMAILS`` (comma-separated). When the var is unset or blank,
falls back to :data:`DEFAULT_ADMIN_EMAILS` so an unconfigured environment keeps
the prior behavior instead of locking every admin out.

Lives in ``config/`` rather than ``api/`` because ``db/`` needs it too and must
not import from ``api/``. This module imports from neither.

Parsing matches ``db/provenance._env_emails`` exactly: split on commas, strip,
lowercase, drop empty segments. User emails are stored lowercased at write time
(``db/database.create_user``), so a lowercase frozenset compares correctly.
"""
from __future__ import annotations

import os
from typing import Optional

#: Fallback when NGW_ADMIN_EMAILS is unset or blank — preserves prior behavior.
DEFAULT_ADMIN_EMAILS: frozenset[str] = frozenset({"todd@toddwillisphoto.com"})

_ENV_VAR = "NGW_ADMIN_EMAILS"


def _env_emails(var: str) -> frozenset[str]:
    raw = os.getenv(var, "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def get_admin_emails() -> frozenset[str]:
    """Admin addresses from NGW_ADMIN_EMAILS, or the default if unset/blank.

    Read at call time, not import time, so env changes take effect without a
    reimport (and so tests can monkeypatch).
    """
    return _env_emails(_ENV_VAR) or DEFAULT_ADMIN_EMAILS


def is_admin(email: Optional[str]) -> bool:
    """True if ``email`` is an admin account. Tolerates None/empty."""
    if not email:
        return False
    return email.strip().lower() in get_admin_emails()
