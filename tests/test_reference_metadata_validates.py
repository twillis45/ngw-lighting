"""The corpus must pass the validator that exists to protect it.

Found 2026-08-31: four dataset entries already on disk could not pass
validate_dataset_metadata. A gate that rejects the corpus it guards proves
nothing about that corpus — it is a gate nobody can turn on.

The cause was TWO pattern catalogs disagreeing:

    engine/taxonomy.py  LightingPattern        34 patterns   (the authority)
    data/patterns/pattern_catalog.json         25 patterns   (what the
                                                              validator read)

The JSON was 9 behind — axial, flat, gobo_projection, hybrid, projected, rim,
silhouette_key, triangle and unknown were all valid in the taxonomy and
rejected here. Two of the four failures were entries remapped to "projected"
earlier in the SAME session: the remap updated ground_truth, and this second
catalog had never heard of the new name.

CLAUDE.md names the taxonomy as authority for canonical pattern names, so the
validator now reads it directly. The JSON's other fields — name, category,
description, canonical_setup — are read by nothing in the codebase.
"""
import glob
import json
import os
from pathlib import Path

import pytest

from engine.reference_dataset import validate_dataset_metadata
from engine.reference_ingestion import _load_valid_pattern_ids
from engine.taxonomy import LightingPattern

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = sorted(glob.glob(str(ROOT / "data/reference_dataset/*/*/metadata.json")))


def test_the_validator_accepts_every_pattern_the_taxonomy_declares():
    """The drift itself. Nothing had ever compared the two lists."""
    valid = set(_load_valid_pattern_ids())
    taxonomy = {p.value for p in LightingPattern}
    missing = taxonomy - valid
    assert not missing, (
        "the ingestion validator rejects patterns the taxonomy declares valid, "
        f"so correct data cannot be ingested: {sorted(missing)}")


def test_every_dataset_entry_passes_its_own_validator():
    if not ENTRIES:
        pytest.skip("reference corpus not present")
    bad = []
    for p in ENTRIES:
        ok, errs = validate_dataset_metadata(json.load(open(p)))
        if not ok:
            bad.append(f"{os.path.basename(os.path.dirname(p))}: {errs[0][:90]}")
    assert not bad, (
        "entries already on disk fail the gate meant to protect them — "
        f"the gate proves nothing about the shipped corpus: {bad}")


def test_no_entry_still_carries_the_retired_gobo_label():
    """gobo was remapped to projected. A rename that updates ground_truth and
    leaves pattern_id behind is how the validator started rejecting real data."""
    if not ENTRIES:
        pytest.skip("reference corpus not present")
    stale = []
    for p in ENTRIES:
        d = json.load(open(p))
        if d.get("pattern_id") == "gobo":
            stale.append(os.path.basename(os.path.dirname(p)))
        gt = (d.get("ground_truth") or {}).get("expected_pattern")
        if gt == "gobo":
            stale.append(f"{os.path.basename(os.path.dirname(p))} (ground_truth)")
    assert not stale, f"retired label 'gobo' still present in: {stale}"
