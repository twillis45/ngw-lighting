"""Every screen key the shell navigates to must have a case that renders it.

Found 2026-08-31. Day1DemoApp.jsx:1813 passed setScreen('sessionLog') and
setScreen('lookLibrary') to the Lab support panel. The switch cases are
'journal' and 'looklibrary' — camelCase versus lowercase, no normalisation in
setScreen, and an unknown key falls through to `default:` which renders
HomeScreen.

So both buttons silently bounced the user to Home. Not an error, not a blank
screen — a plausible-looking navigation to the wrong place, which is the
hardest kind to notice. Correct handlers (handleSessionLog, handleLookLibrary)
already existed with the right keys; that one line bypassed them.

This is in the DEFAULT shell, not behind a legacy flag.

Enumerates rather than naming the two keys, because naming them would only
prove the ones already fixed.
"""
import re
from pathlib import Path

import pytest

SHELL = Path(__file__).resolve().parent.parent / "ui" / "src" / "screens" / "Day1DemoApp.jsx"


def _code() -> str:
    """Source minus // comments — a key named in a comment is not navigation."""
    return "\n".join(l.split("//", 1)[0] for l in SHELL.read_text(encoding="utf-8").splitlines())


def test_every_navigated_key_has_a_case():
    if not SHELL.exists():
        pytest.skip("shell not present")
    code = _code()
    targets = {m.group(1) for m in re.finditer(r"setScreen\(\s*['\"]([A-Za-z_]+)['\"]\s*\)", code)}
    cases = {m.group(1) for m in re.finditer(r"case\s+['\"]([A-Za-z_]+)['\"]\s*:", code)}

    # Guard the zero: if neither regex matched, this test is asserting nothing.
    assert len(targets) > 5, f"only {len(targets)} setScreen targets found — regex is stale"
    assert len(cases) > 5, f"only {len(cases)} switch cases found — regex is stale"

    orphans = sorted(targets - cases - {"home"})
    assert not orphans, (
        "these screen keys are navigated to but have no case, so they fall "
        f"through to default: and silently render Home instead: {orphans}")


def test_no_camelcase_screen_key_is_used():
    """The specific shape of the bug: the cases are all lowercase, so any
    camelCase target is guaranteed to miss."""
    if not SHELL.exists():
        pytest.skip("shell not present")
    code = _code()
    camel = sorted({
        m.group(1) for m in re.finditer(r"setScreen\(\s*['\"]([A-Za-z]+)['\"]\s*\)", code)
        if any(c.isupper() for c in m.group(1))
    })
    assert not camel, (
        f"screen keys are lowercase everywhere else; these will never match a "
        f"case: {camel}")
