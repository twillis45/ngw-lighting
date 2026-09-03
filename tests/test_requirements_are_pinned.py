"""Nothing in requirements.txt may float.

The Dockerfile installs requirements.txt, so a `>=` line is re-resolved on
EVERY Render build and two identical commits can produce different production
images. Found by the stage-8 review board 2026-09-03, with real drift behind it:

    stripe      declared >=7.0.0    installed 15.1.0    eight majors
    openai      declared >=1.30.0   installed 2.36.0
    sentry-sdk  declared >=2.0.0    installed 2.59.0

The stripe one is the sharpest: the checkout path was being fixed for a
mischarge that same day while riding an unbounded SDK major.

requirements-lock.txt was DELETED rather than repaired. Nothing read it, and it
described a different dependency set than requirements.txt -- it added pytest,
sounddevice and opencv-python, and omitted stripe, python-jose, passlib, bcrypt,
sentry-sdk, google-auth and openai. A file whose name asserts reproducibility
while locking the wrong set is worse than no file, because someone will
eventually trust it.
"""
import re
from pathlib import Path

import pytest

REQ = Path("requirements.txt")

# A requirement line, ignoring blanks, comments and inline comments -- the
# comment case is not incidental: a scanner in this repo went false-green on
# 2026-08-31 by matching text inside comments.
_FLOAT = re.compile(r"^\s*([A-Za-z0-9_.\-]+)(\[[^\]]+\])?\s*(>=|>|~=)\s*", )


def _requirement_lines():
    for i, raw in enumerate(REQ.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if line:
            yield i, line


def test_no_requirement_floats():
    floating = [(i, l) for i, l in _requirement_lines() if _FLOAT.match(l)]
    assert not floating, "unpinned requirements (re-resolved on every deploy):\n" + "\n".join(
        f"  requirements.txt:{i}  {l}" for i, l in floating
    )


def test_every_requirement_is_pinned_with_double_equals():
    unpinned = [
        (i, l) for i, l in _requirement_lines()
        if "==" not in l and not l.startswith("-")
    ]
    assert not unpinned, "requirements without an == pin:\n" + "\n".join(
        f"  requirements.txt:{i}  {l}" for i, l in unpinned
    )


def test_the_detector_would_catch_a_float():
    """An enumerating gate whose pattern matches nothing looks exactly like a
    clean file. This proves the pattern works before the assertions above are
    believed."""
    for bad in ("stripe>=7.0.0", "openai >= 1.30.0", "PyYAML~=6.0", "sentry-sdk[fastapi]>=2.0.0"):
        assert _FLOAT.match(bad), f"detector missed {bad!r}"
    for ok in ("stripe==15.1.0", "PyYAML==6.0.3", "sentry-sdk[fastapi]==2.59.0"):
        assert not _FLOAT.match(ok), f"false positive on {ok!r}"


def test_comments_are_not_mistaken_for_requirements():
    """requirements.txt's own header documents the old >= specs. If the parser
    read comments, this file would fail against itself."""
    assert any(">=" in raw for raw in REQ.read_text().splitlines()), \
        "header no longer mentions >=; this test is no longer proving anything"
    assert not [(i, l) for i, l in _requirement_lines() if _FLOAT.match(l)]


def test_the_lock_file_that_locked_the_wrong_set_is_gone():
    assert not Path("requirements-lock.txt").exists(), (
        "requirements-lock.txt is back. If it is real now, delete this test and "
        "make something read it; if nothing reads it, it is a claim of "
        "reproducibility with nothing behind it."
    )
