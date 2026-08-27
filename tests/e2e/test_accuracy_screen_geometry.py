"""Stage-4 computed-geometry gate for the public accuracy screen.

measure-dont-look (~/.claude/skills/measure-dont-look/SKILL.md): a visual
audit catches what looks wrong and a heuristics pass catches what behaves
wrong; neither can see a defect that looks deliberate. This surface renders
in two regimes — a fixed 430x932 canvas under a transform on mobile, and
natively on desktop — and two regimes means two sets of constants.

What this found the first time it ran, both screenshot-clean:

  * The FIRST click on "See how accurate it is first" was silently swallowed.
    The email field autofocuses; pressing the link blurred it, validation
    rendered "Email is required", the layout shifted, and the button moved
    out from under the pointer before `click` fired. Only the second click
    worked. Every visitor would have hit it. Fixed with preventDefault on
    mousedown; red-proofed by removing it and watching this go red.

  * '← Back' rendered underneath the status-bar clock on iPhone.

Assertions are RELATIONSHIPS (tile widths agree; nothing overflows the
viewport), not absolute pixels, so a redesign does not produce false
failures.

Run:  pytest tests/e2e/test_accuracy_screen_geometry.py --base-url=...
Needs a running server; skipped when one is not reachable.
"""
import os
import urllib.request

import pytest

BASE = os.getenv("NGW_E2E_BASE_URL", "http://127.0.0.1:8099")
VIEWPORTS = [("mobile", 390, 844), ("desktop", 1440, 900)]


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/api/gallery", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.benchmark,  # deselected by default; needs a live server
    pytest.mark.skipif(not _server_up(), reason=f"no server at {BASE}"),
]


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize("name,w,h", VIEWPORTS)
def test_first_click_reaches_the_proof_surface(browser, name, w, h):
    """The FIRST click must land. This is the assertion that went red."""
    pg = browser.new_page(viewport={"width": w, "height": h})
    try:
        pg.goto(BASE + "/ui", wait_until="networkidle")
        pg.get_by_text("See how accurate it is first", exact=False).first.click()
        pg.wait_for_timeout(1400)
        assert pg.locator('[data-testid="accuracy-screen"]').count() == 1, (
            f"{name}: first click did not reach the accuracy screen — it is "
            "being swallowed by a blur-triggered re-render"
        )
    finally:
        pg.close()


@pytest.mark.parametrize("name,w,h", VIEWPORTS)
def test_proof_surface_geometry_holds(browser, name, w, h):
    pg = browser.new_page(viewport={"width": w, "height": h})
    try:
        pg.goto(BASE + "/ui", wait_until="networkidle")
        pg.get_by_text("See how accurate it is first", exact=False).first.click()
        pg.wait_for_selector('[data-testid="accuracy-grid"]', timeout=20000)
        pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        pg.wait_for_timeout(800)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(800)

        m = pg.evaluate(
            """() => {
              const q = s => document.querySelector(s);
              const r = el => el ? el.getBoundingClientRect().toJSON() : null;
              const tiles = Array.from(document.querySelectorAll('[data-testid="accuracy-tile"]'));
              const back = q('[data-testid="accuracy-back"]');
              const b = back && back.getBoundingClientRect();
              const hit = b ? document.elementFromPoint(b.x + b.width/2, b.y + b.height/2) : null;
              return {
                vw: innerWidth,
                scrollW: document.documentElement.scrollWidth,
                tiles: tiles.length,
                widths: tiles.slice(0, 8).map(t => Math.round(t.getBoundingClientRect().width)),
                backRect: r(back),
                // el === hit || el.contains(hit) -- NOT hit.contains(el),
                // which counts ancestors and passes everything.
                backHit: !!(back && hit && (back === hit || back.contains(hit))),
              };
            }"""
        )

        assert m["tiles"] > 0, f"{name}: no entry tiles rendered"

        # The page must never scroll sideways.
        assert m["scrollW"] <= m["vw"] + 1, (
            f"{name}: page overflows horizontally — scrollWidth {m['scrollW']} > viewport {m['vw']}"
        )

        # Sibling tiles share one measure (relationship, not a pixel value).
        widths = set(m["widths"])
        assert len(widths) <= 2, (
            f"{name}: entry tiles do not share a measure — widths {sorted(widths)}"
        )

        # '← Back' must be reachable, not painted under the status bar or
        # covered by another element.
        assert m["backHit"], f"{name}: the Back control is not the element at its own center"
        assert m["backRect"]["y"] >= 24, (
            f"{name}: Back sits at y={m['backRect']['y']}, inside the status-bar strip"
        )
    finally:
        pg.close()


@pytest.mark.parametrize("name,w,h", VIEWPORTS[:1])
def test_misses_are_actually_rendered(browser, name, w, h):
    """Claim ledger #3: "Misses are shown. A proof page that hides its failures
    is not proof."

    True today with nothing stopping a future filter from quietly dropping the
    failing entries -- which is exactly how a proof page stops being one. If the
    payload reports misses, at least one must reach the screen.
    """
    import json
    import urllib.request

    with urllib.request.urlopen(f"{BASE}/api/gallery", timeout=10) as r:
        payload = json.load(r)
    expected_misses = payload["scored"] - payload["hits"]
    if expected_misses == 0:
        pytest.skip("no misses in the current corpus — nothing to assert")

    pg = browser.new_page(viewport={"width": w, "height": h})
    try:
        pg.goto(BASE + "/ui", wait_until="networkidle")
        pg.get_by_text("See how accurate it is first", exact=False).first.click()
        pg.wait_for_selector('[data-testid="accuracy-grid"]', timeout=20000)
        pg.wait_for_timeout(800)
        text = pg.inner_text('[data-testid="accuracy-grid"]')
        shown = text.upper().count("MISSED")
        assert shown >= 1, (
            f"payload reports {expected_misses} miss(es) but none rendered — "
            "the proof page is hiding its failures"
        )
        assert shown == expected_misses, (
            f"payload reports {expected_misses} miss(es), screen shows {shown}"
        )
    finally:
        pg.close()
