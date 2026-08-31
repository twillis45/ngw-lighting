"""Experiment flags must actually reach the code that records events.

Found 2026-08-30. api/routes/paywall.py (three call sites) and
api/routes/recommend.py imported `get_flags_for_session` from `db.flags` — a
module that does not exist and never has. Every import sat inside
`try: ... except Exception: flags = {}`, so the ImportError was swallowed and
each call silently returned no flags.

The consequence was not a crash. It was that NO experiment event was ever
recorded for any pricing, paywall_timing, cta_messaging or paywall_value flag.
The experiments ran and produced zero data, and nothing reported it.

The logic existed the whole time, inline in the get_flags route handler. It
had simply never been extracted, so nothing outside that handler could call it.
"""
import re
from pathlib import Path

import pytest

from api.routes.flags import get_flags_for_session, load_flags

ROOT = Path(__file__).resolve().parent.parent


def test_the_function_the_callers_import_actually_exists():
    assert callable(get_flags_for_session)


def test_it_returns_the_shape_the_callers_expect():
    """paywall reads .get('enabled') and .get('group'); recommend reads variant."""
    flags = get_flags_for_session("some-session")
    assert flags, "no flags at all — data/flags.json missing or empty?"
    for name, d in flags.items():
        assert set(d) >= {"enabled", "variant", "group", "config"}, f"{name}: {set(d)}"


def test_the_conversion_groups_paywall_looks_for_are_present():
    """paywall only records events for these groups. If none exist, the
    experiment machinery is inert even with the import fixed."""
    groups = {d.get("group") for d in get_flags_for_session("s").values()}
    wanted = {"pricing", "paywall_timing", "cta_messaging", "paywall_value"}
    assert groups & wanted, f"none of {wanted} present; flag groups are {groups}"


def test_assignment_is_stable_for_a_session():
    a = get_flags_for_session("stable-session")
    b = get_flags_for_session("stable-session")
    assert {k: v["variant"] for k, v in a.items()} == {k: v["variant"] for k, v in b.items()}


def test_no_module_imports_a_phantom_db_flags():
    """The structural guard. The defect was an import of a module that does not
    exist, hidden by a bare except — so assert the phantom cannot come back."""
    offenders = []
    for f in list((ROOT / "api").rglob("*.py")) + list((ROOT / "engine").rglob("*.py")):
        code = "\n".join(l.split("#", 1)[0] for l in f.read_text(encoding="utf-8").splitlines())
        if re.search(r"\bfrom\s+db\.flags\b|\bimport\s+db\.flags\b", code):
            offenders.append(str(f.relative_to(ROOT)))
    assert not offenders, f"db/flags.py does not exist, but these import it: {offenders}"
