#!/usr/bin/env python3
"""Store the engine's RESOLVED read for each reference-dataset entry.

Why this exists separately from reprocess_entry():

  reprocess_entry() calls run_extended_pipeline(), which produces the 30 raw
  vision-pass signals and writes signals.json. Those are intermediate signals.
  The engine's actual answer — the resolved pattern — comes from
  analyze_image() in the orchestrator, which runs the pipeline and then the
  classifier, solver and reconciler on top of it.

  Scoring the public accuracy gallery against a single pass
  (light_structure.pattern_name) measures one detector, not the product. This
  writes resolved.json so the gallery can score what the engine actually says.

Deliberately additive: it does not touch signals.json or reprocess_entry, so
nothing that already depends on those changes shape.

Usage:  python3 scripts/store_resolved_reads.py [--vlm]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Run from anywhere: scripts/ is not on the path when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from engine.orchestrator import analyze_image
from engine.reference_dataset import DATASET_ROOT

RUN_VLM = "--vlm" in sys.argv


def _g(obj, *names):
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return None


def main() -> int:
    root = Path(DATASET_ROOT)
    entries = []
    for pattern_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for entry in sorted(e for e in pattern_dir.iterdir() if e.is_dir()):
            if (entry / "image.jpg").exists() and (entry / "metadata.json").exists():
                entries.append(entry)

    print(f"{len(entries)} entries, run_vlm={RUN_VLM}", flush=True)
    ok = fail = 0
    t0 = time.perf_counter()

    for e in entries:
        try:
            ar = analyze_image(str(e / "image.jpg"), run_extended=True,
                               run_vlm=RUN_VLM, run_solver=True)
            li = getattr(ar, "lighting_intel", None)
            resolved = {
                "authoritative_pattern": _g(ar, "authoritative_pattern"),
                "pattern": _g(li, "pattern") if li else None,
                "pattern_confidence": _g(li, "pattern_confidence") if li else None,
                "light_count": _g(li, "light_count") if li else None,
                "run_vlm": RUN_VLM,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            (e / "resolved.json").write_text(json.dumps(resolved, indent=2))
            ok += 1
            print(f"  ok   {e.name:<24} {resolved['authoritative_pattern']} / {resolved['pattern']}", flush=True)
        except Exception as exc:
            fail += 1
            print(f"  FAIL {e.name}: {str(exc)[:70]}", flush=True)

    print(f"\n{ok} written, {fail} failed, {time.perf_counter() - t0:.0f}s")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
