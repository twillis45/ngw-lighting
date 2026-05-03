# Before State — `bounded_butterfly_vs_clamshell_beauty`

**Date:** 2026-05-03  
**Branch:** `fix/contradiction-cascade-butterfly-clamshell`  
**Base commit:** `8986f10` (v0.1.0-rc3.1 main)  
**Benchmark baseline:** `benchmarks/results/run_20260503_224611.json` (34/10/4/0/0)

---

## Case Definition

```json
{
  "image_path": "benchmarks/images/Tier 1/Clamshel:Beauty/48e9c9296a2a6204d41d1fd83c43c029.jpg",
  "expected": {"mode": "bounded"},
  "checks": {
    "pattern": {"expected": "butterfly", "acceptable": ["butterfly", "clamshell"]}
  }
}
```

**Category:** `bounded_two_credible_classical`

---

## Current Output (from `run_20260503_231610.json`)

```
mode:      FAIL — detected=classical, expected=bounded
pattern:   FAIL — detected=broad, expected=butterfly
key_dir:   FAIL — detected=upper_left, expected=top_center
```

---

## Classifier Outputs

| Classifier | Pattern | Confidence | Notes |
|-----------|---------|------------|-------|
| `reference_read` | broad | ~0.85 | source_direction=camera-left, ~45°, elevated |
| `lighting_inference` | loop | 0.30 | key_side=upper_left, key_pos=at or near 12 o'clock (on-axis) |
| `cue_inference.geometry` | short | 0.60 | key_dir=upper_left, key_height=high, light_count=3 |
| `light_structure` | loop | — | pattern_name from nose shadow geometry |

---

## Signal Readings

| Signal | Value |
|--------|-------|
| `shadow_density` | ~0.001 |
| `left_right_asymmetry` | ~0.002 |
| `highlight_symmetry (hs_sym)` | ~0.871 |
| `fill_ratio` | ~0.892 |
| `triangle_isolation` | low |
| `primary_shadow_direction` | upper_right, clock_angle=2, confidence=0.8 |
| `catchlight position` | 12 o'clock (on-axis — pattern resolved by nose shadow) |
| `flat_bilateral` paradox | **ACTIVE** (shadow_den < 0.04, lr_asym < 0.04, hs_sym > 0.80) |
| `catchlight_shadow_paradox` | **ACTIVE** (shadow→key=upper_left vs catchlight@2→key=upper_right) |

---

## Resolver State

```
pattern_candidates:
  primary:   broad (lighting_inference, 0.46)       ← loop upgraded via pose resolver
  alternate: short (cue_inference_demoted, 0.32)
  alternate: short (reference_read_demoted, 0.22)

contradictions:
  - "reference_read says 'short' but lighting_inference says 'loop'"
  - "signal contradiction (0.75) demoted reference_read 'short'"
  - "cascade (0.75) demoted cue_inference 'short'"
  - "catchlight_shadow_paradox: shadow→key=upper_left vs catchlight@2→key=upper_right"
```

**Note on reference_read:** Diagnostic prints `shadow_pattern=broad`; contradiction log records `reference_read says 'short'`. The active contradictions and demotion events are what the resolver operated on.

---

## Two-Source Shield State

| Parameter | Value |
|-----------|-------|
| `_li_conf_for_shield` | 0.30 (lighting_inference.pattern_confidence = 0.3) |
| `_ci_agrees` | **False** — cue_inference says short, reference_read says broad → disagree |
| Shield fires? | **No** — `_ci_agrees` must be True for shield to activate |
| Effective demotion threshold | 0.65 (standard, no shield raise) |
| short contradiction score | 0.75 ≥ 0.65 → demoted |

---

## Contradiction Score Breakdown: `short`

| Contribution | Value | Trigger |
|-------------|-------|---------|
| `lr_asym < 0.08` | +0.40 | lr_asym = 0.002 |
| `flat_bilateral` paradox | +0.35 | all three conditions met |
| **Total** | **0.75** | ≥ 0.65 threshold → demoted |

## Contradiction Score Breakdown: `broad`

| Contribution | Value | Trigger |
|-------------|-------|---------|
| `hl_width < 0.25` | +0.40 | (if hl_width < 0.25) |
| `flat_bilateral` paradox | +0.35 | all three conditions met |
| **Total** | **0.75** | ≥ 0.65 threshold → demoted |

## Contradiction Score Breakdown: `butterfly`

| Contribution | Value | Trigger |
|-------------|-------|---------|
| `shadow_den < 0.05 AND lr_asym < 0.05` | +0.50 | no visible nose shadow |
| `primary_shadow_direction` clock_angle=2 | +0.65 | lateral hours {2,3,4,8,9,10} |
| **Total** | **~1.15** → capped at 1.0 | no butterfly candidate exists |

## Contradiction Score Breakdown: `clamshell`

| Contribution | Value | Trigger |
|-------------|-------|---------|
| `lr_asym > 0.25` | 0 | lr_asym = 0.002 → no |
| `shadow_den > 0.40` | 0 | shadow_den = 0.001 → no |
| `flat_bilateral` | 0 | clamshell not listed in flat_bilateral handler |
| **Total** | **0.0** | no contradiction — but no candidate either |

---

## Candidate Credibility (after resolver)

| Pattern | Credibility | Notes |
|---------|------------|-------|
| broad | 0.60 | primary, no demotion events |
| short | 0.21 | demoted × 2, flat_bilateral blocks forgiveness |

BOUNDED predicate needs: c0 ≥ 0.55 AND c1 ≥ 0.45 AND spread ≤ 0.20 AND both patterns different AND max_evidence ≥ 2.  
Current: c1 = 0.21 — **BOUNDED cannot fire**.

---

## No-Candidate Verdict for butterfly/clamshell

No upstream classifier (reference_read, lighting_inference, cue_inference, light_structure) ever outputs `butterfly` or `clamshell`. Without a candidate, the credibility scorer never evaluates them. Even if butterfly/clamshell had zero contradictions (clamshell = 0.0, confirmed), they cannot enter the resolver ranking or the credibility list.

**Ambiguity flags:** `multiple_patterns_close_confidence` — signals ambiguity in the existing classifier space (short/broad/loop), but none of those signals point to butterfly/clamshell.
