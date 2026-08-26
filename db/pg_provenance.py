"""
Postgres Session Provenance
============================
Drop-in companion to db/provenance.py for when the project migrates to Postgres.
Provides the same public API surface but targets session_provenance + analytics_events
via asyncpg (async) or psycopg2 (sync) — both patterns shown.

Public API (mirrors db/provenance.py)
--------------------------------------
  classify_session(user_email) -> dict
  ensure_session_provenance(session_id, user_id, user_email, metadata) -> dict
  get_session_provenance(session_id) -> dict | None
  update_session_provenance(session_id, **kwargs) -> dict | None
  promote_session_for_learning(session_id) -> dict | None
  get_sessions_eligible_for_review(limit) -> list[dict]
  get_provenance_summary(days) -> dict

SQL Filter Strategy (replaces SQLite EXCL_* subquery strings)
--------------------------------------------------------------
In Postgres, exclusion filtering is done via JOIN rather than NOT IN subquery:

  -- SQLite approach (db/provenance.py):
  f"WHERE created_at >= ? {EXCL_METRICS} GROUP BY name"
  -- where EXCL_METRICS = "AND (session_id IS NULL OR session_id NOT IN
  --                       (SELECT session_id FROM session_provenance
  --                        WHERE exclude_from_metrics=1))"

  -- Postgres approach (this module):
  JOIN session_provenance sp USING (session_id)
  WHERE sp.exclude_from_metrics = false
  --   ↑ hits partial index idx_sp_production_metrics — near-free filter

Filter helpers exported for use in analytics queries:

  JOIN_METRICS    -- JOIN + WHERE fragment for metrics queries
  JOIN_CONVERSION -- JOIN + WHERE fragment for conversion queries
  JOIN_COHORTS    -- JOIN + WHERE fragment for cohort queries
  JOIN_LEARNING   -- JOIN + WHERE fragment for learning queries
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

# ── Account lists (same logic as db/provenance.py) ───────────────────────────

from config.admin import get_admin_emails


def _env_emails(var: str) -> frozenset[str]:
    raw = os.getenv(var, "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def get_internal_emails() -> frozenset[str]:
    return get_admin_emails() | _env_emails("NGW_DEV_EMAILS")


def get_expert_emails() -> frozenset[str]:
    return _env_emails("NGW_EXPERT_EMAILS")


# ── SQL filter helpers (Postgres JOIN style) ──────────────────────────────────
#
# Usage in an analytics query:
#
#   sql = f"""
#       SELECT ae.data->>'pattern' AS pattern, COUNT(*) AS cnt
#       FROM analytics_events ae
#       {JOIN_METRICS}
#       WHERE ae.name = 'analysis_complete'
#         AND ae.created_at >= NOW() - INTERVAL '%s days'
#       GROUP BY pattern
#   """
#
# Sessions with no provenance row are treated as production (LEFT JOIN → NULL
# for sp columns, and NULL IS NOT false → included by default).

JOIN_METRICS = """
    LEFT JOIN session_provenance sp USING (session_id)
    WHERE (sp.session_id IS NULL OR sp.exclude_from_metrics = false)
"""

JOIN_CONVERSION = """
    LEFT JOIN session_provenance sp USING (session_id)
    WHERE (sp.session_id IS NULL OR sp.exclude_from_conversion = false)
"""

JOIN_COHORTS = """
    LEFT JOIN session_provenance sp USING (session_id)
    WHERE (sp.session_id IS NULL OR sp.exclude_from_cohorts = false)
"""

JOIN_LEARNING = """
    LEFT JOIN session_provenance sp USING (session_id)
    WHERE (sp.session_id IS NULL OR sp.exclude_from_learning = false)
"""

# ── Classification (pure Python, no DB) ──────────────────────────────────────

def classify_session(user_email: Optional[str]) -> Dict[str, Any]:
    """
    Return provenance classification fields based solely on user email.
    Identical logic to SQLite version — classification is pure Python.
    """
    email = (user_email or "").strip().lower()

    if email and email in get_internal_emails():
        return {
            "session_origin": "internal",
            "exclude_from_learning": True,
            "exclude_from_metrics": True,
            "exclude_from_conversion": True,
            "exclude_from_cohorts": True,
            "eligible_for_reference_review": True,
            "manually_promote_for_learning_review": False,
            "classification_reason": f"internal account ({email})",
        }

    if email and email in get_expert_emails():
        return {
            "session_origin": "expert_review",
            "exclude_from_learning": True,
            "exclude_from_metrics": True,
            "exclude_from_conversion": True,
            "exclude_from_cohorts": True,
            "eligible_for_reference_review": True,
            "manually_promote_for_learning_review": False,
            "classification_reason": f"expert account ({email})",
        }

    return {
        "session_origin": "production",
        "exclude_from_learning": False,
        "exclude_from_metrics": False,
        "exclude_from_conversion": False,
        "exclude_from_cohorts": False,
        "eligible_for_reference_review": False,
        "manually_promote_for_learning_review": False,
        "classification_reason": "production user" if email else "anonymous session",
    }


# ── asyncpg (async) implementation ───────────────────────────────────────────
#
# Use this when your FastAPI route uses `async def` and you have an asyncpg
# connection pool available (e.g., via app.state.pool).
#
# Example wire-in:
#
#   pool = await asyncpg.create_pool(DATABASE_URL)
#   app.state.pool = pool
#
#   async def track(body, request: Request):
#       async with request.app.state.pool.acquire() as conn:
#           await ensure_session_provenance_async(
#               conn, body.session_id, user_id=None, user_email=None
#           )

async def ensure_session_provenance_async(
    conn,                          # asyncpg.Connection
    session_id: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Upsert session provenance record. INSERT ON CONFLICT DO NOTHING — idempotent,
    safe to call on every track event.

    Returns the existing or newly created record as a dict.
    """
    fields = classify_session(user_email)
    import json

    await conn.execute(
        """
        INSERT INTO session_provenance (
            session_id, user_id, user_email,
            session_origin, classification_reason,
            exclude_from_learning, exclude_from_metrics,
            exclude_from_conversion, exclude_from_cohorts,
            eligible_for_reference_review,
            manually_promote_for_learning_review,
            metadata
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (session_id) DO NOTHING
        """,
        session_id, user_id, user_email,
        fields["session_origin"],
        fields["classification_reason"],
        fields["exclude_from_learning"],
        fields["exclude_from_metrics"],
        fields["exclude_from_conversion"],
        fields["exclude_from_cohorts"],
        fields["eligible_for_reference_review"],
        fields["manually_promote_for_learning_review"],
        json.dumps(metadata or {}),
    )

    row = await conn.fetchrow(
        "SELECT * FROM session_provenance WHERE session_id = $1", session_id
    )
    return dict(row) if row else {}


async def get_session_provenance_async(conn, session_id: str) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(
        "SELECT * FROM session_provenance WHERE session_id = $1", session_id
    )
    return dict(row) if row else None


async def update_session_provenance_async(
    conn, session_id: str, **kwargs
) -> Optional[Dict[str, Any]]:
    if not kwargs:
        return await get_session_provenance_async(conn, session_id)

    kwargs["updated_at"] = "now()"
    # Build SET clause with numbered params ($1, $2, ...)
    param_num = 1
    sets = []
    vals = []
    for k, v in kwargs.items():
        if v == "now()":
            sets.append(f"{k} = now()")
        else:
            sets.append(f"{k} = ${param_num}")
            vals.append(v)
            param_num += 1

    vals.append(session_id)
    sql = f"UPDATE session_provenance SET {', '.join(sets)} WHERE session_id = ${param_num}"
    await conn.execute(sql, *vals)
    return await get_session_provenance_async(conn, session_id)


async def promote_session_for_learning_async(
    conn, session_id: str
) -> Optional[Dict[str, Any]]:
    """Clear exclude_from_learning and set manually_promote_for_learning_review."""
    await conn.execute(
        """
        UPDATE session_provenance
        SET exclude_from_learning = false,
            manually_promote_for_learning_review = true,
            updated_at = now()
        WHERE session_id = $1
        """,
        session_id,
    )
    return await get_session_provenance_async(conn, session_id)


async def get_sessions_eligible_for_review_async(
    conn, limit: int = 100
) -> List[Dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT * FROM session_provenance
        WHERE eligible_for_reference_review = true
          AND manually_promote_for_learning_review = false
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def get_provenance_summary_async(conn, days: int = 30) -> Dict[str, Any]:
    """
    Data hygiene summary — matches the response shape of get_provenance_summary()
    in db/provenance.py (SQLite version) for drop-in UI compatibility.
    """
    rows = await conn.fetch(
        """
        SELECT
            session_origin::TEXT,
            COUNT(*)                                                        AS total,
            COUNT(*) FILTER (WHERE exclude_from_metrics     = true)         AS excl_metrics,
            COUNT(*) FILTER (WHERE exclude_from_conversion  = true)         AS excl_conversion,
            COUNT(*) FILTER (WHERE exclude_from_cohorts     = true)         AS excl_cohorts,
            COUNT(*) FILTER (WHERE exclude_from_learning    = true)         AS excl_learning,
            COUNT(*) FILTER (WHERE eligible_for_reference_review = true
                               AND manually_promote_for_learning_review = false) AS eligible_not_promoted,
            COUNT(*) FILTER (WHERE manually_promote_for_learning_review = true) AS manually_promoted
        FROM session_provenance
        WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
        GROUP BY session_origin
        """,
        str(days),
    )

    by_origin: Dict[str, int] = {}
    excl_metrics = excl_conversion = excl_cohorts = excl_learning = 0
    eligible_review = manually_promoted = total_known = 0

    for r in rows:
        origin = r["session_origin"]
        by_origin[origin] = r["total"]
        total_known += r["total"]
        excl_metrics    += r["excl_metrics"]
        excl_conversion += r["excl_conversion"]
        excl_cohorts    += r["excl_cohorts"]
        excl_learning   += r["excl_learning"]
        eligible_review += r["eligible_not_promoted"]
        manually_promoted += r["manually_promoted"]

    return {
        "days": days,
        "total_known_sessions": total_known,
        "by_origin": {
            "production":    by_origin.get("production", 0),
            "internal":      by_origin.get("internal", 0),
            "expert_review": by_origin.get("expert_review", 0),
        },
        "excluded": {
            "from_metrics":    excl_metrics,
            "from_conversion": excl_conversion,
            "from_cohorts":    excl_cohorts,
            "from_learning":   excl_learning,
        },
        "promoted": {
            "eligible_for_review": eligible_review,
            "manually_promoted":   manually_promoted,
        },
        "clean_sessions": total_known - excl_metrics,
    }


# ── psycopg2 (sync) implementation ───────────────────────────────────────────
#
# Use this if you're running sync FastAPI routes with a psycopg2 connection pool.
# The logic is identical — only the driver API differs (cursor vs. row objects).

def ensure_session_provenance_sync(
    conn,                          # psycopg2.extensions.connection
    session_id: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Sync version using psycopg2. ON CONFLICT DO NOTHING — idempotent."""
    import json
    fields = classify_session(user_email)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO session_provenance (
                session_id, user_id, user_email,
                session_origin, classification_reason,
                exclude_from_learning, exclude_from_metrics,
                exclude_from_conversion, exclude_from_cohorts,
                eligible_for_reference_review,
                manually_promote_for_learning_review,
                metadata
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (
                session_id, user_id, user_email,
                fields["session_origin"],
                fields["classification_reason"],
                fields["exclude_from_learning"],
                fields["exclude_from_metrics"],
                fields["exclude_from_conversion"],
                fields["exclude_from_cohorts"],
                fields["eligible_for_reference_review"],
                fields["manually_promote_for_learning_review"],
                json.dumps(metadata or {}),
            ),
        )
        conn.commit()

        cur.execute(
            "SELECT * FROM session_provenance WHERE session_id = %s", (session_id,)
        )
        colnames = [desc[0] for desc in cur.description]
        row = cur.fetchone()

    return dict(zip(colnames, row)) if row else {}
