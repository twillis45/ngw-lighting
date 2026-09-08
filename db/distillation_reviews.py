"""distillation_reviews.py — Phase 5c: durable human review state for distillation candidates.

Stores the CURRENT review decision for each distillation candidate or review-queue
entry. This is mutable review STATE, not an append-only log. Each row represents
the latest human judgment on one item.

Source facts (expected_pattern, predicted_pattern, confidence, path_type, etc.)
are seeded from a Phase 5b JSON report and are NEVER overwritten by update_review().
Only the review-decision fields (review_status, reviewer, reviewed_at, rationale, notes)
change on update.

Review statuses
---------------
  pending_review      — not yet reviewed (default on seed)
  approved_candidate  — approved for future distillation consideration
  rejected            — not suitable; rationale required
  gold_set_issue      — gold-set entry itself is suspect; distillation for this
                        pattern is blocked until the gold-set issue is resolved
  specialty_watch     — correct result but specialty-path confidence floor is
                        provisional (2 data points); hold until >= 5 data points

Identity model
--------------
  Rows are keyed by image_path (UNIQUE constraint). seed_from_report() is
  idempotent — existing rows by image_path are skipped, not overwritten.

  This means re-running a seed from a newer report will NOT overwrite prior review
  decisions. If the runtime result for an image changes materially (new confidence,
  new predicted pattern), the operator must handle that conflict explicitly — there
  is no automated merge.

Entry types
-----------
  candidate     — cleared the Phase 5b candidate threshold gates
  review_queue  — flagged for human review by _build_review_queue() (static
                  manifest analysis); may not have runtime prediction data
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db


# ── Constants ────────────────────────────────────────────────────────────────

VALID_STATUSES: frozenset[str] = frozenset({
    "pending_review",
    "approved_candidate",
    "rejected",
    "gold_set_issue",
    "specialty_watch",
})

VALID_ENTRY_TYPES: frozenset[str] = frozenset({"candidate", "review_queue"})


# ── Schema ────────────────────────────────────────────────────────────────────

def init_distillation_reviews_table() -> None:
    """Create distillation_candidate_reviews table and indexes if they don't exist.

    Called from db.database.init_db(). Safe to call multiple times (IF NOT EXISTS).
    """
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS distillation_candidate_reviews (
                id                           TEXT PRIMARY KEY,

                -- Source facts: seeded from Phase 5b JSON report.
                -- These columns are NEVER modified by update_review().
                image_path                   TEXT NOT NULL UNIQUE,
                expected_pattern             TEXT NOT NULL,
                predicted_pattern            TEXT NOT NULL,
                confidence                   REAL NOT NULL,
                correctness                  TEXT NOT NULL,
                path_type                    TEXT NOT NULL,
                candidate_reason             TEXT NOT NULL,
                authoritative_pattern_source TEXT,
                trust_score                  REAL NOT NULL,
                source_report_file           TEXT,
                entry_type                   TEXT NOT NULL,

                -- Review decision: updated by update_review().
                review_status   TEXT NOT NULL DEFAULT 'pending_review',
                reviewer        TEXT,
                reviewed_at     TEXT,
                rationale       TEXT,
                notes           TEXT,

                -- setup_family was added by scripts/migrate_setup_family_column.py
                -- and never made it into this CREATE TABLE, so every FRESH database
                -- was one column short and only the migration could fix it. Added
                -- here 2026-09-08; the migration stays for databases that predate it,
                -- since ADD COLUMN is what an existing table needs.
                setup_family    TEXT NULL DEFAULT NULL,

                -- Audit timestamps.
                created_at      REAL NOT NULL,
                updated_at      REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_dcr_status  ON distillation_candidate_reviews(review_status);
            CREATE INDEX IF NOT EXISTS idx_dcr_pattern ON distillation_candidate_reviews(expected_pattern);
            CREATE INDEX IF NOT EXISTS idx_dcr_path    ON distillation_candidate_reviews(path_type);
            CREATE INDEX IF NOT EXISTS idx_dcr_entry   ON distillation_candidate_reviews(entry_type);
        """)


# ── Seed ──────────────────────────────────────────────────────────────────────

def seed_from_report(report_path: str) -> Tuple[int, int]:
    """Seed review rows from a Phase 5b candidates JSON report.

    Idempotent: existing rows (keyed by image_path) are skipped.
    Returns (seeded_count, skipped_count).

    Source facts are extracted from the report's 'candidates' and 'review_queue'
    sections. Both sections seed into the same table with distinct entry_type values.

    Review-queue entries from the JSON lack runtime prediction data (the static
    manifest analysis does not run the image through the pipeline). For these rows:
      - predicted_pattern is set to "" (no runtime prediction captured at queue time)
      - confidence is set to 0.0
      - correctness is set to "unknown"
      - path_type is set to "unknown"
      - candidate_reason carries the review_reason string from the report

    This is intentional: the source-of-truth for these fields is the Phase 5b
    verbose run output, not the review_queue section of the JSON.
    """
    report = json.loads(Path(report_path).read_text())
    source_report_file = Path(report_path).name

    rows_to_insert: list[dict] = []

    # ── Candidates ───────────────────────────────────────────────────────────
    for c in report.get("candidates", []):
        rows_to_insert.append({
            "image_path":                   c["image_path"],
            "expected_pattern":             c["expected"],
            "predicted_pattern":            c["predicted"],
            "confidence":                   c["confidence"],
            "correctness":                  c["correctness"],
            "path_type":                    c["path_type"],
            "candidate_reason":             c["candidate_reason"],
            "authoritative_pattern_source": c.get("authoritative_pattern_source"),
            "trust_score":                  c["trust_score"],
            "entry_type":                   "candidate",
        })

    # ── Review-queue entries ──────────────────────────────────────────────────
    for r in report.get("review_queue", []):
        rows_to_insert.append({
            "image_path":                   r["image_path"],
            "expected_pattern":             r["expected_pattern"],
            "predicted_pattern":            "",        # not available in static queue analysis
            "confidence":                   0.0,       # not available in static queue analysis
            "correctness":                  "unknown", # not available in static queue analysis
            "path_type":                    "unknown", # not available in static queue analysis
            "candidate_reason":             r["review_reason"],
            "authoritative_pattern_source": None,
            "trust_score":                  r["trust_score"],
            "entry_type":                   "review_queue",
        })

    # ── Insert (skip existing by image_path) ─────────────────────────────────
    seeded = 0
    skipped = 0
    now = time.time()

    with get_db() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT image_path FROM distillation_candidate_reviews"
            ).fetchall()
        }

        for row in rows_to_insert:
            if row["image_path"] in existing:
                skipped += 1
                continue

            conn.execute(
                """INSERT INTO distillation_candidate_reviews (
                    id, image_path, expected_pattern, predicted_pattern,
                    confidence, correctness, path_type, candidate_reason,
                    authoritative_pattern_source, trust_score,
                    source_report_file, entry_type,
                    review_status, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending_review',?,?)""",
                (
                    uuid.uuid4().hex,
                    row["image_path"],
                    row["expected_pattern"],
                    row["predicted_pattern"],
                    row["confidence"],
                    row["correctness"],
                    row["path_type"],
                    row["candidate_reason"],
                    row["authoritative_pattern_source"],
                    row["trust_score"],
                    source_report_file,
                    row["entry_type"],
                    now,
                    now,
                ),
            )
            seeded += 1

    return seeded, skipped


# ── Read ──────────────────────────────────────────────────────────────────────

def get_reviews(
    status: Optional[str] = None,
    path_type: Optional[str] = None,
    entry_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return review rows, optionally filtered by status, path_type, or entry_type."""
    clauses: list[str] = []
    params: list[Any] = []

    if status is not None:
        clauses.append("review_status = ?")
        params.append(status)
    if path_type is not None:
        clauses.append("path_type = ?")
        params.append(path_type)
    if entry_type is not None:
        clauses.append("entry_type = ?")
        params.append(entry_type)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM distillation_candidate_reviews {where} "
            f"ORDER BY entry_type ASC, expected_pattern ASC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_review(review_id: str) -> Optional[Dict[str, Any]]:
    """Return a single review row by id, or None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM distillation_candidate_reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
    return dict(row) if row else None


# ── Update ────────────────────────────────────────────────────────────────────

def insert_from_workbench(
    image_path: str,
    predicted_pattern: str,
    expected_pattern: str,
    confidence: float,
    path_type: str,
    correctness: str,
    reviewer: str,
    notes: str = "",
) -> Dict[str, Any]:
    """Insert a single review row sourced from a Workbench teach action.

    If the image_path already exists in the table the existing row is returned
    unchanged (idempotent — prevents duplicate teach submissions).

    correctness should be 'correct' or 'incorrect'.
    review_status is set to 'approved_candidate' when correct, 'pending_review'
    when incorrect (still needs human confirmation before distillation).
    """
    now = time.time()
    review_status = "approved_candidate" if correctness == "correct" else "pending_review"

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM distillation_candidate_reviews WHERE image_path = ?",
            (image_path,),
        ).fetchone()
        if existing:
            return dict(existing)

        row_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO distillation_candidate_reviews (
                id, image_path, expected_pattern, predicted_pattern,
                confidence, correctness, path_type, candidate_reason,
                authoritative_pattern_source, trust_score,
                source_report_file, entry_type,
                review_status, reviewer, reviewed_at, notes,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id,
                image_path,
                expected_pattern,
                predicted_pattern,
                float(confidence),
                correctness,
                path_type or "primary",
                "workbench_teach",
                None,
                0.85,  # manual label = high trust
                None,
                "candidate",
                review_status,
                reviewer,
                str(now),
                notes,
                now,
                now,
            ),
        )

    return get_review(row_id)


def update_review(
    review_id: str,
    review_status: str,
    reviewer: str,
    rationale: str = "",
    notes: str = "",
) -> Optional[Dict[str, Any]]:
    """Update the review decision fields for one row.

    Only review_status, reviewer, reviewed_at, rationale, and notes are modified.
    Source facts (expected_pattern, predicted_pattern, confidence, path_type, etc.)
    are never touched.

    Returns the updated row, or None if the row was not found.
    Raises ValueError if review_status is not a valid status string.
    """
    if review_status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid review_status {review_status!r}. "
            f"Must be one of: {sorted(VALID_STATUSES)}"
        )

    now = time.time()
    reviewed_at = str(now)

    with get_db() as conn:
        result = conn.execute(
            """UPDATE distillation_candidate_reviews
               SET review_status = ?,
                   reviewer      = ?,
                   reviewed_at   = ?,
                   rationale     = ?,
                   notes         = ?,
                   updated_at    = ?
               WHERE id = ?""",
            (review_status, reviewer, reviewed_at, rationale, notes, now, review_id),
        )
        if result.rowcount == 0:
            return None

    return get_review(review_id)
