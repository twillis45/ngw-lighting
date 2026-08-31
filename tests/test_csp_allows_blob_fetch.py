"""The CSP must permit fetching the blob: URL the app itself creates.

Found 2026-08-31. connect-src listed 'self' and three https hosts but not
blob:. Day1DemoApp.jsx:1130 does fetch(imagePreview) on a blob: URL to convert
the just-analysed photo into a data URL for sessionStorage, so the recalled
LAST RESULT can display it. connect-src governs fetch(), 'self' does not cover
the blob: scheme, and the call site swallowed the rejection with
.catch(() => {}) — so the preview was never written and the recalled result
opened with no photo, with nothing anywhere saying why.

Measured in headless Chrome against both header values before fixing:
without blob: "BLOCKED — Failed to fetch"; with it, the fetch succeeds.

Adding a scheme source does not widen network reach: blob: URLs are
same-origin objects this page created itself.
"""
import re

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _csp() -> str:
    r = client.get("/api/health")
    csp = r.headers.get("content-security-policy")
    assert csp, "no CSP header at all"
    return csp


def _directive(name: str) -> str:
    m = re.search(rf"\b{name}\s+([^;]+)", _csp())
    assert m, f"{name} missing from CSP"
    return m.group(1).strip()


def test_connect_src_allows_blob():
    assert "blob:" in _directive("connect-src"), (
        "connect-src has no blob:, so fetch() on the app's own object URL is "
        "blocked and the recalled LAST RESULT loses its photo")


def test_img_src_still_allows_blob():
    """The other half of the same feature — rendering it once fetched."""
    assert "blob:" in _directive("img-src")


def test_the_csp_did_not_get_loosened_while_fixing_this():
    """A scheme source is narrow; a wildcard is not. Guard against the lazy fix."""
    connect = _directive("connect-src")
    assert "*" not in connect.replace("https://*.ingest.sentry.io", "").replace(
        "https://*.ingest.us.sentry.io", ""), f"unexpected wildcard in connect-src: {connect}"
    assert "'unsafe-eval'" not in _directive("connect-src")
    assert _directive("object-src") == "'none'"
