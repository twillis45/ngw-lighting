"""Every API path the UI calls must exist on the server.

Found 2026-08-31. ui/src/api.js calls POST /api/merge-analyses on every
multi-image upload in ReferenceEvalScreen. That route does not exist and never
has — the only 'merge' route is /api/admin/systems/merge-patch.

It was dead three ways at once, which is why nobody noticed:
  1. the route 404s,
  2. both call sites swallow the failure with .catch(() => {}),
  3. the result is stored in a `consensus` state variable that is never read,
     so even a SUCCESSFUL response would have gone nowhere.

A phantom route is invisible from either side: the frontend looks like it has
a feature, the backend has no idea it is being called. Only comparing the two
finds it, which is what this does.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# ui/src explicitly. A repo-root src/ ALSO exists and is not the UI — the first
# version of this test preferred it, scanned the wrong tree, found zero API
# calls and passed. A false zero, and precisely the idiom this project keeps
# being bitten by: an absent result is a hypothesis, not a pass.
UI = ROOT / "ui" / "src"


def _server_paths() -> set:
    from main import app
    return {r.path for r in app.routes if hasattr(r, "path")}


def _matches(called: str, server: set) -> bool:
    """A called path matches a server route, allowing for {param} segments."""
    if called in server:
        return True
    cs = called.strip("/").split("/")
    for s in server:
        ss = s.strip("/").split("/")
        if len(ss) != len(cs):
            continue
        if all(b.startswith("{") or a == b for a, b in zip(cs, ss)):
            return True
    return False


def test_no_ui_call_targets_a_route_that_does_not_exist():
    server = _server_paths()
    assert server, "no routes collected — the app failed to import"

    called = {}
    for f in list(UI.rglob("*.js")) + list(UI.rglob("*.jsx")):
        code = "\n".join(l.split("//", 1)[0] for l in f.read_text(encoding="utf-8").splitlines())
        # Literal '/api/...' strings, and apiFetch('/...') which prefixes /api.
        for m in re.finditer(r"['\"`](/api/[a-zA-Z0-9/_\-{}$.]+)['\"`]", code):
            p = m.group(1)
            if "${" in p or "." in p.rsplit("/", 1)[-1]:
                continue          # templated, or a static asset
            called.setdefault(p, str(f.relative_to(UI)))

    # Guard the zero: if this found no calls at all, it scanned the wrong tree.
    assert len(called) > 20, (
        f"only {len(called)} API paths found under {UI} — this test is not "
        "looking at the UI, so a pass here means nothing")

    phantom = {p: f for p, f in called.items() if not _matches(p, server)}
    assert not phantom, (
        "the UI calls routes the server does not serve — every one of these "
        f"404s at runtime: {phantom}")
