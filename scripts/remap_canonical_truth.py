#!/usr/bin/env python3
"""Remap non-canonical reference-dataset ground-truth labels to canonical pattern_ids.

TX guardrail: source_context (golden_hour, overcast_natural) and modifier
(gobo) concepts must not sit as peer pattern outputs.  Scoring pattern
accuracy against them is a category error.

Only unambiguous remaps are applied -- each is justified by the entry's own
recorded notes, not by its slug.  Genuine judgment calls are REPORTED, not
guessed, because inventing ground truth is worse than leaving it flagged.
"""
import glob
import json
import os
import sys

# entry slug -> (new expected_pattern, justification from that entry's notes)
REMAP = {
    "overfill_flat": ("flat", "notes: 'Over-filled flat lighting - multiple sources cancel shadows, very low contrast'"),
    "white_seamless_catalog": ("flat", "notes: 'even studio lighting, e-commerce/catalog style'"),
    "rim_only": ("rim", "'rim_only' is a stale alias of canonical 'rim' (Rim / Edge Light)"),
    "window_negative_fill": ("window_negative_fill", "canonical pattern of that exact name exists and is already in acceptable_patterns"),
    "overcast_natural": ("flat", "notes: 'soft diffused light, no harsh shadows' == Flat Lighting"),
    "gobo": ("projected", "engine/enums.py records gobo_projection -> projected as a migration alias; "
                          "'projected' is the canonical LightingPattern for gobo/interrupted light. "
                          "The stale label was showing as a MISS on the public accuracy page."),
}

# Stale aliases appearing inside acceptable_patterns lists.
ALIASES = {"flat_fashion": "flat", "rim_only": "rim"}

NEEDS_HUMAN_CALL = {
    "golden_hour": "source_context, not a pattern; acceptable lists loop/rembrandt/short -- needs the image to choose",
    "hurley_triangle": "'3 lights, two upper and one lower, even wrap' -- 'clamshell' or 'butterfly'?",
}


def canonical_ids():
    data = json.load(open("data/lighting_patterns.json"))
    pats = data if isinstance(data, list) else data.get("patterns") or []
    return {p["pattern_id"] for p in pats}


def main(apply_changes):
    canon = canonical_ids()
    changed = []
    for path in sorted(glob.glob("data/reference_dataset/*/*/metadata.json")):
        slug = os.path.basename(os.path.dirname(path))
        meta = json.load(open(path))
        gt = meta.get("ground_truth") or {}
        before = json.dumps(gt, sort_keys=True)

        if slug in REMAP:
            gt["expected_pattern"] = REMAP[slug][0]

        acc = gt.get("acceptable_patterns") or []
        if acc:
            mapped, seen = [], set()
            for a in acc:
                a2 = ALIASES.get(a, a)
                # keep 'unknown' (a legitimate non-answer) and canonical ids only
                if a2 != "unknown" and a2 not in canon:
                    continue
                if a2 not in seen:
                    seen.add(a2)
                    mapped.append(a2)
            # never let a remap orphan its own expected value
            exp = gt.get("expected_pattern")
            if exp and exp not in mapped:
                mapped.insert(0, exp)
            gt["acceptable_patterns"] = mapped

        if json.dumps(gt, sort_keys=True) != before:
            changed.append(slug)
            meta["ground_truth"] = gt
            if apply_changes:
                json.dump(meta, open(path, "w"), indent=2)

    print(("APPLIED" if apply_changes else "DRY RUN") + f": {len(changed)} entries changed")
    for s in changed:
        print(f"   {s}" + (f"  -> {REMAP[s][0]}   ({REMAP[s][1]})" if s in REMAP else "   (acceptable_patterns cleaned)"))
    print(f"\nLEFT FOR A HUMAN CALL ({len(NEEDS_HUMAN_CALL)}):")
    for s, why in NEEDS_HUMAN_CALL.items():
        print(f"   {s}: {why}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
