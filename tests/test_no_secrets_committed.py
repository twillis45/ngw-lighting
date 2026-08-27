"""Secret scan — the executed check behind "no secrets in anything published".

Stage-5 (Security review) in the Path to Production spine calls for a secret
scan. There was none: the claim was an assertion, carried in a tracker as if
it were verified. This is the check.

Scope, and why each part is here:

  * TRACKED FILES — the obvious case.
  * GIT HISTORY — a secret survives its own deletion. Removing the line does
    not remove the blob.
  * THE SHIPPED CLIENT BUNDLE — anything in the browser bundle is public by
    definition. The chunks are ENUMERATED first: grepping "the bundle" when
    it is five files and finding nothing in two of them is a false zero, and
    that exact idiom is listed in measure-dont-look's false-negative table.

An absent result is a hypothesis, not a passing one — so this test fails
loudly if it cannot find the bundle to scan, rather than reporting zero.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Live-credential shapes. Deliberately narrow: a pattern loose enough to catch
# everything is a pattern noisy enough to be disabled.
PATTERNS = re.compile(
    r"(sk-[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|ghp_[A-Za-z0-9]{30,}"
    r"|AIza[0-9A-Za-z_-]{30,})"
)
BENIGN = re.compile(r"example|placeholder|your-|xxx|fake|dummy|sample", re.I)


def _hits(text: str):
    return [m.group(0) for m in PATTERNS.finditer(text) if not BENIGN.search(m.group(0))]


def test_env_file_is_not_tracked():
    r = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"],
                       cwd=REPO, capture_output=True)
    assert r.returncode != 0, ".env is tracked by git"


def test_env_never_appeared_in_history():
    r = subprocess.run(["git", "log", "--all", "--pretty=format:", "--name-only"],
                       cwd=REPO, capture_output=True, text=True)
    assert ".env" not in r.stdout.split(), ".env appears in git history"


def test_no_secrets_in_tracked_files():
    files = subprocess.run(["git", "ls-files"], cwd=REPO,
                           capture_output=True, text=True).stdout.split("\n")
    files = [f for f in files if f.strip()]
    assert files, "git ls-files returned nothing — the scan would be a false zero"

    found = []
    for f in files:
        p = REPO / f
        try:
            if not p.is_file() or p.stat().st_size > 4_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for h in _hits(text):
            found.append(f"{f}: {h[:12]}…")
    assert not found, f"credential-shaped strings in tracked files: {found[:5]}"


def test_no_secrets_in_the_shipped_client_bundle():
    """Anything in the browser bundle is public. Enumerate chunks, then scan
    every one — scanning 'the bundle' as if it were one file is a false zero."""
    assets = REPO / "static" / "ui" / "assets"
    if not assets.is_dir():
        pytest.skip("no built bundle present")

    chunks = sorted(assets.glob("*.js"))
    assert chunks, "asset dir exists but holds no .js — refusing to report a clean scan"

    found = []
    for c in chunks:
        for h in _hits(c.read_text(encoding="utf-8", errors="ignore")):
            found.append(f"{c.name}: {h[:12]}…")
    assert not found, (
        f"credential-shaped strings in {len(chunks)} scanned chunk(s): {found[:5]}"
    )
