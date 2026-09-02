"""A plain `npm run build` must produce a bundle with the real admin list.

Found 2026-08-31, fixed properly 2026-09-02. The frontend admin list is baked
at BUILD time from VITE_NGW_ADMIN_EMAILS, and that variable was set NOWHERE in
the repo — it had to be typed on the command line every time. It never was.

Every shipped bundle therefore carried only DEFAULT_ADMIN_EMAILS, so
admin@noguessworksystems.com was admin on the BACKEND (proven — the admin API
returns 200) and NOT admin in the UI. Every admin affordance was hidden from
the one account that needed them. Checked back through three earlier bundles:
admin@ had never appeared in any of them.

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
    """.gitignore excludes .env.* — this one needs an explicit un-ignore, and
    without it the file exists locally and vanishes for everyone else."""
    import subprocess
    r = subprocess.run(["git", "check-ignore", "ui/.env.production"],
                       cwd=ROOT, capture_output=True, text=True)
    # exit 0 with output on stdout means IGNORED; a negation yields exit 1.
    assert r.returncode != 0 or not r.stdout.strip().startswith("ui/"), (
        "ui/.env.production is gitignored, so the admin list is set only on "
        "this machine")


def test_every_declared_admin_is_in_the_shipped_bundle():
    bundle = _bundle()
    missing = [e for e in _declared_admins() if e not in bundle]
    assert not missing, (
        f"declared admin(s) absent from the built bundle: {missing} — the "
        "build ran without VITE_NGW_ADMIN_EMAILS and fell back silently")


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
