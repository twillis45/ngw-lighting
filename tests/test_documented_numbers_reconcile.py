"""Load-bearing numbers in the docs must match what the code produces.

Found 2026-08-31. Several figures in files CLAUDE.md names as authorities had
drifted, and nothing re-derived any of them:

  docs/TAXONOMY_TRUTH.md   "42 enum classes"        actual: 6
  docs/CLAIM_LEDGER.md     "18/34, 30/34"           actual: 18/33, 30/33
  docs/CLAIM_LEDGER.md     "23 of 34 monochrome"    actual: 14 of 34

The monochrome one is the instructive case. 23 matches NO definition anyone can
reproduce: the engine's own detector says 14, a plain chroma threshold says 11
strict / 16 including near-monochrome. The number outlived the method that
produced it, which is how a figure becomes unfalsifiable.

This test re-derives each figure and compares. A drifted number now fails
rather than sitting there looking authoritative.
"""
import enum
import glob
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TAX = ROOT / "docs" / "TAXONOMY_TRUTH.md"
LEDGER = ROOT / "docs" / "CLAIM_LEDGER.md"


def test_taxonomy_doc_enum_count_matches_the_module():
    if not TAX.exists():
        pytest.skip("TAXONOMY_TRUTH.md not present")
    import engine.taxonomy as t
    actual = sum(
        isinstance(getattr(t, n), type) and issubclass(getattr(t, n), enum.Enum)
        for n in dir(t)
    )
    m = re.search(r"\*\*(\d+) enum classes\*\*", TAX.read_text())
    assert m, "the enum-class count is no longer stated in a checkable form"
    assert int(m.group(1)) == actual, (
        f"TAXONOMY_TRUTH.md says {m.group(1)} enum classes; the module has {actual}")


def test_taxonomy_doc_pattern_count_matches_the_module():
    if not TAX.exists():
        pytest.skip("TAXONOMY_TRUTH.md not present")
    from engine.taxonomy import LightingPattern
    m = re.search(r"\*\*(\d+) values\*\*", TAX.read_text())
    assert m, "the LightingPattern value count is no longer stated"
    assert int(m.group(1)) == len(list(LightingPattern))


def test_ledger_corpus_denominator_matches_the_scoreable_corpus():
    """It said /34 while the gate scores 33 — the unscoreable entry was
    excluded on 2026-08-31 and the ledger was not updated."""
    if not LEDGER.exists():
        pytest.skip("CLAIM_LEDGER.md not present")
    scoreable = sum(
        1 for p in glob.glob(str(ROOT / "data/reference_dataset/*/*/metadata.json"))
        if (json.load(open(p)).get("ground_truth") or {}).get("expected_pattern")
    )
    text = LEDGER.read_text()
    stale = re.findall(r"\b\d+/(\d+)\s+(?:exact|acceptable)", text)
    bad = [d for d in stale if int(d) != scoreable]
    assert not bad, (
        f"the ledger quotes accuracy over /{set(bad)} while {scoreable} entries "
        "are scoreable")


def test_ledger_monochrome_count_matches_the_engines_own_detector():
    """The figure must come from the detector the PRODUCT uses, and the ledger
    must name it — 23 survived precisely because no method was recorded."""
    if not LEDGER.exists():
        pytest.skip("CLAIM_LEDGER.md not present")
    imgs = sorted(glob.glob(str(ROOT / "data/reference_dataset/*/*/image.jpg")))
    if not imgs:
        pytest.skip("corpus not present")
    from PIL import Image
    from engine.image_analysis import _is_grayscale_like
    actual = sum(1 for p in imgs if _is_grayscale_like(Image.open(p).convert("RGB")))
    text = LEDGER.read_text()
    m = re.search(r"\*\*(\d+) of (\d+)\*\* references are monochrome", text)
    assert m, "the monochrome figure is no longer stated in a checkable form"
    assert (int(m.group(1)), int(m.group(2))) == (actual, len(imgs)), (
        f"ledger says {m.group(1)}/{m.group(2)}; the engine's own detector "
        f"says {actual}/{len(imgs)}")
    assert "_is_grayscale_like" in text, (
        "the ledger must NAME the detector that produced the number — an "
        "unattributed count is how 23 survived")
