"""The gold set may only contain entries a human approved.

Found 2026-08-31. scripts/intelligence/build_gold_set.py never checked
approval_status, and it fell back to `pattern_id` when a ground_truth block was
absent. Together those two gaps put images__5_ in the manifest labelled "loop"
— an entry whose approval_status is "rejected" with rejection_reason
"gold issue not a clear loop or butterfly pattern".

So a human's verdict of "there is no clear pattern here" became the label.

That fallback is the mechanism worth naming: pattern_id is a filing convention
derived from the directory, ground_truth is a claim someone checked. A gold set
may only contain the second.

This matters more than an offline manifest normally would: seed_benchmark_cases
reads it, and production currently has ZERO benchmark cases. Seeding from the
old manifest would have promoted a rejected image into a scored benchmark case
with a wrong label.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "gold_set" / "manifest.json"
DATASET = ROOT / "data" / "reference_dataset"


def _entries():
    if not MANIFEST.exists():
        pytest.skip("gold set manifest not present")
    m = json.loads(MANIFEST.read_text())
    return m.get("entries") or m.get("gold_set") or []


def _meta_for(entry_id):
    for p in DATASET.glob("*/*/metadata.json"):
        d = json.loads(p.read_text())
        if d.get("reference_id", p.parent.name) == entry_id or p.parent.name == entry_id:
            return d
    return None


def test_no_rejected_or_draft_entry_is_in_the_gold_set():
    bad = []
    for e in _entries():
        d = _meta_for(e["id"])
        if d is None:
            continue
        status = d.get("approval_status")
        if status and status != "approved":
            bad.append(f'{e["id"]}: approval_status={status}')
    assert not bad, f"non-approved entries in the gold set: {bad}"


def test_every_entry_has_real_ground_truth_not_a_filing_convention():
    """The fallback to pattern_id is what labelled a rejected image. An entry
    without ground_truth.expected_pattern must not be in the gold set at all."""
    bad = []
    for e in _entries():
        d = _meta_for(e["id"])
        if d is None:
            continue
        gt = (d.get("ground_truth") or {}).get("expected_pattern")
        if not gt:
            bad.append(f'{e["id"]}: no ground_truth.expected_pattern')
        elif gt != e.get("expected_pattern"):
            bad.append(f'{e["id"]}: manifest says {e.get("expected_pattern")!r}, truth says {gt!r}')
    assert not bad, bad


def test_the_builder_itself_checks_approval():
    """Structural: the regeneration script must keep the check. A manifest that
    is correct today and a builder that would reproduce the bug is not a fix."""
    src = (ROOT / "scripts" / "intelligence" / "build_gold_set.py").read_text()
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert "approval_status" in code, "build_gold_set.py no longer checks approval_status"
    assert 'or d.get("pattern_id")' not in code, (
        "the pattern_id fallback is back — that is how an unlabelled entry "
        "acquires a label")


def test_the_manifest_is_not_stale():
    """It was five months stale: 29 on disk vs 33 regenerated, 15 differing."""
    import subprocess, sys, tempfile, shutil
    before = MANIFEST.read_text()
    backup = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    backup.write(before.encode()); backup.close()
    try:
        subprocess.run([sys.executable, "scripts/intelligence/build_gold_set.py"],
                       cwd=ROOT, capture_output=True, check=True)
        after = MANIFEST.read_text()
    finally:
        shutil.copy(backup.name, MANIFEST)
    a, b = json.loads(before), json.loads(after)
    ids = lambda m: {e["id"] for e in (m.get("entries") or m.get("gold_set") or [])}
    assert ids(a) == ids(b), (
        f"manifest is stale — regenerating changes it. "
        f"missing: {sorted(ids(b) - ids(a))}, extra: {sorted(ids(a) - ids(b))}")
