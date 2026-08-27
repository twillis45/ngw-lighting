# Taxonomy Separation — finishing a stalled migration

> Status: **proposal, not implemented.** Written 2026-08-27.
> Cross-refs: `docs/TAXONOMY_TRUTH.md`, `engine/enums.py`, CLAUDE.md §III (TX).

## Summary

The separation of `pattern` / `setup_family` / `source_context` that TX requires is
**already designed and partially implemented**. It stalled mid-cutover. This is not a
new taxonomy design — it is finishing a migration whose alias window expired on
**2026-05-06, three and a half months ago**.

`engine/enums.py:85` says it plainly:

```python
# ── Canonical geometry patterns (14 primary values) ──
# These describe shadow/highlight geometry only — not source type,
# environment, or equipment.  Source context lives in SourceContext enum.

# ── Migration aliases — read-only shims for replay records pre-cutover ──
# REMOVE after 2026-05-06 (30-day alias window).
```

`SourceContext` (`engine/enums.py:177`) exists, documents itself as "SEPARATE from
LightingPattern (which describes geometry only)", and carries the mapping table.

## What the evidence shows (measured 2026-08-26/27, 34-image corpus)

| | geometry-axis | setup-axis | both | neither |
|---|---|---|---|---|
| engine `authoritative_pattern` | 1 | 18 | 14 | 1 |
| corpus `expected_pattern` | 3 | 16 | 13 | 2 |

All 34 engine predictions are valid `LightingPattern` values — the engine is not
emitting garbage. The problem is that `LightingPattern`'s 34 values span four
different questions, so one field is asked to answer all of them:

- **geometry** — loop, rembrandt, butterfly, clamshell, split, broad, short, flat, triangle, shallow_loop
- **tonality** — high_key, low_key
- **source context** — golden_hour, overcast_natural, window_portrait
- **setup / named look** — athletic_rim_sculpt, editorial_rim_key, tabletop_soft_product,
  soft_editorial_key, short_fashion_key, bottle_backlight, strip_dramatic,
  bare_bulb_editorial, window_negative_fill
- **modifier-driven** — projected (formerly gobo_projection)

## Expired migration aliases still live

`engine/enums.py` marks these for removal after 2026-05-06. All still present, and the
reference corpus still uses several as ground truth:

| alias | documented destination | still used as corpus truth? |
|---|---|---|
| `rim_only` | → `rim` | was, remapped 2026-08-26 |
| `flat_fashion` | → `flat` | was (×2), remapped 2026-08-26 |
| `gobo_projection` | → `projected` | `gobo` still on 1 entry |
| `golden_hour` | → **source_context only; pattern resolved separately** | yes, 1 entry |
| `overcast_natural` | → **source_context only** | was, remapped 2026-08-26 |
| `axial` | → `ring_light` | no |

Note the last two: `golden_hour` and `overcast_natural` were never meant to be patterns.
They describe color temperature, falloff, and shadow density — source context. Any
attempt to score them as face patterns is a category error, and depresses every metric
computed from the corpus.

## Staged plan

Ordered smallest-risk first. Today's evidence for why order matters: a `face_box`
coordinate fix that was provably correct in isolation, and had a red-proofed unit test,
cost **10 points of corpus exact accuracy** (15/34 → 5/34) because its consumers were
calibrated against the old values. 2,641 passing tests did not see it.

**Stage 1 — classification (this document).** Analysis only. No code change.

**Stage 2 — record both axes in the corpus.** Add `expected_shadow_pattern` and
`expected_source_context` alongside the existing `expected_pattern`. Additive; nothing
reads the new fields yet, so nothing can regress. Resolves the 2 remaining invalid
labels (`gobo`, and the null-truth entry).

**Stage 3 — score per axis.** Extend `tests/test_corpus_accuracy_gate.py` to score each
axis separately, keeping the measured 17/34 exact and 29/34 acceptable baselines until
the per-axis denominators are measured. Baselines are measured, never aspirational.

**Stage 4 — engine emits separated fields.** Only now change what the engine returns:
`shadow_pattern` from the geometry axis, `source_context` from `SourceContext`,
setup identity separately. Every step guarded by the Stage 3 gate.

**Stage 5 — drop the expired aliases** once nothing reads them.

## Open questions for a human

1. **`hurley_triangle`** — corpus truth is `triangle`, a valid specialty value. Under a
   separated model its geometry is arguably `clamshell` ("3 lights, two upper and one
   lower, even wrap"; image shows symmetric wrap with a small centered under-nose
   shadow). Keep `triangle` as a specialty label, or record geometry `clamshell` plus
   setup `triangle`?
2. **`gobo` entry** — image is a hard source through a cross-shaped cutout. `projected`
   is the canonical destination. But `ShadowPattern` also offers `cross_shaped_gobo`.
   Which axis owns the shape detail?
3. **`overcast_natural` remap** — remapped to `flat` on 2026-08-26. Under the separated
   model it should instead be `source_context=overcast` with geometry resolved
   independently. Revisit at Stage 2.

## Guardrail

Do not repeat the `face_box` failure: no engine output change (Stage 4) lands before the
per-axis gate (Stage 3) exists and has been red-proofed — the fault reintroduced, the
check watched failing.
