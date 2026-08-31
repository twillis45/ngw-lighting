"""
build_gold_set.py  —  Generate data/gold_set/manifest.json from the reference dataset.

Walks data/reference_dataset/, reads every metadata.json that has a real
expected_pattern (not "unknown"), and writes a single gold set manifest.

Usage:
    python3 scripts/intelligence/build_gold_set.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REF_DATASET = REPO_ROOT / "data" / "reference_dataset"
GOLD_OUT    = REPO_ROOT / "data" / "gold_set" / "manifest.json"


def build() -> None:
    entries = []
    skipped = []

    for meta_path in sorted(REF_DATASET.rglob("metadata.json")):
        try:
            d = json.loads(meta_path.read_text())
        except Exception as e:
            skipped.append({"path": str(meta_path), "reason": str(e)})
            continue

        # A gold set is human-verified ground truth by definition, so a human
        # verdict of "rejected" must exclude the entry. This was never checked.
        # Found 2026-08-31: images__5_ carries approval_status "rejected" with
        # rejection_reason "gold issue not a clear loop or butterfly pattern",
        # and it was in the manifest labelled "loop" — a human saying "there is
        # no clear pattern here" turned into a label.
        approval = d.get("approval_status")
        if approval and approval != "approved":
            skipped.append({"path": str(meta_path), "reason": f"approval_status={approval}"})
            continue

        gt = d.get("ground_truth", {})
        # NO FALLBACK to pattern_id. That fallback is HOW the rejected entry got
        # its label: images__5_ has no ground_truth block at all, so
        # `gt.get(...) or d.get("pattern_id")` handed it the directory-derived
        # "loop". pattern_id is a filing convention; ground_truth is a claim
        # someone checked. A gold set may only contain the second.
        expected_pattern = gt.get("expected_pattern")
        if not expected_pattern or expected_pattern == "unknown":
            skipped.append({"path": str(meta_path), "reason": "no ground_truth.expected_pattern"})
            continue

        img_path = meta_path.parent / "image.jpg"
        if not img_path.exists():
            # Try alternate extensions
            for ext in (".png", ".jpeg", ".webp"):
                alt = img_path.with_suffix(ext)
                if alt.exists():
                    img_path = alt
                    break
            else:
                skipped.append({"path": str(meta_path), "reason": "no image file"})
                continue

        entries.append({
            "id": d.get("reference_id", meta_path.parent.name),
            "image_path": str(img_path.relative_to(REPO_ROOT)),
            "expected_pattern": expected_pattern,
            "acceptable_patterns": gt.get("acceptable_patterns", [expected_pattern]),
            "expected_light_count": gt.get("expected_light_count"),
            "acceptable_light_count_range": gt.get("acceptable_light_count_range"),
            "expected_key_direction": gt.get("expected_key_direction"),
            "dataset_tier": d.get("dataset_tier", "community"),
            "trust_score": d.get("entry_trust_score", 0.7),
            "difficulty": (d.get("benchmark_metadata") or {}).get("difficulty", "standard"),
            "known_challenges": (d.get("benchmark_metadata") or {}).get("known_challenges", []),
            "notes": d.get("notes", ""),
        })

    # Sort: gold tier first, then by pattern name
    entries.sort(key=lambda e: (0 if e["dataset_tier"] == "gold" else 1, e["expected_pattern"]))

    # Pattern coverage summary
    coverage: dict[str, int] = {}
    for e in entries:
        coverage[e["expected_pattern"]] = coverage.get(e["expected_pattern"], 0) + 1

    manifest = {
        "_generated_by": "scripts/intelligence/build_gold_set.py",
        "_description": (
            "Gold set: hand-labeled reference images for pattern accuracy benchmarking. "
            "Each entry has ground-truth expected_pattern and acceptable_patterns for "
            "boundary cases. Used by batch_runner.py and benchmark expansion."
        ),
        "total_entries": len(entries),
        "patterns_covered": len(coverage),
        "pattern_coverage": coverage,
        "skipped": len(skipped),
        "entries": entries,
    }

    GOLD_OUT.parent.mkdir(parents=True, exist_ok=True)
    GOLD_OUT.write_text(json.dumps(manifest, indent=2))

    print(f"Gold set: {len(entries)} entries, {len(coverage)} patterns")
    print(f"Skipped:  {len(skipped)}")
    print("Pattern coverage:")
    for p, cnt in sorted(coverage.items()):
        print(f"  {p:<35} {cnt}")

    if skipped:
        print("\nSkipped entries:")
        for s in skipped:
            print(f"  {s['path']} — {s['reason']}")

    print(f"\nWrote: {GOLD_OUT}")


if __name__ == "__main__":
    build()
