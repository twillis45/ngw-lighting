"""SQLite database for user accounts and synced data."""
from __future__ import annotations

import json
import logging
import sqlite3

logger = logging.getLogger("ngw.db")
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import os as _os
DATA_DIR: Path = (
    Path(_os.environ.get("NGW_DATA_DIR", "")).resolve()
    if _os.environ.get("NGW_DATA_DIR")
    else Path(__file__).resolve().parent.parent / "data"
)
DB_PATH = DATA_DIR / "ngw_users.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id             TEXT PRIMARY KEY,
                email          TEXT UNIQUE NOT NULL,
                username       TEXT UNIQUE NOT NULL,
                hashed_pw      TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                created_at     REAL NOT NULL,
                updated_at     REAL NOT NULL
            );

            -- Backfill existing rows missing the email_verified column
            -- (ignored if column already exists — executescript is lenient)

            CREATE TABLE IF NOT EXISTS email_verifications (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token      TEXT UNIQUE NOT NULL,
                expires_at REAL NOT NULL,
                used_at    REAL
            );
            CREATE INDEX IF NOT EXISTS idx_email_verif_token ON email_verifications(token);
            CREATE INDEX IF NOT EXISTS idx_email_verif_user  ON email_verifications(user_id);

            CREATE TABLE IF NOT EXISTS magic_link_tokens (
                id         TEXT PRIMARY KEY,
                email      TEXT NOT NULL,
                token      TEXT UNIQUE NOT NULL,
                expires_at REAL NOT NULL,
                used_at    REAL
            );
            CREATE INDEX IF NOT EXISTS idx_magic_link_token ON magic_link_tokens(token);
            CREATE INDEX IF NOT EXISTS idx_magic_link_email ON magic_link_tokens(email);

            CREATE TABLE IF NOT EXISTS user_kits (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kit_json    TEXT NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_kits_user ON user_kits(user_id);

            CREATE TABLE IF NOT EXISTS user_setups (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                tag         TEXT NOT NULL DEFAULT 'personal',
                result_json TEXT NOT NULL,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_setups_user ON user_setups(user_id);

            CREATE TABLE IF NOT EXISTS user_feedback (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                setup_id    TEXT NOT NULL,
                mood        TEXT,
                pattern     TEXT,
                rating      INTEGER,
                comment     TEXT,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_feedback_user ON user_feedback(user_id);

            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pref_key   TEXT NOT NULL,
                pref_value TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, pref_key)
            );

            CREATE TABLE IF NOT EXISTS admin_changelog (
                id          TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id   TEXT NOT NULL,
                action      TEXT NOT NULL,
                diff_json   TEXT NOT NULL,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_changelog_entity ON admin_changelog(entity_type, entity_id);

            CREATE TABLE IF NOT EXISTS image_ground_truth (
                id               TEXT PRIMARY KEY,
                image_path       TEXT NOT NULL,
                expected_mood    TEXT,
                expected_pattern TEXT,
                actual_mood      TEXT,
                actual_pattern   TEXT,
                corrections      TEXT,
                created_at       REAL NOT NULL,
                updated_at       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS image_correction_log (
                id             TEXT PRIMARY KEY,
                image_path     TEXT NOT NULL,
                analysis_id    TEXT,
                corrected_by   TEXT NOT NULL,
                corrected_at   TEXT NOT NULL,
                field_name     TEXT NOT NULL,
                old_value      TEXT,
                new_value      TEXT NOT NULL,
                system_version TEXT,
                source         TEXT DEFAULT 'admin'
            );
            CREATE INDEX IF NOT EXISTS idx_correction_log_path ON image_correction_log (image_path);
            CREATE INDEX IF NOT EXISTS idx_correction_log_analysis ON image_correction_log (analysis_id);

            CREATE TABLE IF NOT EXISTS feedback_aggregates (
                id          TEXT PRIMARY KEY,
                system_id   TEXT NOT NULL,
                mood        TEXT,
                total_count INTEGER DEFAULT 0,
                avg_rating  REAL DEFAULT 0.0,
                updated_at  REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_agg_sys_mood ON feedback_aggregates(system_id, mood);

            CREATE TABLE IF NOT EXISTS gold_set_entries (
                id                  TEXT PRIMARY KEY,
                image_path          TEXT NOT NULL,
                expected_analysis   TEXT,
                notes               TEXT,
                status              TEXT NOT NULL DEFAULT 'draft',
                created_by          TEXT,
                provenance          TEXT,   -- SP-001: source/rights tracking (see SetupFamily provenance values)
                -- setup_family was added by scripts/migrate_setup_family_column.py
                -- and never made it into this CREATE TABLE, so every FRESH database
                -- was one column short and only the migration could fix it. Added
                -- here 2026-09-08; the migration stays for databases that predate it,
                -- since ADD COLUMN is what an existing table needs.
                setup_family    TEXT NULL DEFAULT NULL,
                created_at          REAL NOT NULL,
                updated_at          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gold_set_status ON gold_set_entries(status);

            CREATE TABLE IF NOT EXISTS rule_candidates (
                id                  TEXT PRIMARY KEY,
                title               TEXT NOT NULL,
                description         TEXT NOT NULL,
                rationale           TEXT,
                source_gold_set_id  TEXT,
                source_image_path   TEXT,
                proposed_change     TEXT,
                status              TEXT NOT NULL DEFAULT 'proposed',
                created_by          TEXT,
                created_at          REAL NOT NULL,
                updated_at          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rule_candidates_status ON rule_candidates(status);

            -- ── API key health events ─────────────────────────────────────
            CREATE TABLE IF NOT EXISTS api_health_events (
                id         TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                provider   TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_api_health_created ON api_health_events(created_at DESC);

            -- ── VLM call metrics ──────────────────────────────────────────
            -- One row per VLM API invocation: latency, success, caller context.
            CREATE TABLE IF NOT EXISTS vlm_call_metrics (
                id          TEXT PRIMARY KEY,
                called_at   REAL NOT NULL,
                provider    TEXT NOT NULL,
                model       TEXT,
                latency_ms  REAL,
                ok          INTEGER NOT NULL DEFAULT 1,
                caller      TEXT,
                error       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_vlm_calls_at ON vlm_call_metrics(called_at DESC);

            -- ── VLM cost columns (added post-launch) ─────────────────────
            -- ALTER TABLE is not idempotent in SQLite, handled in _migrate_vlm_cost_columns()

            -- ── Revenue simulation history ────────────────────────────────
            -- One row per completed simulation run.  Keeps full projections +
            -- summary as JSON so the frontend can restore any past run.
            CREATE TABLE IF NOT EXISTS simulation_runs (
                id          TEXT PRIMARY KEY,
                run_at      REAL NOT NULL,
                run_by      TEXT,
                summary     TEXT NOT NULL,
                projections TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sim_runs_run_at ON simulation_runs(run_at DESC);

            -- ── Stripe subscriptions ──────────────────────────────────────
            -- One row per completed Stripe Checkout session.
            -- customer_email is the billing identity; may differ from users.email.
            CREATE TABLE IF NOT EXISTS subscriptions (
                id                     TEXT PRIMARY KEY,
                stripe_session_id      TEXT UNIQUE NOT NULL,
                stripe_customer_id     TEXT,
                stripe_subscription_id TEXT,
                customer_email         TEXT NOT NULL,
                plan                   TEXT NOT NULL DEFAULT 'pro',
                billing_period         TEXT NOT NULL DEFAULT 'monthly',
                status                 TEXT NOT NULL DEFAULT 'active',
                created_at             REAL NOT NULL,
                updated_at             REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sub_email
                ON subscriptions(customer_email);
            CREATE INDEX IF NOT EXISTS idx_sub_stripe_session
                ON subscriptions(stripe_session_id);
            CREATE INDEX IF NOT EXISTS idx_sub_stripe_sub_id
                ON subscriptions(stripe_subscription_id);

            -- ── Per-session analysis counts ───────────────────────────────
            -- Server-side source of truth for free-tier limit enforcement.
            -- Keyed by the browser session_id from flagsStore.getSessionId().
            CREATE TABLE IF NOT EXISTS session_analysis_counts (
                session_id  TEXT PRIMARY KEY,
                count       INTEGER NOT NULL DEFAULT 0,
                updated_at  REAL NOT NULL
            );

            -- ── VLM disagreement records ─────────────────────────────────
            -- Append-only per-analysis record of VLM hint vs resolved value.
            -- Phase 5a: persisted best-effort after each analyze_image() call.
            CREATE TABLE IF NOT EXISTS vlm_disagreements (
                id                     TEXT PRIMARY KEY,
                analysis_id            TEXT NOT NULL,
                field_name             TEXT NOT NULL,
                vlm_value              TEXT NOT NULL,
                vlm_confidence         REAL,
                resolved_value         TEXT,
                resolved_source        TEXT,
                agreement              TEXT,
                disagreement_magnitude REAL,
                pipeline_version       TEXT,
                created_at             REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vlm_disagree_analysis ON vlm_disagreements (analysis_id);
            CREATE INDEX IF NOT EXISTS idx_vlm_disagree_field    ON vlm_disagreements (field_name);
            CREATE INDEX IF NOT EXISTS idx_vlm_disagree_version  ON vlm_disagreements (pipeline_version);

            -- ── Password reset tokens ─────────────────────────────────────
            -- One-time tokens for password reset. Expire after 1 hour.
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id         TEXT PRIMARY KEY,
                email      TEXT NOT NULL,
                token      TEXT UNIQUE NOT NULL,
                expires_at REAL NOT NULL,
                used_at    REAL
            );
            CREATE INDEX IF NOT EXISTS idx_pwd_reset_token ON password_reset_tokens(token);
            CREATE INDEX IF NOT EXISTS idx_pwd_reset_email ON password_reset_tokens(email);

            -- ── Alert state (production alerting) ────────────────────────
            -- Persists alert transitions so they survive server restarts.
            -- One row per rule state change (ok→warn, warn→alert, etc.)
            CREATE TABLE IF NOT EXISTS alert_events (
                id          TEXT PRIMARY KEY,
                rule_id     TEXT NOT NULL,
                prev_state  TEXT NOT NULL,
                new_state   TEXT NOT NULL,
                value       TEXT,
                threshold   TEXT,
                fired_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alert_events_at ON alert_events(fired_at DESC);

            -- ── Build 3A: Analysis replay blobs ──────────────────────────
            -- Stores trimmed JSON snapshots of each AnalysisResult for later
            -- case replay. Only available for analyses run after Build 3A
            -- deployment (2026-04-02). result_json is produced by
            -- analysis_result_to_replay_dict() in engine.orchestrator.
            -- Excludes numpy arrays, cv2 objects, and debug frames.
            CREATE TABLE IF NOT EXISTS analysis_results (
                analysis_id   TEXT PRIMARY KEY,
                image_path    TEXT,
                system_version TEXT,
                result_json   TEXT NOT NULL,
                created_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_results_image_path
                ON analysis_results(image_path);
            CREATE INDEX IF NOT EXISTS idx_analysis_results_created_at
                ON analysis_results(created_at);

            CREATE TABLE IF NOT EXISTS batch_jobs (
                id            TEXT PRIMARY KEY,
                user_email    TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                total_images  INTEGER NOT NULL,
                completed     INTEGER NOT NULL DEFAULT 0,
                results_json  TEXT,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_batch_jobs_user
                ON batch_jobs(user_email);

            CREATE TABLE IF NOT EXISTS reference_library (
                id            TEXT PRIMARY KEY,
                user_email    TEXT NOT NULL,
                name          TEXT NOT NULL,
                category      TEXT DEFAULT 'uncategorized',
                image_path    TEXT NOT NULL,
                analysis_id   TEXT,
                notes         TEXT,
                tags          TEXT,
                created_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reflib_user
                ON reference_library(user_email);

            CREATE TABLE IF NOT EXISTS api_keys (
                id            TEXT PRIMARY KEY,
                user_email    TEXT NOT NULL,
                key_hash      TEXT UNIQUE NOT NULL,
                key_prefix    TEXT NOT NULL,
                name          TEXT DEFAULT 'Default',
                created_at    REAL NOT NULL,
                last_used     REAL,
                revoked       INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_api_keys_user
                ON api_keys(user_email);
            CREATE INDEX IF NOT EXISTS idx_api_keys_hash
                ON api_keys(key_hash);

            CREATE TABLE IF NOT EXISTS teams (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                owner_id      TEXT NOT NULL,
                created_at    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team_members (
                team_id       TEXT NOT NULL,
                user_id       TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'member',
                invited_at    REAL NOT NULL,
                PRIMARY KEY (team_id, user_id)
            );

            -- ── Team sessions (shoot session sharing) ────────────────────
            -- One row per shared cockpit session. Creator shares a short
            -- token URL; assistant opens it to see the setup context.
            -- Sessions auto-expire after 24h. No real-time sync — this is
            -- a persistent "here's what we're shooting" handoff.
            CREATE TABLE IF NOT EXISTS team_sessions (
                id            TEXT PRIMARY KEY,
                share_token   TEXT UNIQUE NOT NULL,
                creator_email TEXT NOT NULL,
                setup_name    TEXT NOT NULL,
                setup_data    TEXT NOT NULL,
                created_at    REAL NOT NULL,
                expires_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_team_sessions_token
                ON team_sessions(share_token);
            CREATE INDEX IF NOT EXISTS idx_team_sessions_expires
                ON team_sessions(expires_at);
        """)
    # Migrate existing users table — add email_verified if missing
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "email_verified" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1")
            # Default existing accounts to verified so they're not locked out

    # Migrate rule_candidates — add source_image_path if missing
    with get_db() as conn:
        rc_cols = [r[1] for r in conn.execute("PRAGMA table_info(rule_candidates)").fetchall()]
        if "source_image_path" not in rc_cols:
            conn.execute("ALTER TABLE rule_candidates ADD COLUMN source_image_path TEXT")

    # Phase 4a — add analysis traceability to user_feedback
    with get_db() as conn:
        fb_cols = [r[1] for r in conn.execute("PRAGMA table_info(user_feedback)").fetchall()]
        if "analysis_id" not in fb_cols:
            conn.execute("ALTER TABLE user_feedback ADD COLUMN analysis_id TEXT")
        if "system_version" not in fb_cols:
            conn.execute("ALTER TABLE user_feedback ADD COLUMN system_version TEXT")

    # Build 3A — add analysis_id to gold_set_entries for replay linkage
    with get_db() as conn:
        gs_cols = [r[1] for r in conn.execute("PRAGMA table_info(gold_set_entries)").fetchall()]
        if "analysis_id" not in gs_cols:
            conn.execute("ALTER TABLE gold_set_entries ADD COLUMN analysis_id TEXT")

    # Logs — add user_email to analysis_results for per-user filtering
    with get_db() as conn:
        ar_cols = [r[1] for r in conn.execute("PRAGMA table_info(analysis_results)").fetchall()]
        if "user_email" not in ar_cols:
            conn.execute("ALTER TABLE analysis_results ADD COLUMN user_email TEXT")

    from db.analytics import init_analytics_table
    init_analytics_table()
    from db.learning import init_learning_tables
    init_learning_tables()
    from db.provenance import init_provenance_table
    init_provenance_table()
    from db.distillation_reviews import init_distillation_reviews_table
    init_distillation_reviews_table()

    # Migrate VLM cost columns (idempotent)
    with get_db() as conn:
        vlm_cols = [r[1] for r in conn.execute("PRAGMA table_info(vlm_call_metrics)").fetchall()]
        if "input_tokens" not in vlm_cols:
            conn.execute("ALTER TABLE vlm_call_metrics ADD COLUMN input_tokens INTEGER")
        if "output_tokens" not in vlm_cols:
            conn.execute("ALTER TABLE vlm_call_metrics ADD COLUMN output_tokens INTEGER")
        if "cost_usd" not in vlm_cols:
            conn.execute("ALTER TABLE vlm_call_metrics ADD COLUMN cost_usd REAL")

    # Migrate user_setups — add sharing columns
    with get_db() as conn:
        setup_cols = [r[1] for r in conn.execute("PRAGMA table_info(user_setups)").fetchall()]
        if "shared" not in setup_cols:
            conn.execute("ALTER TABLE user_setups ADD COLUMN shared INTEGER DEFAULT 0")
        if "share_token" not in setup_cols:
            conn.execute("ALTER TABLE user_setups ADD COLUMN share_token TEXT")


# ── User CRUD ──────────────────────────────────────────────

def create_user(email: str, username: str, hashed_pw: str) -> Dict[str, Any]:
    uid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, username, hashed_pw, email_verified, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
            (uid, email.lower(), username, hashed_pw, now, now),
        )
    logger.info("[db] create_user id=%s email=%s", uid, email.lower())
    return {"id": uid, "email": email.lower(), "username": username, "email_verified": False}


# ── Email Verification ─────────────────────────────────────

def create_verification_token(user_id: str, expires_in: int = 86400) -> str:
    """Create a new verification token (valid for expires_in seconds, default 24h).
    Returns the token string."""
    import secrets
    token = secrets.token_urlsafe(32)
    vid = uuid.uuid4().hex
    expires_at = time.time() + expires_in
    with get_db() as conn:
        # Invalidate any existing unused tokens for this user
        conn.execute(
            "DELETE FROM email_verifications WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (?,?,?,?)",
            (vid, user_id, token, expires_at),
        )
    return token


def consume_verification_token(token: str) -> Optional[Dict[str, Any]]:
    """Mark token as used and set user.email_verified=1.
    Returns updated user dict or None if token is invalid/expired."""
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM email_verifications WHERE token = ? AND used_at IS NULL AND expires_at > ?",
            (token, now),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE email_verifications SET used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.execute(
            "UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?",
            (now, row["user_id"]),
        )
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    return dict(user) if user else None


def mark_email_verified(user_id: str) -> None:
    """Directly mark a user's email as verified (admin use / testing)."""
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?",
            (now, user_id),
        )


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    return dict(row) if row else None


def get_or_create_passwordless_user(email: str, username: str | None = None) -> Dict[str, Any]:
    """Get an existing user by email or create one with no password (Google / magic-link)."""
    user = get_user_by_email(email)
    if user:
        return user
    uid = uuid.uuid4().hex
    now = time.time()
    uname = (username or email.split("@")[0])[:32]
    # Ensure username is unique
    base = uname
    suffix = 0
    while True:
        with get_db() as conn:
            clash = conn.execute("SELECT id FROM users WHERE username = ?", (uname,)).fetchone()
        if not clash:
            break
        suffix += 1
        uname = f"{base}{suffix}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, email, username, hashed_pw, email_verified, created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
            (uid, email.lower(), uname, "__passwordless__", now, now),
        )
    return {"id": uid, "email": email.lower(), "username": uname, "email_verified": True}


# ── Magic Link Tokens ───────────────────────────────────────

def create_magic_link_token(email: str, expires_in: int = 900) -> str:
    """Create a one-time magic link token for the given email (default 15 min)."""
    import secrets
    token = secrets.token_urlsafe(32)
    tid = uuid.uuid4().hex
    expires_at = time.time() + expires_in
    with get_db() as conn:
        # Invalidate existing unused tokens for this email
        conn.execute(
            "DELETE FROM magic_link_tokens WHERE email = ? AND used_at IS NULL",
            (email.lower(),),
        )
        conn.execute(
            "INSERT INTO magic_link_tokens (id, email, token, expires_at) VALUES (?,?,?,?)",
            (tid, email.lower(), token, expires_at),
        )
    return token


def consume_magic_link_token(token: str) -> Optional[str]:
    """Validate and consume a magic link token. Returns the email, or None if invalid/expired."""
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM magic_link_tokens WHERE token = ? AND used_at IS NULL AND expires_at > ?",
            (token, now),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE magic_link_tokens SET used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
    return row["email"]


# ── Password Reset Tokens ───────────────────────────────────

def create_password_reset_token(email: str, expires_in: int = 3600) -> str:
    """Create a one-time password-reset token (default 1 hour)."""
    import secrets
    token = secrets.token_urlsafe(32)
    tid = uuid.uuid4().hex
    expires_at = time.time() + expires_in
    with get_db() as conn:
        # Invalidate existing unused tokens for this email
        conn.execute(
            "DELETE FROM password_reset_tokens WHERE email = ? AND used_at IS NULL",
            (email.lower(),),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (id, email, token, expires_at) VALUES (?,?,?,?)",
            (tid, email.lower(), token, expires_at),
        )
    return token


def consume_password_reset_token(token: str) -> Optional[str]:
    """Validate and consume a reset token. Returns email, or None if invalid/expired."""
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token = ? AND used_at IS NULL AND expires_at > ?",
            (token, now),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
    return row["email"]


def update_user_password(user_id: str, hashed_pw: str) -> None:
    """Update a user's hashed password."""
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET hashed_pw = ?, updated_at = ? WHERE id = ?",
            (hashed_pw, now, user_id),
        )
    logger.info("[db] update_user_password user_id=%s", user_id)


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def delete_user_account(user_id: str, email: str) -> None:
    """Permanently delete a user and all their owned data.

    Cascading ON DELETE in the schema handles child rows for tables that use
    REFERENCES users(id) ON DELETE CASCADE.  Tables keyed by email (subscriptions,
    password_reset_tokens) or without a FK constraint are cleaned up explicitly.
    """
    with get_db() as conn:
        # Email-keyed tables (safe — ignores missing tables)
        for tbl, col in [
            ("subscriptions", "customer_email"),
            ("analysis_results", "user_email"),
            ("batch_jobs", "user_email"),
            ("reference_library", "user_email"),
            ("api_keys", "user_email"),
        ]:
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE {col} = ?", (email,))
            except Exception:
                pass  # table may not exist yet
        # Session-keyed (session_analysis_counts uses "user:<id>" format)
        try:
            conn.execute("DELETE FROM session_analysis_counts WHERE session_id = ?", (f"user:{user_id}",))
        except Exception:
            pass
        # Token tables (may or may not exist as separate tables)
        for tbl in ("password_reset_tokens", "magic_link_tokens", "email_verifications"):
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (user_id,))
            except Exception:
                try:
                    conn.execute(f"DELETE FROM {tbl} WHERE email = ?", (email,))
                except Exception:
                    pass
        # user_id-keyed tables not covered by FK cascade
        for tbl in ("user_kits", "user_setups", "user_feedback", "user_preferences", "team_members"):
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (user_id,))
            except Exception:
                pass
        # Finally remove the account itself
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    logger.info("[db] delete_user_account user_id=%s email=%s", user_id, email)


# ── Subscription CRUD ──────────────────────────────────────

def create_subscription(
    stripe_session_id: str,
    customer_email: str,
    plan: str = "pro",
    billing_period: str = "monthly",
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a completed Stripe Checkout session as a subscription record."""
    sub_id = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO subscriptions
               (id, stripe_session_id, stripe_customer_id, stripe_subscription_id,
                customer_email, plan, billing_period, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(stripe_session_id) DO NOTHING""",
            (
                sub_id, stripe_session_id, stripe_customer_id, stripe_subscription_id,
                customer_email.lower(), plan, billing_period, "active", now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE stripe_session_id = ?",
            (stripe_session_id,),
        ).fetchone()
    return dict(row) if row else {}


def get_active_subscription(customer_email: str) -> Optional[Dict[str, Any]]:
    """Return the most recent active subscription for an email, or None."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM subscriptions
               WHERE customer_email = ? AND status = 'active'
               ORDER BY created_at DESC LIMIT 1""",
            (customer_email.lower(),),
        ).fetchone()
    return dict(row) if row else None


def get_subscription_by_stripe_session(stripe_session_id: str) -> Optional[Dict[str, Any]]:
    """Return the subscription row for a given Stripe checkout session ID, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE stripe_session_id = ?",
            (stripe_session_id,),
        ).fetchone()
    return dict(row) if row else None


def cancel_subscription_by_stripe_id(stripe_subscription_id: str) -> bool:
    """Mark a subscription as cancelled by its Stripe subscription ID.

    Called when Stripe fires customer.subscription.deleted.
    Returns True if a row was updated, False if no matching row found.
    """
    import time as _time
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE subscriptions
               SET status = 'cancelled', updated_at = ?
               WHERE stripe_subscription_id = ? AND status = 'active'""",
            (_time.time(), stripe_subscription_id),
        )
    return cursor.rowcount > 0


# ── Analysis Count CRUD ────────────────────────────────────

def _analysis_key(session_id: str, user_id: Optional[str] = None) -> str:
    """Return the canonical key for analysis counting.

    Authenticated users get a ``user:<id>`` key so counts are portable across
    devices and sessions.  Anonymous users fall back to ``session_id``.
    """
    return f"user:{user_id}" if user_id else session_id


def increment_analysis_count(
    session_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Increment the server-side analysis count for a session or user.

    When *user_id* is provided the count is keyed by ``user:<user_id>`` so it
    follows the user across browsers/devices.  Falls back to *session_id* for
    anonymous callers.

    Returns ``{'count': int, 'updated_at': float}``.
    """
    key = _analysis_key(session_id, user_id)
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO session_analysis_counts (session_id, count, updated_at)
               VALUES (?, 1, ?)
               ON CONFLICT(session_id) DO UPDATE
               SET count = count + 1, updated_at = excluded.updated_at""",
            (key, now),
        )
        row = conn.execute(
            "SELECT count, updated_at FROM session_analysis_counts WHERE session_id = ?",
            (key,),
        ).fetchone()
    return {"count": row["count"], "updated_at": row["updated_at"]}


def get_analysis_count(
    session_id: str,
    user_id: Optional[str] = None,
) -> int:
    """Return the current analysis count for a session or user (0 if not found)."""
    key = _analysis_key(session_id, user_id)
    with get_db() as conn:
        row = conn.execute(
            "SELECT count FROM session_analysis_counts WHERE session_id = ?",
            (key,),
        ).fetchone()
    return row["count"] if row else 0


# ── Kit CRUD ───────────────────────────────────────────────

def save_user_kit(user_id: str, kit: Dict[str, Any]) -> Dict[str, Any]:
    kid = uuid.uuid4().hex
    now = time.time()
    kit_json = json.dumps(kit)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO user_kits (id, user_id, kit_json, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET kit_json=excluded.kit_json, updated_at=excluded.updated_at""",
            (kid, user_id, kit_json, now),
        )
    return {"user_id": user_id, "kit": kit, "updated_at": now}


def get_user_kit(user_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_kits WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "kit": json.loads(row["kit_json"]), "updated_at": row["updated_at"]}


def delete_user_kit(user_id: str) -> bool:
    with get_db() as conn:
        c = conn.execute("DELETE FROM user_kits WHERE user_id = ?", (user_id,))
    return c.rowcount > 0


# ── Setups CRUD ────────────────────────────────────────────

def save_user_setup(user_id: str, name: str, tag: str, result: Dict[str, Any]) -> Dict[str, Any]:
    sid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_setups (id, user_id, name, tag, result_json, created_at) VALUES (?,?,?,?,?,?)",
            (sid, user_id, name, tag, json.dumps(result), now),
        )
    return {"id": sid, "name": name, "tag": tag, "created_at": now}


def get_user_setups(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM user_setups WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "tag": r["tag"],
         "result": json.loads(r["result_json"]), "created_at": r["created_at"]}
        for r in rows
    ]


def delete_user_setup(user_id: str, setup_id: str) -> bool:
    with get_db() as conn:
        c = conn.execute("DELETE FROM user_setups WHERE id = ? AND user_id = ?", (setup_id, user_id))
    return c.rowcount > 0


# ── Feedback CRUD ──────────────────────────────────────────

def save_user_feedback(user_id: str, setup_id: str, mood: str, pattern: str,
                       rating: int, comment: str,
                       analysis_id: Optional[str] = None,
                       system_version: Optional[str] = None) -> Dict[str, Any]:
    fid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_feedback (id, user_id, setup_id, mood, pattern, rating, comment, created_at, analysis_id, system_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (fid, user_id, setup_id, mood, pattern, rating, comment, now, analysis_id, system_version),
        )
    return {"id": fid, "setup_id": setup_id, "rating": rating, "created_at": now}


def get_user_feedback(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM user_feedback WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── User Preferences ──────────────────────────────────────
# Generic key-value store for per-user UI preferences (e.g. tab order).
# Values are JSON-encoded so any serialisable type can be stored.

def save_user_preference(user_id: str, key: str, value: Any) -> None:
    """Upsert a single preference value for a user."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO user_preferences (user_id, pref_key, pref_value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, pref_key)
               DO UPDATE SET pref_value = excluded.pref_value,
                             updated_at  = excluded.updated_at""",
            (user_id, key, json.dumps(value), time.time()),
        )


def get_user_preference(user_id: str, key: str) -> Optional[Any]:
    """Return a single preference value, or None if not set."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT pref_value FROM user_preferences WHERE user_id = ? AND pref_key = ?",
            (user_id, key),
        ).fetchone()
    return json.loads(row["pref_value"]) if row else None


def get_all_user_preferences(user_id: str) -> Dict[str, Any]:
    """Return all preferences for a user as a plain dict."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT pref_key, pref_value FROM user_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {r["pref_key"]: json.loads(r["pref_value"]) for r in rows}


# ── Alert Events ──────────────────────────────────────────

def log_alert_event(rule_id: str, prev_state: str, new_state: str,
                    value: str = None, threshold: str = None) -> Dict[str, Any]:
    """Persist an alert state transition."""
    eid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO alert_events (id, rule_id, prev_state, new_state, value, threshold, fired_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (eid, rule_id, prev_state, new_state, value, threshold, now),
        )
    return {"id": eid, "rule_id": rule_id, "prev_state": prev_state,
            "new_state": new_state, "fired_at": now}


def get_alert_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent alert events, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_events ORDER BY fired_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Admin Changelog ───────────────────────────────────────

def log_admin_change(entity_type: str, entity_id: str, action: str, diff: Dict[str, Any]) -> Dict[str, Any]:
    cid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO admin_changelog (id, entity_type, entity_id, action, diff_json, created_at) VALUES (?,?,?,?,?,?)",
            (cid, entity_type, entity_id, action, json.dumps(diff), now),
        )
    return {"id": cid, "entity_type": entity_type, "entity_id": entity_id, "action": action, "created_at": now}


def get_admin_changelog(limit: int = 50) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM admin_changelog ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {**dict(r), "diff": json.loads(r["diff_json"])}
        for r in rows
    ]


# ── Image Ground Truth ────────────────────────────────────

def save_image_ground_truth(
    image_path: str,
    expected_mood: Optional[str] = None,
    expected_pattern: Optional[str] = None,
    actual_mood: Optional[str] = None,
    actual_pattern: Optional[str] = None,
    corrections: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    gid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO image_ground_truth
               (id, image_path, expected_mood, expected_pattern, actual_mood, actual_pattern, corrections, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (gid, image_path, expected_mood, expected_pattern, actual_mood, actual_pattern,
             json.dumps(corrections) if corrections else None, now, now),
        )
    return {"id": gid, "image_path": image_path, "created_at": now}


def log_image_correction(
    image_path: str,
    corrected_by: str,
    field_name: str,
    new_value: str,
    old_value: Optional[str] = None,
    analysis_id: Optional[str] = None,
    system_version: Optional[str] = None,
    source: str = "admin",
    corrected_at: Optional[str] = None,
) -> str:
    """Append one row to image_correction_log. Returns the new log entry id."""
    log_id = uuid.uuid4().hex
    ts = corrected_at or str(time.time())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO image_correction_log
               (id, image_path, analysis_id, corrected_by, corrected_at,
                field_name, old_value, new_value, system_version, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (log_id, image_path, analysis_id, corrected_by, ts,
             field_name, old_value, new_value, system_version, source),
        )
    return log_id


def save_truth_and_log_corrections(
    image_path: str,
    expected_mood: Optional[str],
    expected_pattern: Optional[str],
    actual_mood: Optional[str],
    actual_pattern: Optional[str],
    corrections: Optional[Dict[str, Any]],
    correction_log_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Insert image ground truth and append correction-log rows in a single transaction.

    correction_log_entries is a list of dicts with keys:
        corrected_by (str), corrected_at (str), field_name (str),
        new_value (str), old_value (str|None), analysis_id (str|None),
        system_version (str|None), source (str, default 'admin')
    """
    gid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO image_ground_truth
               (id, image_path, expected_mood, expected_pattern, actual_mood, actual_pattern, corrections, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (gid, image_path, expected_mood, expected_pattern, actual_mood, actual_pattern,
             json.dumps(corrections) if corrections else None, now, now),
        )
        for entry in correction_log_entries:
            log_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO image_correction_log
                   (id, image_path, analysis_id, corrected_by, corrected_at,
                    field_name, old_value, new_value, system_version, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (log_id, image_path,
                 entry.get("analysis_id"),
                 entry["corrected_by"],
                 entry["corrected_at"],
                 entry["field_name"],
                 entry.get("old_value"),
                 entry["new_value"],
                 entry.get("system_version"),
                 entry.get("source", "admin")),
            )
    return {"id": gid, "image_path": image_path, "created_at": now}


def get_image_ground_truths(limit: int = 100) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM image_ground_truth ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("corrections"):
            d["corrections"] = json.loads(d["corrections"])
        results.append(d)
    return results


# ── Feedback Aggregates ───────────────────────────────────

def upsert_feedback_aggregate(system_id: str, mood: str, rating: float) -> None:
    now = time.time()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, total_count, avg_rating FROM feedback_aggregates WHERE system_id = ? AND mood = ?",
            (system_id, mood),
        ).fetchone()
        if existing:
            new_count = existing["total_count"] + 1
            new_avg = (existing["avg_rating"] * existing["total_count"] + rating) / new_count
            conn.execute(
                "UPDATE feedback_aggregates SET total_count = ?, avg_rating = ?, updated_at = ? WHERE id = ?",
                (new_count, new_avg, now, existing["id"]),
            )
        else:
            aid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO feedback_aggregates (id, system_id, mood, total_count, avg_rating, updated_at) VALUES (?,?,?,?,?,?)",
                (aid, system_id, mood, 1, float(rating), now),
            )


def get_feedback_aggregates() -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback_aggregates ORDER BY system_id, mood"
        ).fetchall()
    return [dict(r) for r in rows]


def refresh_feedback_aggregates() -> int:
    """Recompute all feedback aggregates from user_feedback table."""
    with get_db() as conn:
        conn.execute("DELETE FROM feedback_aggregates")
        rows = conn.execute(
            """SELECT setup_id, mood, COUNT(*) as cnt, AVG(rating) as avg_r
               FROM user_feedback
               WHERE rating IS NOT NULL
               GROUP BY setup_id, mood"""
        ).fetchall()
        now = time.time()
        count = 0
        for r in rows:
            aid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO feedback_aggregates (id, system_id, mood, total_count, avg_rating, updated_at) VALUES (?,?,?,?,?,?)",
                (aid, r["setup_id"], r["mood"], r["cnt"], r["avg_r"], now),
            )
            count += 1
    return count


# ── Gold Set Entries CRUD ─────────────────────────────────

_GOLD_SET_VALID_STATUSES = {"draft", "approved", "archived", "rejected"}
_GOLD_SET_VALID_PROVENANCE = {
    "photographer_original",  # image taken by the contributing photographer
    "licensed_stock",         # licensed from stock library
    "public_domain",          # explicitly public domain
    "creative_commons",       # CC-licensed with appropriate terms
    "fair_use_reference",     # used for reference/research under fair use
    "synthetic",              # AI-generated or rendered
    "internal_test",          # internal test asset, not for redistribution
    "unknown",                # provenance not recorded
}


def create_gold_set_entry(
    image_path: str,
    expected_analysis: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    status: str = "draft",
    created_by: Optional[str] = None,
    setup_family: Optional[str] = None,
    provenance: Optional[str] = None,
) -> Dict[str, Any]:
    # TR-002: approved status requires created_by
    if status == "approved" and not created_by:
        raise ValueError("TR-002: 'approved' status requires created_by to be set.")
    # Validate status
    if status not in _GOLD_SET_VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(_GOLD_SET_VALID_STATUSES)}")
    gid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO gold_set_entries
               (id, image_path, expected_analysis, notes, status, created_by,
                setup_family, provenance, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (gid, image_path,
             json.dumps(expected_analysis) if expected_analysis else None,
             notes, status, created_by,
             setup_family, provenance, now, now),
        )
    return {
        "id": gid, "image_path": image_path,
        "expected_analysis": expected_analysis,
        "notes": notes, "status": status,
        "created_by": created_by,
        "setup_family": setup_family,
        "provenance": provenance,
        "created_at": now, "updated_at": now,
    }


def get_gold_set_entries(
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM gold_set_entries WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM gold_set_entries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("expected_analysis"):
            d["expected_analysis"] = json.loads(d["expected_analysis"])
        results.append(d)
    return results


def get_gold_set_entry(entry_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM gold_set_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("expected_analysis"):
        d["expected_analysis"] = json.loads(d["expected_analysis"])
    return d


def update_gold_set_entry(entry_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    # TR-002: 'approved' status requires created_by on the existing entry
    if kwargs.get("status") == "approved":
        if kwargs.get("status") not in _GOLD_SET_VALID_STATUSES:
            raise ValueError(f"Invalid status. Must be one of: {sorted(_GOLD_SET_VALID_STATUSES)}")
        existing = get_gold_set_entry(entry_id)
        if existing and not existing.get("created_by"):
            raise ValueError(
                f"TR-002: Cannot approve gold set entry '{entry_id}' — "
                "created_by is not set. Assign an author before approving."
            )
    elif "status" in kwargs and kwargs["status"] not in _GOLD_SET_VALID_STATUSES:
        raise ValueError(f"Invalid status '{kwargs['status']}'. Must be one of: {sorted(_GOLD_SET_VALID_STATUSES)}")

    now = time.time()
    sets = ["updated_at = ?"]
    vals: list = [now]
    for key in ("expected_analysis", "notes", "status", "setup_family", "provenance"):
        if key in kwargs and kwargs[key] is not None:
            v = kwargs[key]
            if key == "expected_analysis" and isinstance(v, dict):
                v = json.dumps(v)
            sets.append(f"{key} = ?")
            vals.append(v)
    vals.append(entry_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE gold_set_entries SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
    return get_gold_set_entry(entry_id)


def delete_gold_set_entry(entry_id: str) -> bool:
    with get_db() as conn:
        c = conn.execute("DELETE FROM gold_set_entries WHERE id = ?", (entry_id,))
    return c.rowcount > 0


# ── Rule Candidates CRUD ─────────────────────────────────

def create_rule_candidate(
    title: str,
    description: str,
    rationale: Optional[str] = None,
    source_gold_set_id: Optional[str] = None,
    source_image_path: Optional[str] = None,
    proposed_change: Optional[Dict[str, Any]] = None,
    status: str = "proposed",
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    cid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO rule_candidates
               (id, title, description, rationale, source_gold_set_id, source_image_path, proposed_change, status, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, title, description, rationale, source_gold_set_id, source_image_path,
             json.dumps(proposed_change) if proposed_change else None,
             status, created_by, now, now),
        )
    return {
        "id": cid, "title": title, "description": description,
        "rationale": rationale, "source_gold_set_id": source_gold_set_id,
        "source_image_path": source_image_path,
        "proposed_change": proposed_change, "status": status,
        "created_by": created_by,
        "created_at": now, "updated_at": now,
    }


def get_rule_candidates(
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    # Left-join with gold_set_entries; direct source_image_path column wins, else use gold set image
    base_sql = """
        SELECT rc.*,
               COALESCE(rc.source_image_path, gs.image_path) AS source_image_path
        FROM rule_candidates rc
        LEFT JOIN gold_set_entries gs ON rc.source_gold_set_id = gs.id
        {where}
        ORDER BY rc.created_at DESC
        LIMIT ?
    """
    with get_db() as conn:
        if status:
            rows = conn.execute(
                base_sql.format(where="WHERE rc.status = ?"), (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                base_sql.format(where=""), (limit,)
            ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("proposed_change"):
            d["proposed_change"] = json.loads(d["proposed_change"])
        results.append(d)
    return results


def get_rule_candidate(candidate_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT rc.*, gs.image_path AS source_image_path
               FROM rule_candidates rc
               LEFT JOIN gold_set_entries gs ON rc.source_gold_set_id = gs.id
               WHERE rc.id = ?""",
            (candidate_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("proposed_change"):
        d["proposed_change"] = json.loads(d["proposed_change"])
    return d


def update_rule_candidate(candidate_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    now = time.time()
    sets = ["updated_at = ?"]
    vals: list = [now]
    for key in ("title", "description", "rationale", "source_image_path", "proposed_change", "status"):
        if key in kwargs:
            v = kwargs[key]
            if key == "proposed_change" and isinstance(v, dict):
                v = json.dumps(v)
            sets.append(f"{key} = ?")
            vals.append(v)
    vals.append(candidate_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE rule_candidates SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
    return get_rule_candidate(candidate_id)


def delete_rule_candidate(candidate_id: str) -> bool:
    with get_db() as conn:
        c = conn.execute("DELETE FROM rule_candidates WHERE id = ?", (candidate_id,))
    return c.rowcount > 0


# ── Simulation run history ────────────────────────────────────────────────────

def save_simulation_run(
    summary: dict,
    projections: list,
    run_by: str = None,
) -> dict:
    """Persist a completed simulation run and return it with its id + run_at."""
    rid  = uuid.uuid4().hex
    now  = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO simulation_runs (id, run_at, run_by, summary, projections) VALUES (?,?,?,?,?)",
            (rid, now, run_by, json.dumps(summary), json.dumps(projections)),
        )
    return {"id": rid, "run_at": now, "run_by": run_by, "summary": summary, "projections": projections}


def list_simulation_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """Return the most recent simulation runs, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, run_at, run_by, summary, projections FROM simulation_runs ORDER BY run_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["summary"]     = json.loads(d["summary"])
        d["projections"] = json.loads(d["projections"])
        out.append(d)
    return out


def get_latest_simulation_run() -> Optional[Dict[str, Any]]:
    """Return the single most recent simulation run, or None."""
    runs = list_simulation_runs(limit=1)
    return runs[0] if runs else None


# ── API key health events ─────────────────────────────────────────────────────

def log_api_health_event(provider: str, event_type: str, detail: str = None) -> None:
    """Log an API key health event (401_error, probe_ok, probe_fail, startup_ok, startup_fail)."""
    eid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO api_health_events (id, created_at, provider, event_type, detail) VALUES (?,?,?,?,?)",
            (eid, now, provider, event_type, detail),
        )


def get_api_health_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent API health events, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM api_health_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_api_health(provider: str) -> Optional[Dict[str, Any]]:
    """Return the most recent health event for a given provider."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM api_health_events WHERE provider = ? ORDER BY created_at DESC LIMIT 1",
            (provider,),
        ).fetchone()
    return dict(row) if row else None


# ── VLM call metrics ──────────────────────────────────────────────────────────

def log_vlm_call(provider: str, model: str, latency_ms: float, ok: bool,
                 caller: str = None, error: str = None,
                 input_tokens: int = None, output_tokens: int = None,
                 cost_usd: float = None) -> None:
    """Record a single VLM API call with timing, outcome, and cost."""
    cid = uuid.uuid4().hex
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO vlm_call_metrics (id, called_at, provider, model, latency_ms, ok, caller, error, input_tokens, output_tokens, cost_usd) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, now, provider, model, latency_ms, 1 if ok else 0, caller, error, input_tokens, output_tokens, cost_usd),
        )


def get_vlm_call_stats(hours: int = 24) -> Dict[str, Any]:
    """Return aggregate VLM call stats for the last N hours."""
    cutoff = time.time() - hours * 3600
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM vlm_call_metrics WHERE called_at > ? ORDER BY called_at DESC",
            (cutoff,),
        ).fetchall()

    calls = [dict(r) for r in rows]
    total = len(calls)
    ok_count = sum(1 for c in calls if c["ok"])
    err_count = total - ok_count
    latencies = [c["latency_ms"] for c in calls if c["latency_ms"] is not None and c["ok"]]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else None
    p95_latency = round(sorted(latencies)[int((len(latencies) - 1) * 0.95)], 1) if len(latencies) >= 5 else None

    # Bucketed timeline for sparkline.
    # ≤48h → one bar per hour (up to 48 bars).
    # >48h (7d) → one bar per day (up to 7 bars).
    now = time.time()
    if hours <= 48:
        bucket_secs = 3600       # 1 hour per bar
        n_buckets   = hours
    else:
        bucket_secs = 86400      # 1 day per bar
        n_buckets   = hours // 24

    buckets: Dict[int, int] = {}
    for c in calls:
        idx = int((now - c["called_at"]) // bucket_secs)
        buckets[idx] = buckets.get(idx, 0) + 1
    # hours_ago stores the bucket start in hours for tooltip consistency
    hourly = [
        {"hours_ago": h * (bucket_secs // 3600), "count": buckets.get(h, 0)}
        for h in range(n_buckets)
    ]

    # Cost aggregation
    total_input  = sum(c.get("input_tokens") or 0 for c in calls)
    total_output = sum(c.get("output_tokens") or 0 for c in calls)
    total_cost   = sum(c.get("cost_usd") or 0.0 for c in calls)

    # Cost per day (for trend chart)
    cost_buckets: Dict[int, float] = {}
    for c in calls:
        day_idx = int((now - c["called_at"]) // 86400)
        cost_buckets[day_idx] = cost_buckets.get(day_idx, 0.0) + (c.get("cost_usd") or 0.0)
    n_days = max(hours // 24, 1)
    daily_cost = [
        {"days_ago": d, "cost_usd": round(cost_buckets.get(d, 0.0), 4)}
        for d in range(n_days)
    ]

    return {
        "window_hours":   hours,
        "total":          total,
        "ok":             ok_count,
        "errors":         err_count,
        "error_rate":     round(err_count / total, 3) if total else 0.0,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "hourly":         hourly,
        "recent":         calls[:10],
        "total_input_tokens":  total_input,
        "total_output_tokens": total_output,
        "total_cost_usd":      round(total_cost, 4),
        "daily_cost":          daily_cost,
    }


# ── VLM Disagreement Records ──────────────────────────────────────────────────

def save_vlm_disagreements(analysis_id: str, records: list) -> None:
    """Persist a list of VLMDisagreementRecord instances for one analysis run.

    Best-effort only — callers must wrap in try/except.  Accepts either
    VLMDisagreementRecord dataclass instances or plain dicts.
    """
    if not records:
        return
    now = time.time()
    with get_db() as conn:
        for rec in records:
            if hasattr(rec, "__dict__"):
                r = rec.__dict__
            else:
                r = dict(rec)
            conn.execute(
                """INSERT OR IGNORE INTO vlm_disagreements
                   (id, analysis_id, field_name, vlm_value, vlm_confidence,
                    resolved_value, resolved_source, agreement,
                    disagreement_magnitude, pipeline_version, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex,
                    analysis_id,
                    r.get("field_name", ""),
                    r.get("vlm_value", ""),
                    r.get("vlm_confidence"),
                    r.get("resolved_value"),
                    r.get("resolved_source"),
                    r.get("agreement"),
                    r.get("disagreement_magnitude"),
                    r.get("pipeline_version"),
                    now,
                ),
            )


def get_vlm_disagreements(
    *,
    analysis_id: Optional[str] = None,
    pipeline_version: Optional[str] = None,
    field_name: Optional[str] = None,
    agreement: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read VLM disagreement records with optional filters."""
    clauses: list = []
    params: list = []
    if analysis_id:
        clauses.append("analysis_id = ?")
        params.append(analysis_id)
    if pipeline_version:
        clauses.append("pipeline_version = ?")
        params.append(pipeline_version)
    if field_name:
        clauses.append("field_name = ?")
        params.append(field_name)
    if agreement:
        clauses.append("agreement = ?")
        params.append(agreement)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM vlm_disagreements {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ── Image Correction Log (read) ───────────────────────────────────────────────

def get_image_correction_log(
    *,
    image_path: Optional[str] = None,
    field_name: Optional[str] = None,
    analysis_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read image correction log entries with optional filters."""
    clauses: list = []
    params: list = []
    if image_path:
        clauses.append("image_path = ?")
        params.append(image_path)
    if field_name:
        clauses.append("field_name = ?")
        params.append(field_name)
    if analysis_id:
        clauses.append("analysis_id = ?")
        params.append(analysis_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM image_correction_log {where} ORDER BY corrected_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ── Feedback Calibration ──────────────────────────────────────────────────────

def get_feedback_calibration(
    *,
    system_version: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Per-pattern feedback aggregates for calibration diagnostics.

    Filters to rows with analysis_id IS NOT NULL (traceable feedback only).
    Optionally filters by system_version.
    Returns diagnostic aggregates only — not used for automatic tuning.
    """
    clauses = ["analysis_id IS NOT NULL", "pattern IS NOT NULL"]
    params: list = []
    if system_version:
        clauses.append("system_version = ?")
        params.append(system_version)
    where = "WHERE " + " AND ".join(clauses)
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT
                    pattern,
                    COUNT(*)                            AS feedback_count,
                    ROUND(AVG(rating), 3)               AS avg_rating,
                    SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS high_rating_count,
                    SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS low_rating_count,
                    COUNT(DISTINCT analysis_id)         AS distinct_analyses,
                    COUNT(DISTINCT system_version)      AS distinct_versions
               FROM user_feedback
               {where}
               GROUP BY pattern
               ORDER BY feedback_count DESC
               LIMIT ?""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ── Session Log / Analysis History ───────────────────────────────────────────

def get_user_analyses(
    user_email: str,
    limit: int = 20,
    offset: int = 0,
    pattern: str | None = None,
    date_from: float | None = None,
    date_to: float | None = None,
) -> tuple[list[dict], int]:
    """Return paginated list of a user's past analyses + total count."""
    import json as _json
    where = ["user_email = ?"]
    params: list = [user_email.lower()]
    if pattern:
        where.append("json_extract(result_json, '$.authoritative_pattern') = ?")
        params.append(pattern)
    if date_from is not None:
        where.append("created_at >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("created_at <= ?")
        params.append(date_to)
    where_clause = " AND ".join(where)

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM analysis_results WHERE {where_clause}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT analysis_id, image_path, system_version, created_at,
                       json_extract(result_json, '$.authoritative_pattern') AS pattern,
                       json_extract(result_json, '$.pattern_confidence') AS confidence
                FROM analysis_results
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

    return [dict(r) for r in rows], total


def get_analysis_by_id(analysis_id: str, user_email: str | None = None) -> dict | None:
    """Return full analysis result by ID, optionally scoped to a user."""
    with get_db() as conn:
        if user_email:
            row = conn.execute(
                "SELECT * FROM analysis_results WHERE analysis_id = ? AND user_email = ?",
                (analysis_id, user_email.lower()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM analysis_results WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
    return dict(row) if row else None


# ── Batch Jobs ───────────────────────────────────────────────────────────────

def create_batch_job(user_email: str, total_images: int) -> dict:
    import uuid, time
    job_id = str(uuid.uuid4())
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO batch_jobs (id, user_email, status, total_images, completed, results_json, created_at, updated_at)
               VALUES (?, ?, 'pending', ?, 0, '[]', ?, ?)""",
            (job_id, user_email.lower(), total_images, now, now),
        )
    return {"id": job_id, "status": "pending", "total_images": total_images, "completed": 0}


def update_batch_job(job_id: str, *, status: str | None = None, completed: int | None = None, results_json: str | None = None):
    import time
    sets, params = [], []
    if status is not None:
        sets.append("status = ?"); params.append(status)
    if completed is not None:
        sets.append("completed = ?"); params.append(completed)
    if results_json is not None:
        sets.append("results_json = ?"); params.append(results_json)
    sets.append("updated_at = ?"); params.append(time.time())
    params.append(job_id)
    with get_db() as conn:
        conn.execute(f"UPDATE batch_jobs SET {', '.join(sets)} WHERE id = ?", params)


def get_batch_job(job_id: str, user_email: str | None = None) -> dict | None:
    with get_db() as conn:
        if user_email:
            row = conn.execute("SELECT * FROM batch_jobs WHERE id = ? AND user_email = ?", (job_id, user_email.lower())).fetchone()
        else:
            row = conn.execute("SELECT * FROM batch_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


# ── Reference Library ────────────────────────────────────────────────────────

def add_reference(user_email: str, name: str, image_path: str, analysis_id: str | None = None,
                  category: str = "uncategorized", notes: str = "", tags: str = "") -> dict:
    import uuid, time
    ref_id = str(uuid.uuid4())
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO reference_library (id, user_email, name, category, image_path, analysis_id, notes, tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ref_id, user_email.lower(), name, category, image_path, analysis_id, notes, tags, now),
        )
    return {"id": ref_id, "name": name, "category": category, "created_at": now}


def list_references(user_email: str, category: str | None = None) -> list[dict]:
    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM reference_library WHERE user_email = ? AND category = ? ORDER BY created_at DESC",
                (user_email.lower(), category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reference_library WHERE user_email = ? ORDER BY created_at DESC",
                (user_email.lower(),),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_reference(ref_id: str, user_email: str) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM reference_library WHERE id = ? AND user_email = ?", (ref_id, user_email.lower()))
    return cur.rowcount > 0


# ── API Keys ─────────────────────────────────────────────────────────────────

def create_api_key(user_email: str, name: str = "Default") -> dict:
    import uuid, time, secrets, hashlib
    key_id = str(uuid.uuid4())
    raw_key = f"ngw_studio_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:16]
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO api_keys (id, user_email, key_hash, key_prefix, name, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key_id, user_email.lower(), key_hash, key_prefix, name, now),
        )
    return {"id": key_id, "key": raw_key, "prefix": key_prefix, "name": name}


def list_api_keys(user_email: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, key_prefix, name, created_at, last_used, revoked FROM api_keys WHERE user_email = ? AND revoked = 0 ORDER BY created_at DESC",
            (user_email.lower(),),
        ).fetchall()
    return [dict(r) for r in rows]


def validate_api_key(raw_key: str) -> str | None:
    """Validate an API key and return the associated user email, or None."""
    import hashlib, time
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_email FROM api_keys WHERE key_hash = ? AND revoked = 0",
            (key_hash,),
        ).fetchone()
        if row:
            conn.execute("UPDATE api_keys SET last_used = ? WHERE key_hash = ?", (time.time(), key_hash))
            return row["user_email"]
    return None


def revoke_api_key(key_id: str, user_email: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET revoked = 1 WHERE id = ? AND user_email = ?",
            (key_id, user_email.lower()),
        )
    return cur.rowcount > 0


# ── Teams ────────────────────────────────────────────────────────────────────

def create_team(owner_id: str, name: str) -> dict:
    import uuid, time
    team_id = str(uuid.uuid4())
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO teams (id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
            (team_id, name, owner_id, now),
        )
        conn.execute(
            "INSERT INTO team_members (team_id, user_id, role, invited_at) VALUES (?, ?, 'owner', ?)",
            (team_id, owner_id, now),
        )
    return {"id": team_id, "name": name, "owner_id": owner_id}


def add_team_member(team_id: str, user_id: str, role: str = "member") -> bool:
    import time
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO team_members (team_id, user_id, role, invited_at) VALUES (?, ?, ?, ?)",
                (team_id, user_id, role, time.time()),
            )
        return True
    except Exception:
        return False


def get_team_members(team_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT tm.user_id, tm.role, tm.invited_at, u.email, u.username
               FROM team_members tm LEFT JOIN users u ON tm.user_id = u.id
               WHERE tm.team_id = ?""",
            (team_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_teams(user_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT t.id, t.name, t.owner_id, t.created_at, tm.role
               FROM teams t JOIN team_members tm ON t.id = tm.team_id
               WHERE tm.user_id = ?""",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def remove_team_member(team_id: str, user_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM team_members WHERE team_id = ? AND user_id = ? AND role != 'owner'",
            (team_id, user_id),
        )
    return cur.rowcount > 0


# ── Team Sessions (shoot session sharing) ────────────────────────────────────

def create_team_session(
    creator_email: str,
    setup_name: str,
    setup_data: str,
    expires_in: int = 86400,
) -> Dict[str, Any]:
    """Create a shared shoot session. Returns the session dict with share_token."""
    import secrets
    session_id = uuid.uuid4().hex
    now = time.time()
    expires_at = now + expires_in

    # Generate a short URL-safe token with collision retry
    for _ in range(5):
        token = secrets.token_urlsafe(8)  # ~11 chars, 64 bits entropy
        try:
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO team_sessions
                       (id, share_token, creator_email, setup_name, setup_data, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, token, creator_email, setup_name, setup_data, now, expires_at),
                )
            return {
                "id": session_id,
                "share_token": token,
                "creator_email": creator_email,
                "setup_name": setup_name,
                "created_at": now,
                "expires_at": expires_at,
            }
        except Exception:
            session_id = uuid.uuid4().hex
            continue
    raise RuntimeError("Failed to generate unique session token after 5 attempts")


def get_team_session_by_token(share_token: str) -> Optional[Dict[str, Any]]:
    """Fetch a session by its share token. Returns None if not found.
    Does NOT check expiry — caller decides 404 vs 410."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM team_sessions WHERE share_token = ?",
            (share_token,),
        ).fetchone()
    return dict(row) if row else None


def update_team_session(
    share_token: str,
    setup_name: Optional[str] = None,
    setup_data: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update a session's name or data. Returns updated row or None."""
    updates = []
    params = []
    if setup_name is not None:
        updates.append("setup_name = ?")
        params.append(setup_name)
    if setup_data is not None:
        updates.append("setup_data = ?")
        params.append(setup_data)
    if not updates:
        return get_team_session_by_token(share_token)
    params.append(share_token)
    with get_db() as conn:
        conn.execute(
            f"UPDATE team_sessions SET {', '.join(updates)} WHERE share_token = ?",
            params,
        )
    return get_team_session_by_token(share_token)


def cleanup_expired_team_sessions() -> int:
    """Delete sessions that expired more than 1 hour ago. Returns count deleted."""
    cutoff = time.time() - 3600
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM team_sessions WHERE expires_at < ?",
            (cutoff,),
        )
    return cur.rowcount
