"""A plan-gated capability with no way to reach it cannot be sold.

Written 2026-09-04, working the open item "Value metric for the paid tier".

The question was framed as open — speed, volume, deliverables and teams all
still on the table — but the CODE had already answered it and nobody had
written that down. Seven capability groups are gated by require_plan(), which
is a pricing decision expressed in Python:

    pro     /user/analyses            saved analyses
    studio  /api/teams                team management
    studio  /api/batch                batch processing
    studio  /api/studio/references    reference library
    studio  /api/api-keys             API keys
    studio  /api/brief                the shoot brief
    studio  /user/setups              saved setups

Measured against the SHIPPED bundle rather than the source tree — source can
contain a caller that never builds — four of those seven groups, thirteen of
the seventeen routes, have no surface at all. A buyer paying for Studio today
would get teams they cannot create, batch they cannot run, a reference library
they cannot open and API keys they cannot manage.

That is not a pricing question. Studio is a build-completion question, and
this test is what stops it being named on a pricing page before it is one.

BACKEND_ONLY below is the honest escape hatch: a capability may legitimately
have no UI (an API-key surface is plausibly CLI-first). It must be listed
DELIBERATELY, with a reason, which is the difference between a decision and an
omission.

WHAT THIS GATE DOES NOT CATCH, established by red-proofing rather than assumed:
it works at CAPABILITY-GROUP granularity (/api/teams, /api/batch), not per
route. A new plan-gated route added inside an ALREADY-REACHABLE group -- say
/api/brief/something-new -- does not fail this test. That was measured: the
first red-proof added exactly such a route and the gate stayed green.

Per-route matching is not the fix. The bundle contains the prefixes the client
calls, not every sub-path it constructs, so asserting per route would fail on
legitimate sub-routes and the gate would be turned off within a week. The real
limit is that this catches a new unreachable CAPABILITY, which is the thing
that gets written on a pricing page.
"""
import ast
import glob
import os
import re
from pathlib import Path

import pytest

# Gated capabilities with no UI surface ON PURPOSE. Each needs a reason.
BACKEND_ONLY = {
    "/api/api-keys": "API keys are for programmatic access; a UI is not required to use them.",
}

# Built, mounted, plan-gated -- and NOT shipped. Recorded rather than excused.
#
# This is the answer to "value metric for the paid tier", found in the code on
# 2026-09-04: Studio's value proposition is three-quarters unreachable. Each
# entry names what it blocks. The list is a RATCHET -- when one ships, the
# staleness test below fails and forces its removal, so this cannot quietly
# become permanent.
KNOWN_UNSHIPPED = {
    "/api/teams":   "5 routes. Team creation, invites, membership. Blocks naming "
                    "'teams' as a Studio value metric.",
    "/api/batch":   "2 routes. Batch analyze. Blocks naming 'volume' as anything "
                    "beyond the Pro analysis cap.",
    "/api/studio":  "3 routes. The reference library. Blocks naming a personal "
                    "library as a deliverable.",
}


def _bundle() -> str:
    files = sorted(glob.glob("static/ui/assets/index-*.js"), key=os.path.getmtime)
    if not files:
        pytest.skip("no built bundle present")
    return Path(files[-1]).read_text(errors="ignore")


def _gated_routes():
    """Every route behind require_plan(), by AST.

    A regex version of this undercounted 17 routes as 3, because it could not
    follow multi-line signatures — and reported a confident partial picture.
    """
    out = []
    for f in sorted(glob.glob("api/routes/*.py")):
        src = Path(f).read_text()
        m = re.search(r'APIRouter\(\s*prefix="([^"]+)"', src)
        pfx = m.group(1) if m else ""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            plan = None
            for d in list(node.args.defaults) + list(node.args.kw_defaults):
                for sub in (ast.walk(d) if d else []):
                    if (isinstance(sub, ast.Call)
                            and getattr(sub.func, "id", "") == "require_plan"
                            and sub.args):
                        plan = getattr(sub.args[0], "value", None)
            if not plan:
                continue
            url = pfx
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                    url = pfx + getattr(dec.args[0], "value", "")
            out.append((url, plan, os.path.basename(f)))
    return out


def _groups():
    g = {}
    for url, plan, f in _gated_routes():
        stem = "/".join(url.split("/")[:3]) or url
        g.setdefault(stem, {"plan": plan, "files": set(), "routes": []})
        g[stem]["files"].add(f)
        g[stem]["routes"].append(url)
    return g


def test_the_extractor_finds_the_gated_routes():
    """Presence check first. An enumerating gate that finds nothing passes
    every assertion below it vacuously -- the defect this repo has now found
    five times."""
    routes = _gated_routes()
    assert len(routes) >= 10, (
        f"only {len(routes)} plan-gated routes found; the extractor has "
        f"probably drifted and everything below is vacuous"
    )
    assert {p for _, p, _ in routes} >= {"pro", "studio"}


def test_every_paid_capability_is_reachable_or_declared_backend_only():
    b = _bundle()
    orphans = {
        stem: d for stem, d in _groups().items()
        if stem not in b and stem not in BACKEND_ONLY and stem not in KNOWN_UNSHIPPED
    }
    assert not orphans, (
        "plan-gated capabilities the shipped app cannot reach — these cannot "
        "honestly appear on a pricing page:\n" + "\n".join(
            f"  {s:<26} {d['plan']:<7} {len(d['routes'])} routes  "
            f"({', '.join(sorted(d['files']))})"
            for s, d in sorted(orphans.items())
        ) + "\n\nEither ship a surface, or add it to BACKEND_ONLY with a reason."
    )


def test_backend_only_entries_carry_a_reason():
    for stem, why in BACKEND_ONLY.items():
        assert why and len(why) > 20, f"{stem} is excused without a real reason"


def test_backend_only_does_not_excuse_a_capability_that_is_now_reachable():
    """A stale exemption hides the fact that the work landed."""
    b = _bundle()
    stale = [s for s in BACKEND_ONLY if s in b]
    assert not stale, f"reachable now; remove from BACKEND_ONLY: {stale}"


def test_known_unshipped_entries_are_still_genuinely_unshipped():
    """A ratchet, not a permanent excuse. When one of these ships, this fails
    and forces it out of the list -- so the gap can only ever shrink, and a
    capability cannot be quietly counted as both shipped and exempt."""
    b = _bundle()
    now_shipped = [s for s in KNOWN_UNSHIPPED if s in b]
    assert not now_shipped, (
        "these now have a surface — remove them from KNOWN_UNSHIPPED so the "
        f"gate protects them: {now_shipped}"
    )


def test_the_paid_tier_can_be_described_honestly():
    """What a pricing page may claim today.

    Studio's four capability groups: one reachable (brief), one deliberately
    backend-only (api-keys), two unshipped (teams, batch, references). So the
    only paid capability a buyer can exercise end-to-end is the Pro analysis
    cap plus the brief.
    """
    b = _bundle()
    groups = _groups()
    studio = {s: d for s, d in groups.items() if d["plan"] == "studio"}
    reachable = [s for s in studio if s in b]
    assert reachable, "no Studio capability is reachable at all"
    # If this ever exceeds the recorded set, Studio grew a surface and the
    # value-metric note in the artifact needs rewriting.
    assert len(reachable) <= 2, (
        f"Studio now reaches {len(reachable)} capabilities ({reachable}); the "
        f"recorded value-metric finding says 2 and is now stale"
    )
