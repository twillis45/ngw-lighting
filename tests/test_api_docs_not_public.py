"""Interactive API docs must not be public, and must not shadow our own /docs.

Found 2026-08-31 against production. /docs, /redoc and /openapi.json all
returned 200, publishing 243 routes — 118 of them admin, lab or debug — with
full request and response schemas. A free map of the private surface, and it
makes probing for an unguarded route trivial.

The same defect silently broke the project's own documentation. main.py
registers @app.get("/docs") to redirect to the handwritten pages, but FastAPI
mounts its built-in Swagger at app construction, so the built-in always won and
that redirect was unreachable code. Disabling the built-ins fixes the exposure
AND makes the handwritten route work for the first time.

Docs are still available locally on NON-COLLIDING paths (/api-docs,
/api-redoc) when NGW_ENABLE_API_DOCS=1 or NGW_DEV_MODE=1, because reading the
schema is the point during development.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, docs_on: bool):
    monkeypatch.setenv("NGW_JWT_SECRET", "x" * 64)
    monkeypatch.setenv("NGW_DEV_MODE", "0")
    if docs_on:
        monkeypatch.setenv("NGW_ENABLE_API_DOCS", "1")
    else:
        monkeypatch.delenv("NGW_ENABLE_API_DOCS", raising=False)
    import main
    importlib.reload(main)
    return TestClient(main.app)


@pytest.mark.parametrize("path", ["/openapi.json", "/redoc", "/api-docs", "/api-redoc"])
def test_schema_endpoints_are_absent_by_default(monkeypatch, path):
    """Default = production. Nothing that publishes the route table answers."""
    assert _client(monkeypatch, docs_on=False).get(path).status_code == 404, (
        f"{path} is served by default — the private API surface is public")


def test_our_own_docs_route_is_reachable(monkeypatch):
    """It was shadowed by FastAPI's built-in Swagger and could never run."""
    r = _client(monkeypatch, docs_on=False).get("/docs", follow_redirects=False)
    assert r.status_code == 301, (
        f"/docs returned {r.status_code}, not the handwritten redirect — "
        "something is shadowing it again")
    assert r.headers.get("location") == "/docs/"


def test_docs_can_still_be_enabled_locally(monkeypatch):
    """The fix must not make the schema unreadable during development."""
    c = _client(monkeypatch, docs_on=True)
    assert c.get("/openapi.json").status_code == 200
    assert c.get("/api-docs").status_code == 200


def test_enabling_docs_does_not_re_shadow_our_route(monkeypatch):
    """The built-ins must never be mounted at /docs, in any mode — that
    collision is what made the handwritten redirect dead code."""
    r = _client(monkeypatch, docs_on=True).get("/docs", follow_redirects=False)
    assert r.status_code == 301, "built-in docs are shadowing /docs again"
