from __future__ import annotations

# Load .env BEFORE any engine imports — engine/vlm.py reads API keys at
# module import time, so dotenv must run first.
from dotenv import load_dotenv
load_dotenv()

import logging as _logging
import sys as _sys

# ── Logging — INFO/WARNING → stdout, ERROR/CRITICAL → stderr ──
import os as _os_early
_log_level = _os_early.environ.get("NGW_LOG_LEVEL", "INFO").upper()
_log_fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_log_datefmt = "%H:%M:%S"

_stdout_handler = _logging.StreamHandler(_sys.stdout)
_stdout_handler.setLevel(getattr(_logging, _log_level, _logging.INFO))
_stdout_handler.addFilter(lambda r: r.levelno < _logging.ERROR)
_stdout_handler.setFormatter(_logging.Formatter(_log_fmt, datefmt=_log_datefmt))

_stderr_handler = _logging.StreamHandler(_sys.stderr)
_stderr_handler.setLevel(_logging.ERROR)
_stderr_handler.setFormatter(_logging.Formatter(_log_fmt, datefmt=_log_datefmt))

_logging.basicConfig(
    level=getattr(_logging, _log_level, _logging.INFO),
    handlers=[_stdout_handler, _stderr_handler],
)
_startup_logger = _logging.getLogger("ngw.startup")

# ── In-memory log buffer — captured before any other imports so we catch
#    startup errors too.  Served by GET /api/lab/server-logs.
from engine.log_buffer import install as _install_log_buffer  # noqa: E402
_install_log_buffer()

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from pathlib import Path

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

from api.routes.shoot_match import router as shoot_match_router
from api.routes.recommend import router as recommend_router
from api.routes.auth import router as auth_router
from api.routes.user_data import router as user_data_router
from api.routes.admin import router as admin_router
from api.routes.diagnostics import router as diagnostics_router
from api.routes.lab import router as lab_router
from api.routes.lab import analyze_router
from api.routes.gallery import router as gallery_router
from api.routes.lab_benchmarks import router as lab_benchmarks_router
from api.routes.lab_signals import router as lab_signals_router
from api.routes.exec_dashboard import router as exec_dashboard_router
from api.routes.lighting_dna import router as lighting_dna_router
from api.routes.shoot_mode import router as shoot_mode_router
from api.routes.spatial import router as spatial_router
from api.routes.blueprint import router as blueprint_router
from api.routes.live_feedback import router as live_feedback_router
from api.routes.style_dna import router as style_dna_router
from api.routes.track import router as track_router
from api.routes.learning import router as learning_router
from api.routes.flags import router as flags_router
from api.routes.experiments import router as experiments_router
from api.routes.paywall import router as paywall_router
from api.routes.stripe_checkout import router as stripe_router
from api.routes.waitlist import router as waitlist_router
from api.routes.failures import router as failures_router
from api.routes.intelligence import router as intelligence_router
from api.routes.health import router as health_router
from api.routes.batch import router as batch_router
from api.routes.reference_library import router as reference_library_router
from api.routes.teams import router as teams_router
from api.routes.team_sessions import router as team_sessions_router
from api.routes.api_keys import router as api_keys_router
from api.routes.studio_api import router as studio_api_router
from api.routes.brief import router as brief_router
from db.database import init_db

from engine.services.recommend_service import ENGINE_VERSION


@asynccontextmanager
async def lifespan(app):
    # ── Production safety guards ──────────────────────────────────────────────
    _dev_mode = os.getenv("NGW_DEV_MODE", "").strip().lower() in ("1", "true", "yes")
    _env = os.getenv("ENVIRONMENT", "production").strip().lower()
    if _dev_mode and _env == "production":
        raise RuntimeError(
            "NGW_DEV_MODE is enabled but ENVIRONMENT=production. "
            "This bypasses all admin auth. Refusing to start. "
            "Set ENVIRONMENT=development or unset NGW_DEV_MODE."
        )

    # ── Required env vars preflight (production only) ────────────────────────
    if _env == "production":
        _required = ["NGW_JWT_SECRET", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"]
        _missing = [v for v in _required if not os.getenv(v)]
        if _missing:
            raise RuntimeError(
                f"Missing required environment variables for production: {_missing}. "
                "Set these before starting the server."
            )

    # ── Sentry (optional — only initialised when SENTRY_DSN is set) ──────────
    _sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
    if _sentry_dsn:
        try:
            import subprocess as _sp
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration
            import logging as _sl

            # Release: prefer Render/CI env vars, fall back to local git SHA
            _release = (
                os.getenv("RENDER_GIT_COMMIT")
                or os.getenv("GIT_COMMIT")
            )
            if not _release:
                try:
                    _release = _sp.check_output(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=str(Path(__file__).parent),
                        stderr=_sp.DEVNULL,
                    ).decode().strip()
                except Exception:
                    _release = "unknown"

            sentry_sdk.init(
                dsn=_sentry_dsn,
                environment=_env,
                release=_release,
                traces_sample_rate=0.1,
                send_default_pii=False,
                integrations=[
                    StarletteIntegration(transaction_style="endpoint"),
                    FastApiIntegration(transaction_style="endpoint"),
                    LoggingIntegration(
                        level=_sl.WARNING,       # breadcrumbs at WARNING+
                        event_level=_sl.ERROR,   # Sentry events at ERROR+
                    ),
                ],
            )
            _startup_logger.info(
                "✓ Sentry initialised (environment=%s release=%s)", _env, _release
            )
        except Exception as _sentry_exc:
            _startup_logger.error(
                "Sentry init failed (server continues without Sentry): %s", _sentry_exc
            )
    else:
        _startup_logger.warning(
            "SENTRY_DSN not set — runtime errors will not be captured by Sentry"
        )

    # Ensure runtime directories exist (safe on both local dev and Render/Docker)
    for d in ("data", "static/uploads", "static/www", "static/ui"):
        Path(d).mkdir(parents=True, exist_ok=True)
    init_db()
    from db.database import DB_PATH
    _startup_logger.info("✓ Database path: %s", DB_PATH)
    from db.benchmark import init_benchmark_tables
    init_benchmark_tables()
    from db.benchmark_baseline import init_baseline_tables
    init_baseline_tables()
    from db.signals import init_signals_tables, seed_signals
    init_signals_tables()
    seed_signals()   # no-op if rows already exist
    from db.experiments import init_experiments_tables
    init_experiments_tables()

    # ── Startup service probes — VLM, DB, SMTP, Stripe (all parallel) ──────────
    # Each probe is informational only — a failure is logged and stored for the
    # health endpoint but never blocks startup or disables the service.
    # SKIP_PROBES=1 skips all probes for fast local dev startup.
    _skip_probes = os.getenv("SKIP_PROBES", "").strip().lower() in ("1", "true", "yes")
    if not _skip_probes:
      try:
        import asyncio as _aio
        import engine.vlm          as _vlm_mod
        import engine.service_health as _svc_health
        from engine.vlm          import probe_api_key, vlm_available, _VLM_PROVIDER
        from engine.service_health import probe_db, probe_smtp, probe_stripe, probe_sentry

        async def _probe(fn, timeout_s: float, fallback: dict):
            """Run fn() in a thread with a wall-clock timeout."""
            try:
                return await _aio.wait_for(
                    _aio.get_running_loop().run_in_executor(None, fn),
                    timeout=timeout_s,
                )
            except _aio.TimeoutError:
                return {**fallback, "detail": f"probe timed out ({timeout_s:.0f}s)"}
            except Exception as exc:
                return {**fallback, "detail": str(exc)}

        async def _vlm_probe_or_skip():
            if vlm_available():
                return await _probe(probe_api_key, 10.0, {"ok": False, "provider": _VLM_PROVIDER})
            return {"ok": None, "provider": _VLM_PROVIDER, "detail": "not configured"}

        vlm_r, db_r, smtp_r, stripe_r, sentry_r = await _aio.gather(
            _vlm_probe_or_skip(),
            _probe(probe_db,     5.0,  {"ok": False, "service": "db"}),
            _probe(probe_smtp,   10.0, {"ok": False, "service": "smtp"}),
            _probe(probe_stripe, 10.0, {"ok": False, "service": "stripe"}),
            _probe(probe_sentry, 10.0, {"ok": False, "service": "sentry"}),
        )

        _vlm_mod._vlm_probe_result         = vlm_r
        _svc_health._db_probe_result       = db_r
        _svc_health._smtp_probe_result     = smtp_r
        _svc_health._stripe_probe_result   = stripe_r
        _svc_health._sentry_probe_result   = sentry_r

        for label, r in (("VLM", vlm_r), ("DB", db_r), ("SMTP", smtp_r), ("Stripe", stripe_r), ("Sentry", sentry_r)):
            if r.get("ok") is True:
                _startup_logger.info("✓ %s: %s", label, r.get("detail", "OK"))
            elif r.get("ok") is None:
                _startup_logger.warning("  %s: %s (skipped)", label, r.get("detail", "not configured"))
            else:
                _startup_logger.error("✗ %s: %s", label, r.get("detail", "probe failed"))

        # Detailed VLM failure guidance
        if vlm_r.get("ok") is False:
            _startup_logger.error(
                "  → Update %s_API_KEY in .env and restart.\n"
                "  → VLM calls will still attempt but may fail.",
                _VLM_PROVIDER.upper(),
            )
      except Exception as exc:
        _startup_logger.warning("Service probes failed at startup: %s", exc)
    else:
        _startup_logger.info("SKIP_PROBES=1 — skipping startup service probes")

    # Start background scheduler (no-op if ENABLE_SCHEDULER is not set)
    from engine.scheduler import boot_scheduler, stop_scheduler
    boot_scheduler()

    # Start waitlist email sequence loop (no-op if WAITLIST_SEQUENCE_ENABLED not set)
    from engine.email_sequence import boot_sequence, stop_sequence
    boot_sequence()

    yield

    stop_scheduler()
    stop_sequence()


app = FastAPI(title="NGW Core v1", version=ENGINE_VERSION, lifespan=lifespan)


# ── Global exception handler ──────────────────────────────────────────────────
# Ensures every unhandled error returns structured JSON (not an HTML 500 page)
# so the frontend can always parse `response.json().detail`.

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred. Please try again."},
    )


# ── CORS ─────────────────────────────────────────────────────────────────────
# Set ALLOWED_ORIGINS env var to a comma-separated list of origins.
# Example: https://ngw.vercel.app,https://www.noguesswork.com
# Defaults to localhost only for safe local development.
_raw_origins = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:8000"
)
_allowed_origins: List[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(shoot_match_router, prefix="/api")
app.include_router(recommend_router)  # mounted at root (not /api) for backward compat
app.include_router(auth_router, prefix="/api")
app.include_router(user_data_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(diagnostics_router, prefix="/api")
app.include_router(lab_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")   # customer-facing /api/analyze
app.include_router(gallery_router, prefix="/api")    # public accuracy gallery
app.include_router(lab_benchmarks_router, prefix="/api/lab")
app.include_router(exec_dashboard_router, prefix="/api")
app.include_router(lighting_dna_router, prefix="/api")
app.include_router(shoot_mode_router, prefix="/api")
app.include_router(spatial_router, prefix="/api")
app.include_router(blueprint_router, prefix="/api")
app.include_router(live_feedback_router, prefix="/api")
app.include_router(style_dna_router, prefix="/api")
app.include_router(track_router, prefix="/api")
app.include_router(learning_router, prefix="/api")
app.include_router(lab_signals_router, prefix="/api")
app.include_router(flags_router, prefix="/api")
app.include_router(experiments_router, prefix="/api")
app.include_router(paywall_router, prefix="/api")
app.include_router(stripe_router, prefix="/api")
app.include_router(waitlist_router)
app.include_router(failures_router, prefix="/api")
app.include_router(intelligence_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(batch_router)  # prefix already set in router (/api/batch)
app.include_router(reference_library_router)  # prefixes set in router (/api/studio/*, /api/shared/*)
app.include_router(teams_router)  # prefix set in router (/api/teams)
app.include_router(team_sessions_router)  # prefix set in router (/api/team-sessions)
app.include_router(api_keys_router)  # prefix set in router (/api/api-keys)
app.include_router(studio_api_router)  # prefix set in router (/api/v1)
app.include_router(brief_router)  # prefix set in router (/api/brief)
# Sample image served at root for HomeScreen "Try a Sample" flow
@app.get("/ghost-rembrandt.jpg")
async def serve_sample_image():
    from fastapi.responses import FileResponse
    return FileResponse("static/ui/ghost-rembrandt.jpg", media_type="image/jpeg")

app.mount("/www", StaticFiles(directory="static/www"), name="www")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    # ── Sentry user context ──────────────────────────────────────────────
    # Attempt to extract user from JWT Bearer token so every Sentry event
    # in this request is tagged with the user's email/id.
    try:
        import sentry_sdk as _s_ctx
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            from auth.security import decode_token
            from db.database import get_user_by_id
            _uid = decode_token(auth_header[7:])
            if _uid:
                _u = get_user_by_id(_uid)
                if _u:
                    _s_ctx.set_user({"id": str(_u["id"]), "email": _u.get("email", "")})
    except Exception:
        pass  # never block a request for telemetry

    response = await call_next(request)

    # ── Security headers ──────────────────────────────────────────────────────
    # Prevent MIME-type sniffing.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Block this app from being framed on other origins (clickjacking protection).
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # Don't send the Referer header when navigating to a different origin.
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Opt out of FLoC / Topics API.
    response.headers.setdefault("Permissions-Policy", "interest-cohort=()")
    # Content Security Policy — restricts which resources the browser can load.
    # 'unsafe-inline' / 'unsafe-eval' are required by React/Vite in production
    # (inline styles, dynamic imports). Stripe JS requires frame-src allowance.
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://js.stripe.com; "
            # worker-src was unset, so it fell back to script-src, which has no
            # blob: — every Worker created from a blob URL was blocked. The export
            # path (socialCanvas, exportSvg, SocialExportPanel) builds blob URLs.
            "worker-src 'self' blob:; "
            # Google Fonts needs the stylesheet host here and the font files in
            # font-src below; without both, Inter never loads and the page
            # silently falls back to system faces.
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; "
            # "o*.ingest.sentry.io" was invalid twice over: a CSP host wildcard
            # must be a leading "*." label, and the real host carries a region
            # segment (o…​.ingest.US.sentry.io). An invalid source makes the
            # browser drop it, so Sentry was blocked outright — the tool that
            # reports errors could not report.
            "connect-src 'self' https://api.stripe.com https://js.stripe.com "
            "https://*.ingest.sentry.io https://*.ingest.us.sentry.io; "
            "frame-src https://js.stripe.com https://hooks.stripe.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "object-src 'none'; "
            "base-uri 'self';"
        ),
    )

    # ── Cache: immutable assets ───────────────────────────────────────────────
    # Vite build outputs content-hashed filenames under /static/ui/assets/.
    # These are safe to cache forever — new deploy = new hash = new URL.
    if request.url.path.startswith("/static/ui/assets/"):
        response.headers["Cache-Control"] = "max-age=31536000, immutable"

    return response

@app.get("/health")
def health() -> Dict[str, Any]:
    from db.database import get_db
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "detail": "database", "error": str(exc)},
        )
    return {"status": "ok", "engine_version": ENGINE_VERSION}


def _is_mobile(request: Request) -> bool:
    """Check User-Agent for mobile device indicators."""
    ua = (request.headers.get("user-agent") or "").lower()
    return any(tok in ua for tok in ("iphone", "android", "mobile", "ipod"))


@app.get("/")
def root(request: Request):
    # app.noguessworksystems.com → always serve the product UI
    host = (request.headers.get("host") or "").lower()
    if host.startswith("app."):
        return ui()
    # Mobile → straight to the app (tool UI)
    if _is_mobile(request):
        return RedirectResponse(url="/ui", status_code=307)
    # Desktop → marketing site
    www_path = Path("static/www/index.html")
    if www_path.exists():
        return HTMLResponse(www_path.read_text(encoding="utf-8"))
    return RedirectResponse(url="/ui", status_code=307)


_MARKETING_PAGES = {"features", "pricing", "library", "blog", "login", "signup", "early-access"}

_DOCS_PAGES = {"index", "patterns", "glossary", "how-it-works"}


@app.get("/features")
@app.get("/pricing")
@app.get("/library")
@app.get("/blog")
@app.get("/login")
@app.get("/signup")
@app.get("/early-access")
def marketing_page(request: Request):
    page = request.url.path.lstrip("/")
    if page not in _MARKETING_PAGES:
        raise HTTPException(status_code=404)
    # Mobile → redirect login/signup to the app UI
    if _is_mobile(request) and page in ("login", "signup"):
        return RedirectResponse(url="/ui", status_code=307)
    file_path = Path(f"static/www/{page}.html")
    if file_path.exists():
        return HTMLResponse(file_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404)


@app.get("/docs")
def docs_index_redirect():
    return RedirectResponse(url="/docs/", status_code=301)


@app.get("/docs/")
@app.get("/docs/{page}")
def docs_page(page: str = "index"):
    slug = page.rstrip("/") or "index"
    slug = slug.removesuffix(".html")
    if slug not in _DOCS_PAGES:
        raise HTTPException(status_code=404)
    file_path = Path(f"static/www/docs/{slug}.html")
    if file_path.exists():
        return HTMLResponse(file_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404)


@app.get("/sitemap.xml")
def sitemap():
    base = "https://noguessworksystems.com"
    urls = [
        f"{base}/",
        f"{base}/features",
        f"{base}/pricing",
        f"{base}/blog",
        f"{base}/library",
        f"{base}/docs/",
        f"{base}/docs/patterns",
        f"{base}/docs/glossary",
        f"{base}/docs/how-it-works",
    ]
    items = "\n".join(
        f"  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>"
        for u in urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n"
        "</urlset>"
    )
    return HTMLResponse(content=xml, media_type="application/xml")


@app.get("/robots.txt")
def robots_txt():
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /docs/\n"
        "Allow: /features\n"
        "Allow: /pricing\n"
        "Allow: /blog\n"
        "Allow: /library\n"
        "Disallow: /api/\n"
        "Disallow: /ui\n"
        "Disallow: /static/uploads/\n"
        "Sitemap: https://noguessworksystems.com/sitemap.xml\n"
    )
    return HTMLResponse(content=content, media_type="text/plain")


@app.get("/ui")
def ui() -> HTMLResponse:
    ui_path = Path("static/ui/index.html")
    html = ui_path.read_text(encoding="utf-8") if ui_path.exists() else "<html><body><h1>NGW UI</h1></body></html>"
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


