"""A plain `npm run build` must produce a bundle with the real admin list.

Found 2026-08-31, fixed properly 2026-09-02. The frontend admin list is baked
at BUILD time from VITE_NGW_ADMIN_EMAILS, and that variable was set NOWHERE in
the repo — it had to be typed on the command line every time. It never was.

CORRECTED 2026-09-02, by an independent verifier: the claim originally made
here — "admin@ had never appeared in any shipped bundle" — is FALSE. The
pre-fix bundle (index-4acb2fb8.js, at e95d055^) contains
admin@noguessworksystems.com exactly once, inlined in the same position:

    function x4(){return aW("admin@noguessworksystems.com")||rW}

So the variable HAD been typed by hand for that build. The real defect is
narrower and still worth fixing: the value lived nowhere in the repo, so
whether any given build carried it depended on whether someone remembered.
Reproducibility was the fault, not absence.

That correction matters for what can be tested. A correct build and a build
that happened to be typed correctly produce IDENTICAL bundles, so no assertion
over the artifact can tell them apart. The bundle check below is a smoke test
and is documented as such; the guard that actually binds is that the value is
declared IN THE REPO and tracked.

The register's own "Enabling admin@" procedure lists this as step 5. It had
never been done, and a procedure step that depends on remembering is not a
procedure. ui/.env.production now carries the value, Vite loads it
automatically for a production build, and the correct bundle is what a bare
`npm run build` produces.

NOT A SECRET: the list already ships inside the bundle by design, and
ui/src/config/admin.js says so — it is a convenience gate, never a security
boundary. Authorisation is server-side against NGW_ADMIN_EMAILS.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENVFILE = ROOT / "ui" / ".env.production"
ASSETS = ROOT / "static" / "ui" / "assets"


def _declared_admins():
    if not ENVFILE.exists():
        pytest.fail(
            "ui/.env.production is missing — VITE_NGW_ADMIN_EMAILS is then set "
            "nowhere, and every build silently reverts to the fallback list")
    m = re.search(r"^VITE_NGW_ADMIN_EMAILS=(.+)$", ENVFILE.read_text(), re.M)
    assert m, "VITE_NGW_ADMIN_EMAILS is not set in ui/.env.production"
    return [e.strip() for e in m.group(1).split(",") if e.strip()]


def _bundle() -> str:
    if not ASSETS.is_dir():
        pytest.skip("no built bundle present")
    js = sorted(ASSETS.glob("index-*.js"))
    assert js, "no index-*.js in the built assets"
    return js[-1].read_text(encoding="utf-8", errors="ignore")


def test_the_env_file_is_tracked_not_gitignored():
    """.gitignore excludes .env.*, so this file needs an explicit un-ignore.
    Untracked, it works here and vanishes for everyone else.

    Rewritten 2026-09-02: this asked `git check-ignore`, which returns exit 1
    for any TRACKED file no matter what .gitignore says. The negation could be
    deleted and the test stayed green. Ask the question directly instead --
    is the file in the index?"""
    import subprocess
    r = subprocess.run(["git", "ls-files", "--error-unmatch", "ui/.env.production"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, (
        "ui/.env.production is NOT tracked by git, so VITE_NGW_ADMIN_EMAILS is "
        "set only on this machine and every other clone builds the fallback")


def test_every_declared_admin_is_in_the_shipped_bundle():
    """SMOKE TEST, and it cannot fail for the reason this file was written.

    A bundle built with the env file and one built by someone typing the
    variable are byte-identical, so this cannot distinguish them. It is kept
    because it still catches a build that carried NEITHER."""
    bundle = _bundle()
    missing = [e for e in _declared_admins() if e not in bundle]
    assert not missing, (
        f"declared admin(s) absent from the built bundle: {missing} — the "
        "build ran without VITE_NGW_ADMIN_EMAILS and fell back silently")


def test_no_retired_address_is_still_granted_by_the_shipped_bundle():
    """The discriminating half, and the one that red-proofs.

    todd@toddwillisphoto.com was removed from the server's NGW_ADMIN_EMAILS,
    which turned its presence in the bundle into a STALE GRANT -- a UI trusting
    an address the server no longer does. Any address in the bundle that is not
    in the declared list is that same fault."""
    bundle = _bundle()
    declared = set(_declared_admins())
    RETIRED = {"todd@toddwillisphoto.com"}
    still_granted = sorted(a for a in RETIRED - declared if a in bundle)
    assert not still_granted, (
        f"the shipped bundle still grants admin to {still_granted}, which the "
        "server does not trust — rebuild, and check DEFAULT_ADMIN_EMAILS")


def test_the_fallback_list_is_empty_so_a_missed_build_fails_closed():
    """DEFAULT_ADMIN_EMAILS was ['todd@toddwillisphoto.com'] and that address
    was retired from NGW_ADMIN_EMAILS, turning the fallback into a stale
    GRANT. An unconfigured allowlist is an absence of permission."""
    src = (ROOT / "ui" / "src" / "config" / "admin.js").read_text()
    m = re.search(r"DEFAULT_ADMIN_EMAILS\s*=\s*\[([^\]]*)\]", src)
    assert m, "DEFAULT_ADMIN_EMAILS is no longer declared as a literal list"
    assert not m.group(1).strip(), (
        f"the fallback grants admin to {m.group(1).strip()} — a build that "
        "misses the env var would silently trust an address the server does not")
