"""The waitlist sequence must not re-send, and must not mail dead addresses.

Found 2026-08-31 in production logs. A single startup emitted EIGHT emails —
day2, day5, day10 and day14 to each of two entries — and it repeated on every
deploy. Roughly ten deploys that day.

Two independent causes, both fixed:

1. engine/email_sequence.py held its own WAITLIST_PATH = Path("data/waitlist.json"),
   relative, resolving to /app/data in the container — IMAGE storage, rebuilt
   on every deploy. That file also holds the sequence's sent-state, so every
   deploy reset the state to the git-tracked copy and the sequence started
   over from day 2. This was the SECOND copy of a line fixed in
   api/routes/waitlist.py earlier the same day; one was fixed, the other was
   never looked for.

2. Both recipients are undeliverable by definition — smoketest@test.com and
   wltest+...@ngw.test. Every send was a hard bounce charged against a Resend
   sender with no reputation history.
"""
import re
from pathlib import Path

import pytest

from engine.email_sequence import _is_undeliverable

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("addr", [
    "smoketest@test.com",
    "wltest+1776725917@ngw.test",
    "someone@example.com",
    "x@anything.invalid",
    "y@thing.test",
])
def test_reserved_and_test_domains_are_never_mailed(addr):
    assert _is_undeliverable(addr) is True


@pytest.mark.parametrize("addr", [
    "real@noguessworksystems.com",
    "todd@toddwillisphoto.com",
    "someone@gmail.com",
])
def test_real_addresses_are_still_mailed(addr):
    """The guard must not become a reason nobody gets email."""
    assert _is_undeliverable(addr) is False


def test_sequence_state_is_not_stored_in_image_storage():
    """The re-send cause. A relative path resolves against WORKDIR into
    /app/data, which every deploy rebuilds — taking the sent-state with it."""
    src = ROOT / "engine" / "email_sequence.py"
    code = "\n".join(l.split("#", 1)[0] for l in src.read_text().splitlines())
    assert 'Path("data/waitlist.json")' not in code, (
        "sequence state is on a relative path again — every deploy will reset "
        "it and the whole sequence will re-send")
    assert "DATA_DIR" in code, "sequence state must follow DATA_DIR to the disk"


def test_no_writable_state_anywhere_uses_a_bare_relative_data_path():
    """Structural: this exact line existed in TWO files and only one was fixed.
    Enumerate rather than name files, because that is how the second was missed."""
    offenders = []
    for d in ("api", "engine", "db", "auth"):
        for f in (ROOT / d).rglob("*.py"):
            code = "\n".join(l.split("#", 1)[0] for l in f.read_text(encoding="utf-8").splitlines())
            for m in re.finditer(r'Path\("data/([a-z_]+\.json)"\)', code):
                # Only WRITABLE state matters; shipped read-only content is
                # correctly read from the image.
                if m.group(1) in {"waitlist.json"}:
                    offenders.append(f"{f.relative_to(ROOT)}: {m.group(0)}")
    assert not offenders, offenders
