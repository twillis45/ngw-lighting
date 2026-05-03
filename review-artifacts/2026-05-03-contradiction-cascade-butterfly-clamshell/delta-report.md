# Branch B — Contradiction Cascade Butterfly/Clamshell Delta Report

**Date:** 2026-05-03  
**Branch:** `fix/contradiction-cascade-butterfly-clamshell`  
**Base commit:** `8986f10` (v0.1.0-rc3.1 main)  
**Benchmark baseline:** `benchmarks/results/run_20260503_224611.json` (34/10/4/0/0)  
**Benchmark post-investigation:** `benchmarks/results/run_20260503_232009.json` (34/10/4/0/0)

---

## 1. Objective

Investigate and fix `bounded_butterfly_vs_clamshell_beauty`:

| Case | Expected | Current | Status |
|------|----------|---------|--------|
| `bounded_butterfly_vs_clamshell_beauty` | bounded + butterfly/clamshell | classical + broad | ⛔ No safe fix (documented) |

---

## 2. Root Cause Analysis

### Failure Chain

The image is a clamshell/beauty setup (on-axis key above, fill below, near-zero shadows, bilateral highlights). The engine produces `broad/classical` via this chain:

**Step 1 — Classifiers output wrong patterns:**
| Classifier | Output | Confidence |
|-----------|--------|------------|
| `reference_read` | broad | ~0.85 |
| `lighting_inference` | loop | 0.30 |
| `cue_inference` | short | 0.60 |
| `light_structure` | loop | — |

No classifier proposes butterfly or clamshell. This is the foundational problem: all three primary classifiers are reading the face-turn and catchlight geometry and inferring lateral-key patterns, when the true setup is frontal/on-axis.

**Step 2 — `flat_bilateral` paradox fires (correctly):**

```
shadow_den=0.001 < 0.04 ✓
lr_asym=0.002    < 0.04 ✓
hs_sym=0.871     > 0.80 ✓
```

The `flat_bilateral` paradox is correct — the illumination is genuinely bilateral. It adds +0.35 contradiction to `short` and +0.35 to `broad`. This is the right physical reasoning: completely flat illumination contradicts pose-dependent directional patterns.

**Step 3 — Both primary candidates demoted:**

- `reference_read(broad)`: broad score = +0.40 (hl_width < 0.25) + 0.35 (flat_bilateral) = **0.75** ≥ 0.65 → **demoted**
- `cue_inference(short)`: short score = +0.40 (lr_asym < 0.08) + 0.35 (flat_bilateral) = **0.75** ≥ 0.65 → **cascade demoted**
- `catchlight_shadow_paradox` also fires: shadow→upper_left vs catchlight@2→upper_right

**Step 4 — Two-source shield cannot fire:**

The two-source shield requires `cue_inference agrees with reference_read on the SAME pattern`. But:
- reference_read said `broad`
- cue_inference said `short`
- They disagree → `_ci_agrees = False` → shield does not fire
- Demotion threshold stays at 0.65 (standard)

**Step 5 — `lighting_inference(loop, 0.30)` wins by default:**

With both reference_read and cue_inference demoted, `lighting_inference(loop)` wins at priority 1. Loop has a lower contradiction score (hs_sym = 0.871 and centroid checks create moderate contradiction but not enough to demote at 0.80 threshold).

**Step 6 — Pose resolver upgrades loop → broad:**

Face orientation analysis upgrades `loop` to `broad`, yielding final `broad(lighting_inference, 0.46)`.

**Step 7 — Mode stays CLASSICAL:**

Candidate credibility: broad=0.60, short=0.21. BOUNDED needs second ≥ 0.45 — not met.

---

## 3. Why No Safe Fix Exists

### Problem A: No butterfly/clamshell candidate

The contradiction scorer gives `clamshell` a score of **0.0** (it is not contradicted by any available signal). But the contradiction scorer only evaluates **existing candidates** — it cannot create new ones. No upstream classifier (reference_read, lighting_inference, cue_inference, light_structure) ever proposes `butterfly` or `clamshell` for this image. Without a candidate in the resolver list, no score can be assigned, and no credibility entry is created.

The only fix would be to add a new signal-based classifier that detects clamshell from raw CV signals. This is a resolver architecture change — outside the scope of this branch.

### Problem B: Even if pattern were fixed, BOUNDED mode would not fire

BOUNDED mode requires two candidates with credibility ≥ 0.55 / ≥ 0.45 and spread ≤ 0.20. The credibility scorer is driven by upstream-classifier pattern-match agreement. Credibility for a hypothetical `clamshell` candidate:

```
baseline:              0.50
reference_read match:  0     (rr says broad, not clamshell)
lighting_inf match:    0     (li says loop, not clamshell)
cue_inf match:         0     (ci says short, not clamshell)
light_structure match: 0     (ls says loop, not clamshell)
Total:                 0.50  — below 0.55 threshold
```

No upstream support = credibility below BOUNDED gate floor regardless of what the post-resolver pattern says.

### Problem C: Post-resolver upgrade won't fix mode

Even if we added a post-resolver "high-symmetry rescue" that upgrades the authoritative pattern to `clamshell`, `compute_candidate_credibility` runs from `pc.primary + pc.alternates` (the resolver's internal list), not from `result.authoritative_pattern`. The credibility values would remain unchanged, BOUNDED would still not fire, and the rescue would change the pattern label but not the verdict.

### Problem D: `flat_bilateral` paradox prevents forgiveness

`_paradox_blocks_forgiveness = _any_paradox_active OR _catchlight_paradox`. Two paradoxes are active (flat_bilateral + catchlight_shadow_paradox). Demotion forgiveness is blocked. The short credibility (0.21) cannot be rescued, so no path to two credible classical candidates exists.

---

## 4. Evaluated Fix Options

| Fix | Would it fix pattern? | Would it fix mode? | Safe? |
|-----|-----------------------|--------------------|-------|
| Guard `primary_shadow_direction` butterfly contradiction to require shadow_den ≥ 0.05 | No — nobody proposes butterfly | No | N/A |
| Post-resolver high-symmetry rescue: upgrade short/loop/broad → butterfly | Possibly | No (credibility unchanged) | Risky without mode fix |
| Add signal-geometry clamshell candidate in resolver | Yes, potentially | Maybe (if credibility ≥ 0.55) | Architecture change — out of scope |
| Add new BOUNDED gate specifically for high-symmetry beauty setups | Pattern would still be broad | Yes, but non-principled | Hard-coded bypass — violates guardrails |
| Fix `_ci_agrees` to compare against all sources (not just reference_read) | No direct effect on butterfly/clamshell | Unlikely | Behavioral change for many cases |

**No evaluated fix is both safe and effective at the mode-classifier layer.**

---

## 5. Code Changes Made

**None.** No safe, generalizable rule was found. The investigation is complete.

---

## 6. Benchmark Delta

| Metric | Baseline (RC3.1) | Branch B | Delta |
|--------|-----------------|----------|-------|
| PASS | 34 | 34 | 0 |
| SOFT_PASS | 10 | 10 | 0 |
| FAIL | 4 | 4 | 0 |
| ERROR | 0 | 0 | 0 |
| Pass rate | 87.5% | 87.5% | 0 |

**No regressions.** Identical results. No sentinel cases affected.

**Mode confusion matrix (Branch B):**
- Mode correctness: 97.9% (47/48) — unchanged
- CLA→HYB false-positive: 0/37 = 0.0% ✅
- HYB→CLA under-decompose: 0/1 = 0.0% ✅
- INS→any false-negative: 0/5 = 0.0% ✅

---

## 7. Remaining FAILs (4 cases, all pre-existing)

| Case | Expected | Got | Reason | In Scope? |
|------|----------|-----|--------|-----------|
| `bounded_butterfly_vs_clamshell_beauty` | bounded+butterfly | classical+broad | No upstream classifier proposes butterfly/clamshell | Target — **no safe fix** |
| `bounded_loop_vs_short_jewelry_t1` | bounded (mode ✓) | short/bounded | Pattern check fail | Out of scope |
| `bounded_loop_vs_short_rihanna_t1` | bounded (mode ✓) | window_portrait/bounded | Pattern check fail | Out of scope |
| `hybrid_key_plus_hair_light_corporate_t1` | hybrid (mode ✓) | loop/hybrid | Pattern check fail | Out of scope |

---

## 8. Acceptance Status

Per task acceptance criteria:

- ⛔ `bounded_butterfly_vs_clamshell_beauty` — no safe fix at mode-classifier layer
- ✅ All 4 regression sentinels pass (rihanna, jewelry, rembrandt_bw, hybrid_corporate)
- ✅ No regressions in 44 other cases
- ✅ Full 48-case benchmark completed
- ✅ Root cause documented completely (two-level failure: no-candidate + no-credibility)
- ✅ All evaluated fix options documented with safety/effectiveness assessment

**Minimum acceptance met:** no-safe-fix finding documented more deeply than the RC3.1 report.

---

## 9. Required Upstream Work

To fix `bounded_butterfly_vs_clamshell_beauty`, two things must change upstream of the mode classifier:

**Fix A — Clamshell/butterfly classifier from CV signals:**
Add a signal-geometry classifier that proposes `clamshell` when:
- `shadow_den < 0.03` AND `lr_asym < 0.03` AND `hs_sym > 0.85` AND `fill_ratio > 0.85` AND catchlight at 11/12/1

This classifier would create a clamshell candidate in the resolver and provide a credibility evidence match.

**Fix B — Credibility evidence for signal-geometry patterns:**
Extend `compute_candidate_credibility` to include signal-geometry pattern matches as evidence. Currently only cue_inference, light_structure, lighting_inference, and reference_read feed the evidence accumulator. A fifth evidence path from high-confidence CV signals would allow clamshell to reach ≥ 0.55 credibility without requiring VLM support.

**Without both A and B**, BOUNDED mode cannot fire for this image with the current architecture.

**Recommended tracking:** Open separate ticket. Tag: `engine/resolver` and `engine/credibility`. Not a mode-classifier issue — this is a coverage gap in upstream pattern generation.

---

## 10. Recommendation

**Do not merge.** No code was changed. Close branch with this investigation as the deliverable.

Open a tracked ticket for the upstream resolver + credibility work described in §9. Tag the `bounded_butterfly_vs_clamshell_beauty` failure as `upstream-blocker` in the benchmark system.
