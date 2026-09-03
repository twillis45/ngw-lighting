"""
API Key & Service Health — /api/health/*
========================================

GET  /api/health            — basic liveness check
GET  /api/health/api-keys   — service probes + recent VLM health events
GET  /api/health/system     — uptime, storage, scheduler, VLM rolling stats
POST /api/health/api-keys/probe — force a live key probe right now
"""
from __future__ import annotations

import logging
import time
from typing import Dict

from fastapi import APIRouter, Depends

from auth.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

# Process boot time — used for uptime calculation
_BOOT_EPOCH = time.time()

import os
from config.admin import is_admin

def _require_admin(user: dict) -> None:
    if os.getenv("NGW_DEV_MODE", "").strip().lower() in ("1", "true", "yes"):
        return
    if not user or not is_admin(user.get("email")):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("/health")
async def liveness():
    """Basic liveness — always returns 200 if the server is up."""
    return {"ok": True, "service": "ngw-core"}


@router.get("/health/api-keys")
async def api_key_status(user=Depends(get_current_user)):
    """Return health status for all services: VLM, DB, SMTP, Stripe + recent VLM events."""
    _require_admin(user)
    from db.database import get_api_health_events, get_latest_api_health
    from engine.vlm          import _VLM_PROVIDER, _VLM_MODEL, vlm_available, _vlm_probe_result
    from engine.service_health import _db_probe_result, _smtp_probe_result, _stripe_probe_result, _sentry_probe_result

    latest        = get_latest_api_health(_VLM_PROVIDER) if _VLM_PROVIDER != "none" else None
    recent_events = get_api_health_events(limit=20)

    # Legacy convenience fields (kept for backward compat)
    smtp_configured = all([
        os.getenv("SMTP_HOST", "").strip(),
        os.getenv("SMTP_USER", "").strip(),
        os.getenv("SMTP_PASS", "").strip(),
    ])

    # has_errors = any startup probe failed OR recent VLM error events
    has_errors = any(e["event_type"] in ("401_error", "probe_fail") for e in recent_events[:5])
    if _vlm_probe_result and not _vlm_probe_result["ok"]:
        has_errors = True

    def _svc(r):
        if r is None:
            return {"ok": None, "detail": None}
        return {"ok": r.get("ok"), "detail": r.get("detail")}

    return {
        # VLM
        "provider":         _VLM_PROVIDER,
        "model":            _VLM_MODEL,
        "vlm_available":    vlm_available(),
        "vlm_probe_ok":     _vlm_probe_result["ok"] if _vlm_probe_result else None,
        "vlm_probe_detail": _vlm_probe_result.get("detail") if _vlm_probe_result else None,
        # VLM event log
        "latest_event":     latest,
        "recent_events":    recent_events,
        "has_errors":       has_errors,
        # Legacy SMTP fields
        "smtp_configured":  smtp_configured,
        "smtp_host":        os.getenv("SMTP_HOST", ""),
        "from_email":       os.getenv("FROM_EMAIL", ""),
        "app_url":          os.getenv("APP_URL", ""),
        # Structured per-service probe results — hoisted to top level so the
        # frontend can read health.db.ok / health.smtp.ok / etc. directly,
        # AND nested under "services" for programmatic consumers.
        "db":     _svc(_db_probe_result),
        "smtp":   _svc(_smtp_probe_result),
        "stripe": _svc(_stripe_probe_result),
        "sentry": _svc(_sentry_probe_result),
        "services": {
            "vlm":    _svc(_vlm_probe_result),
            "db":     _svc(_db_probe_result),
            "smtp":   _svc(_smtp_probe_result),
            "stripe": _svc(_stripe_probe_result),
            "sentry": _svc(_sentry_probe_result),
        },
    }


@router.post("/health/sentry/test")
async def sentry_test_capture(user=Depends(get_current_user)):
    """Send a test capture_message to Sentry and return the event ID."""
    _require_admin(user)
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return {"ok": False, "detail": "SENTRY_DSN not set — configure it in .env to enable Sentry"}
    try:
        import sentry_sdk
        client = sentry_sdk.get_client()
        if client is None or not getattr(client, "options", {}).get("dsn"):
            return {"ok": False, "detail": "Sentry SDK not initialised — restart the server after setting SENTRY_DSN"}
        event_id = sentry_sdk.capture_message("NGW Lab health check — test event", level="info")
        return {"ok": True, "detail": f"Test event sent (id: {event_id or 'unknown'})"}
    except Exception as exc:
        return {"ok": False, "detail": f"Sentry capture failed: {str(exc)[:120]}"}


@router.post("/health/api-keys/probe")
async def force_key_probe(user=Depends(get_current_user)):
    """Run a live API key probe right now and return the result."""
    _require_admin(user)
    from engine.vlm import probe_api_key, vlm_available
    if not vlm_available():
        return {"ok": False, "detail": "VLM not configured — set VLM_PROVIDER and API key in .env"}
    result = probe_api_key()
    return result


@router.get("/health/system")
async def system_health(user=Depends(get_current_user)):
    """Operational health: uptime, storage, background tasks, VLM rolling stats."""
    _require_admin(user)
    from pathlib import Path
    import shutil

    # ── Uptime ────────────────────────────────────────────────────────────
    uptime_secs = round(time.time() - _BOOT_EPOCH, 1)

    # ── Upload storage ────────────────────────────────────────────────────
    # Was hardcoded "static/uploads" while the uploader read NGW_UPLOAD_DIR.
    # Setting that variable made this report on a directory nothing wrote to.
    from paths import UPLOAD_DIR as uploads_dir
    uploads_writable = os.access(uploads_dir, os.W_OK) if uploads_dir.exists() else False
    try:
        disk = shutil.disk_usage(uploads_dir if uploads_dir.exists() else Path("."))
        uploads_free_gb = round(disk.free / (1024 ** 3), 2)
    except Exception:
        uploads_free_gb = None

    # ── Scheduler ─────────────────────────────────────────────────────────
    try:
        from engine.scheduler import get_scheduler_status, is_task_running
        sched = get_scheduler_status()
        scheduler_running  = is_task_running()
        scheduler_last_run = sched.get("last_run_at")
        scheduler_error    = sched.get("last_run_error")
        scheduler_runs     = sched.get("run_count", 0)
    except Exception:
        scheduler_running  = None
        scheduler_last_run = None
        scheduler_error    = None
        scheduler_runs     = 0

    # ── Email sequence ────────────────────────────────────────────────────
    try:
        from engine.email_sequence import _seq_task
        sequence_running = _seq_task is not None and not _seq_task.done()
    except Exception:
        sequence_running = None

    # ── VLM rolling stats (1h + 24h) ─────────────────────────────────────
    try:
        from db.database import get_vlm_call_stats
        vlm_1h  = get_vlm_call_stats(hours=1)
        vlm_24h = get_vlm_call_stats(hours=24)
    except Exception:
        vlm_1h  = None
        vlm_24h = None

    # ── JWT safety ────────────────────────────────────────────────────────
    jwt_secret = os.getenv("NGW_JWT_SECRET", "").strip()
    jwt_ok = bool(jwt_secret) and jwt_secret not in (
        "CHANGE_ME", "changeme", "your-secret-here", "replace-this",
    )

    return {
        "uptime_secs":        uptime_secs,
        "uploads_writable":   uploads_writable,
        "uploads_free_gb":    uploads_free_gb,
        "scheduler_running":  scheduler_running,
        "scheduler_last_run": scheduler_last_run,
        "scheduler_error":    scheduler_error,
        "scheduler_runs":     scheduler_runs,
        "sequence_running":   sequence_running,
        "jwt_configured":     jwt_ok,
        "vlm_stats_1h":       vlm_1h,
        "vlm_stats_24h":      vlm_24h,
    }
