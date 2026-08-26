"""
Session Provenance
==================
Tracks the origin and data-hygiene flags for every session so that
internal, admin, and expert sessions are never silently mixed into
production analytics, cohorts, conversion metrics, or the learning engine.

session_origin values
---------------------
  production    — real end user; all flags false by default
  internal      — team / admin account; excluded from everything by default
  expert_review — explicitly invited reviewer; excluded by default but
                  eligible_for_reference_review=True lets them supply
                  reference images after manual promotion

Exclusion flags
---------------
  exclude_from_learning     — keep out of ingestion / failure clusters
  exclude_from_metrics      — keep out of KPI / funnel / pattern queries
  exclude_from_conversion   — keep out of paywall / upgrade queries
  exclude_from_cohorts      — keep out of retention / session quality queries

Review flags (experts and internal only)
-----------------------------------------
  eligible_for_reference_review          — session may be used as reference candidate
  manually_promote_for_learning_review   — operator explicitly chose to include this
                                           session in learning (must be set to True)

Classification is ACCOUNT-BASED only — no behavioral heuristics.

Internal account detection (in priority order):
  1. Email in the admin list (NGW_ADMIN_EMAILS env var — see config/admin.py)
  2. Email in NGW_DEV_EMAILS env var
  3. Email in NGW_EXPERT_EMAILS env var → expert_review
  4. Everything else → production

SQL filter helpers
------------------
  _excl(flag)   — returns a parameterless SQL AND-fragment for any WHERE clause
  EXCL_METRICS  — shorthand for exclude_from_metrics
  EXCL_COHORTS  — shorthand for exclude_from_cohorts
  EXCL_CONV     — shorthand for exclude_from_conversion
  EXCL_LEARNING — shorthand for exclude_from_learning
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from db.database import get_db

# ── Account lists ───────────────────────────────────────────────────────────────

#: Admin / internal accounts — resolved from NGW_ADMIN_EMAILS (see config/admin.py)
from config.admin import get_admin_emails


def _env_emails(var: str) -> frozenset[str]:
    raw = os.getenv(var, "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def get_internal_emails() -> frozenset[str]:
    """Union of the admin list + NGW_DEV_EMAILS."""
    return get_admin_emails() | _env_emails("NGW_DEV_EMAILS")


def get_expert_emails() -> frozenset[str]:
    """NGW_EXPERT_EMAILS env var."""
    return _env_emails("NGW_EXPERT_EMAILS")


# ── Schema ──────────────────────────────────────────────────────────────────────

def init_provenance_table() -> None:
    """Create session_provenance table if it doesn't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS session_provenance (
                session_id                          TEXT PRIMARY KEY,
                user_id                             TEXT,
                user_email                          TEXT,
                session_origin                      TEXT NOT NULL DEFAULT 'production',
                exclude_from_learning               INTEGER NOT NULL DEFAULT 0,
                exclude_from_metrics                INTEGER NOT NULL DEFAULT 0,
                exclude_from_conversion             INTEGER NOT NULL DEFAULT 0,
                exclude_from_cohorts                INTEGER NOT NULL DEFAULT 0,
                eligible_for_reference_review       INTEGER NOT NULL DEFAULT 0,
                manually_promote_for_learning_review INTEGER NOT NULL DEFAULT 0,
                classification_reason               TEXT,
                created_at                          REAL NOT NULL,
                updated_at                          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sp_origin     ON session_provenance(session_origin);
            CREATE INDEX IF NOT EXISTS idx_sp_learning   ON session_provenance(exclude_from_learning);
            CREATE INDEX IF NOT EXISTS idx_sp_metrics    ON session_provenance(exclude_from_metrics);
            CREATE INDEX IF NOT EXISTS idx_sp_conversion ON session_provenance(exclude_from_conversion);
            CREATE INDEX IF NOT EXISTS idx_sp_cohorts    ON session_provenance(exclude_from_cohorts);
            CREATE INDEX IF NOT EXISTS idx_sp_user_id    ON session_provenance(user_id);
        """)


# ── Classification ──────────────────────────────────────────────────────────────

def classify_session(user_email: Optional[str]) -> Dict[str, Any]:
    """
    Return provenance classification fields for a session, based solely
    on the user's email. Called once at session creation.

    Returns a dict matching the session_provenance column set (minus
    session_id, user_id, created_at, updated_at).
    """
    email = (user_email or "").strip().lower()

    if email and email in get_internal_emails():
        return {
            "session_origin": "internal",
            "exclude_from_learning": 1,
            "exclude_from_metrics": 1,
            "exclude_from_conversion": 1,
            "exclude_from_cohorts": 1,
            "eligible_for_reference_review": 1,   # admin may contribute reference images
            "manually_promote_for_learning_review": 0,
            "classification_reason": f"internal account ({email})",
        }

    if email and email in get_expert_emails():
        return {
            "session_origin": "expert_review",
            "exclude_from_learning": 1,   # never passively entered
            "exclude_from_metrics": 1,
            "exclude_from_conversion": 1,
            "exclude_from_cohorts": 1,
            "eligible_for_reference_review": 1,   # can be promoted explicitly
            "manually_promote_for_learning_review": 0,
            "classification_reason": f"expert account ({email})",
        }

    # Production user (anonymous or authenticated non-internal)
    return {
        "session_origin": "production",
        "exclude_from_learning": 0,
        "exclude_from_metrics": 0,
        "exclude_from_conversion": 0,
        "exclude_from_cohorts": 0,
        "eligible_for_reference_review": 0,
        "manually_promote_for_learning_review": 0,
        "classification_reason": "production user" if email else "anonymous session",
    }


# ── CRUD ────────────────────────────────────────────────────────────────────────

def ensure_session_provenance(
    session_id: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a provenance record for session_id if one doesn't already exist.
    Returns the existing or newly created record.

    Safe to call on every track event — the INSERT is ignored if the
    session_id already exists.
    """
    now = time.time()
    fields = classify_session(user_email)
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO session_provenance
               (session_id, user_id, user_email, session_origin,
                exclude_from_learning, exclude_from_metrics, exclude_from_conversion,
                exclude_from_cohorts, eligible_for_reference_review,
                manually_promote_for_learning_review, classification_reason,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id, user_id, user_email,
                fields["session_origin"],
                fields["exclude_from_learning"],
                fields["exclude_from_metrics"],
                fields["exclude_from_conversion"],
                fields["exclude_from_cohorts"],
                fields["eligible_for_reference_review"],
                fields["manually_promote_for_learning_review"],
                fields["classification_reason"],
                now, now,
            ),
        )
    return get_session_provenance(session_id) or {}


def get_session_provenance(session_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM session_provenance WHERE session_id=?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def update_session_provenance(session_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    """
    Update specific fields for a session's provenance record.
    Used for manual promotion and reviewer overrides.
    """
    if not kwargs:
        return get_session_provenance(session_id)
    kwargs["updated_at"] = time.time()
    sets = [f"{k}=?" for k in kwargs]
    vals = list(kwargs.values()) + [session_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE session_provenance SET {', '.join(sets)} WHERE session_id=?", vals
        )
    return get_session_provenance(session_id)


def mark_session_as_test(session_id: str, marked_by: str = "") -> Optional[Dict[str, Any]]:
    """
    Mark a production session as a test/dev session.
    Sets all exclusion flags so the session is removed from every analytics dimension.
    Uses origin='test' to distinguish user-marked sessions from hardcoded internal ones
    (so they can be reverted via unmark_session_as_test).
    """
    reason = f"user-marked test session ({marked_by})" if marked_by else "user-marked test session"
    return update_session_provenance(
        session_id,
        session_origin="test",
        exclude_from_learning=1,
        exclude_from_metrics=1,
        exclude_from_conversion=1,
        exclude_from_cohorts=1,
        classification_reason=reason,
    )


def unmark_session_as_test(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Revert a user-marked test session back to production.
    Only operates on sessions with session_origin='test' — never downgrades
    internal or expert_review sessions.
    Returns the existing record unchanged if it can't be reverted.
    """
    prov = get_session_provenance(session_id)
    if not prov or prov.get("session_origin") != "test":
        return prov  # Refuse to touch internal/expert/production sessions
    return update_session_provenance(
        session_id,
        session_origin="production",
        exclude_from_learning=0,
        exclude_from_metrics=0,
        exclude_from_conversion=0,
        exclude_from_cohorts=0,
        classification_reason="user-unmarked test session (restored to production)",
    )


def promote_session_for_learning(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Explicitly mark an expert/internal session for learning review.
    Clears exclude_from_learning and sets manually_promote_for_learning_review.

    SAFETY: Only sessions with eligible_for_reference_review=1 should be promoted.
    The API layer enforces this check before calling this function.
    """
    return update_session_provenance(
        session_id,
        exclude_from_learning=0,
        manually_promote_for_learning_review=1,
    )


def get_sessions_eligible_for_review(limit: int = 100) -> List[Dict[str, Any]]:
    """Return sessions eligible for reference review (expert/internal, not yet promoted)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM session_provenance
               WHERE eligible_for_reference_review=1
                 AND manually_promote_for_learning_review=0
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_provenance_summary(days: int = 30, origin: Optional[str] = None) -> Dict[str, Any]:
    """
    Return counts of sessions by origin and exclusion status for
    data hygiene observability surfaces.

    When origin is specified ('production' or 'internal'), all counts are
    scoped to that origin class so the summary reflects the selected segment.
    """
    since = time.time() - days * 86400

    # Validate origin against known values — prevents SQL injection
    _VALID_ORIGINS = {'production', 'internal', 'expert_review', 'test', 'all'}
    if origin and origin not in _VALID_ORIGINS:
        raise ValueError(f"Invalid origin filter: {origin!r}. Must be one of {sorted(_VALID_ORIGINS)}")

    # Build optional origin clause — parameterized, never interpolated
    origin_params: tuple = ()
    if origin and origin != 'all':
        if origin == 'internal':
            # 'internal' tab covers internal, expert_review, and user-marked test sessions
            origin_clause = " AND session_origin IN ('internal','expert_review','test')"
        else:
            origin_clause = " AND session_origin=?"
            origin_params = (origin,)
    else:
        origin_clause = ""  # 'all' or no filter → full breakdown

    with get_db() as conn:
        # Counts by origin (always full breakdown — not scoped to origin filter)
        origin_rows = conn.execute(
            """SELECT session_origin, COUNT(*) as cnt
               FROM session_provenance WHERE created_at>=? GROUP BY session_origin""",
            (since,),
        ).fetchall()
        # Total excluded from each dimension (scoped to selected origin)
        excl_learning = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE exclude_from_learning=1 AND created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]
        excl_metrics = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE exclude_from_metrics=1 AND created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]
        excl_conversion = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE exclude_from_conversion=1 AND created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]
        excl_cohorts = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE exclude_from_cohorts=1 AND created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]
        manually_promoted = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE manually_promote_for_learning_review=1 AND created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]
        eligible_review = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE eligible_for_reference_review=1 AND created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]
        total_known = conn.execute(
            f"SELECT COUNT(*) as cnt FROM session_provenance WHERE created_at>=?{origin_clause}",
            (since,) + origin_params,
        ).fetchone()["cnt"]

    by_origin = {r["session_origin"]: r["cnt"] for r in origin_rows}
    return {
        "days": days,
        "total_known_sessions": total_known,
        "by_origin": {
            "production": by_origin.get("production", 0),
            "internal": by_origin.get("internal", 0),
            "expert_review": by_origin.get("expert_review", 0),
            "test": by_origin.get("test", 0),
        },
        "excluded": {
            "from_metrics": excl_metrics,
            "from_conversion": excl_conversion,
            "from_cohorts": excl_cohorts,
            "from_learning": excl_learning,
        },
        "promoted": {
            "eligible_for_review": eligible_review,
            "manually_promoted": manually_promoted,
        },
        "clean_sessions": total_known - excl_metrics,  # sessions counted in production analytics
    }


# ── SQL filter helpers ──────────────────────────────────────────────────────────
#
# These return parameterless AND-fragments that can be appended to any
# WHERE clause in analytics queries. The subquery reads session_provenance
# directly — no extra bind params needed.
#
# Usage in analytics SQL:
#   f"WHERE created_at >= ? {EXCL_METRICS} GROUP BY name"
#
# Sessions with no provenance record are treated as production (included).

def _excl(flag: str) -> str:
    """Return SQL AND-fragment that excludes sessions flagged with `flag`=1."""
    return (
        f" AND (session_id IS NULL"
        f" OR session_id NOT IN"
        f" (SELECT session_id FROM session_provenance WHERE {flag}=1)) "
    )


EXCL_METRICS    = _excl("exclude_from_metrics")
EXCL_COHORTS    = _excl("exclude_from_cohorts")
EXCL_CONVERSION = _excl("exclude_from_conversion")
EXCL_LEARNING   = _excl("exclude_from_learning")
