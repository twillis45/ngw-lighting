# Claim ledger — NGW Lighting

> Every buyer-facing sentence, paired with the executed check that proves it.
> Built 2026-08-27 with `claim-verification`. Goes stale the moment the product
> changes — rebuild it before any copy ships.
>
> **The rule:** no claim ships unless an executed check asserts it. A green check
> on something adjacent is not evidence for the claim beside it.

---

## 1. How this audit was run

Suites executed 2026-08-27, recording **the numbers they printed**, not numbers
copied from an earlier doc.

| Suite | Command | Executed result |
|---|---|---|
| Unit + integration | `pytest tests/ -q` | 2,580 passed · 51 skipped · 1 xfailed · **0 failed** |
| Corpus accuracy (full sweep) | `pytest tests/test_corpus_accuracy_gate.py -m benchmark` | 1 passed (baselines 18/34 exact, 30/34 acceptable) |
| Accuracy-screen geometry | `pytest tests/e2e -m benchmark` | 4 passed |
| Evidence builder | `node scripts/check-lighting-evidence.mjs` | 17 checks PASS |
| Live gallery payload | `list_gallery()` | exact **15** / acceptable **27** / scored **29** |

**Cannot prove a claim even when green:** the default `pytest tests/` run
excludes both `benchmark` suites, so a green default run says nothing about
corpus accuracy or rendered geometry. Anyone citing "the suite passes" as
evidence for an accuracy claim is citing the wrong suite.

---

## 2. What nothing verifies

The most valuable section, and the one that took discipline to write.

- **No check establishes that the reference corpus ground truth was verified by
  a human.** 32 of 34 entries carry `photographer: "benchmark_verified"` — a
  placeholder string, not a person — and `source_type: "found_online"`. There is
  no record of who verified any entry, when, or by what method. `entry_trust_score`
  is a stored number with no derivation. This is load-bearing: it is the sentence
  the entire proof page rests on.
- **Nothing has tested the engine against photographs we did not choose.** Every
  accuracy number comes from a 34-image corpus assembled in-house.
- **No working photographer has ever assessed whether a returned setup is
  shootable.** Zero sessions run.
- **Skin-tone performance is unmeasured and unmeasurable with current tooling.**
  23 of 34 references are monochrome or near-monochrome, and the engine's
  skin-tone estimator is luma-based, so it reads underexposure as pigmentation.
- **Nothing verifies rendering in a viewer's own browser or email client.** The
  geometry gate covers Chromium at two viewports; Safari/iOS was checked by hand
  once, not by a standing check.

---

## 3. Claims

| # | Claim | Where | What must be true | Executed check | Class |
|---|---|---|---|---|---|
| 1 | "**15 of 29** matched the expected pattern exactly" | Accuracy screen; `accuracy_note` | The count is derived at request time from stored reads vs stored truth | `list_gallery()` computes it live; `test_gallery.py` asserts the resolved read is scored, not a single pass | **PROVEN** |
| 2 | "**27 of 29** fell within the accepted range" | same | Same, against `acceptable_patterns` minus `unknown` | same; `unknown` is excluded so declining cannot score as a hit | **PROVEN** |
| 3 | "Misses are shown. A proof page that hides its failures is not proof." | Accuracy screen | Failing entries render, labelled, alongside passing ones | Rendered and read back signed-out: `gobo`, `flat`, `short` appeared as `MISSED · READ …`. No standing assertion. | **PARTIAL** |
| 4 | "Against photographs whose lighting was **verified by hand**" | Accuracy screen | A human established each entry's expected pattern, on the record | **None.** `photographer` is the literal string `benchmark_verified` on 32 of 34; `source_type` is `found_online` | **UNPROVEN** |
| 5 | "Reverse-engineer any portrait. Nail the shot, **every time**." | Login — the first sentence a visitor reads | The engine returns a correct, actionable read on essentially all portraits | Corpus: **18/34 exact (53%)**, 30/34 acceptable (88%). "Every time" is contradicted by our own gate | **FALSE** |
| 6 | "Reverse-engineer **any** portrait" | Login; Studio home | Works across subjects, tones, and conditions generally | 34 in-house images, 23 monochrome, no external set | **UNPROVEN** |
| 7 | "See how it was lit." | Studio home headline | A promise of what the product does, not a performance claim | n/a — states the job | **PROVEN** |
| 8 | "Catchlight 10 o'clock, left eye" and the rest of the evidence readout | Result screen | Values come from the engine's own measurements for this image | `check-lighting-evidence.mjs`, 17 checks against a real captured `/api/analyze` payload | **PROVEN** |
| 9 | "Confident" on a read | Result screen | Reads shown as Confident are right materially more often than others | Measured: ≥80 band = 89% correct vs 83–100% below; grade shown **only** in that band | **PARTIAL** |
| 10 | "Two readings disagreed — butterfly vs loop" | Result screen | The engine actually recorded that disagreement for this image | Derived from `observability.contradictions`; asserted in the node checks incl. no resolver-name leakage | **PROVEN** |
| 11 | "Most of the frame is in shadow — fewer mid-tones to read direction from" | Result screen | The corresponding edge-case flag is set for this image | Derived from `edge_case_flags` / `ambiguity_flags`; asserted | **PROVEN** |
| 12 | "Rembrandt · Softbox · 45° left · 4 ft" | Studio home, sample tile | A representative real output | Static decorative string in the component; not generated | **PARTIAL** |
| 13 | Free tier is not a degraded read | Direction Board D4; pricing | CV-only accuracy equals the paid path | Corpus run with the VLM on and off: **identical on 34/34** | **PROVEN** |
| 14 | "Trusted by photographers who care about light" | Legacy `HomeScreenV2` CTA hint | Photographers use and endorse it | No users, no endorsements | **FALSE** |

---

## 4. Corrections kept

| Was | Now | What prevents its return |
|---|---|---|
| Gallery reported **2 of 29** exact (scored one of 30 vision passes) | 15 of 29 | `test_gallery.py` asserts the *resolved* read is scored and that exact ≥ 10 |
| Gap tracker: "`run_vlm` defaults to `False`, marginal cost ≈ $0" — never tested | Replaced with the measured statement | Numbers on the tracker now cite the run that produced them |
| Corpus scored `gobo` as a miss | `gobo → projected` per the enum's own migration note | Corpus gate baselines raised to 18/30 |
| Confidence shown as "Uncertain" on reads that were 83% correct | Grade shown only in the ≥80 band | `scoreIsMeaningful` + node checks |

---

## 5. Open items, ranked by embarrassment

Ordered by *what happens if a buyer tests this themselves* — not by difficulty.

1. **#5 "Nail the shot, every time."** A buyer needs one miss to disprove it, and
   our own published page shows two. It is the first sentence on the site and it
   is contradicted by the second screen. **Ship-blocking.**
2. **#4 "verified by hand."** A buyer who asks "verified by whom?" gets no answer.
   This is the credibility of the entire proof surface.
3. **#14 "Trusted by photographers."** There are no photographers yet.
4. **#6 "any portrait."** Survives casual use; fails the first unusual subject.
5. **#12** sample readout — harmless until someone asks whether that was measured.
6. **#3** misses-are-shown — true today, with nothing stopping a future filter.

---

## 6. Checks that would settle each open item

| # | Settled by |
|---|---|
| 5 | Reword to what is proven. "88% of our reference reads land within the accepted pattern range — every one published, misses included." Narrower and still sells. |
| 4 | Either record real provenance per entry (who, when, method) and keep "verified by hand", or reword to "against a reference set with recorded expected patterns". Reword is honest today; provenance is the durable fix. |
| 14 | Delete until true. Reinstate when a named photographer agrees to be quoted. |
| 6 | The 20-image external set (Gate Zero G0.15). Until then, drop "any". |
| 12 | Generate the tile from a real stored read, or label it as an example. |
| 3 | Add an assertion to the geometry gate that at least one `MISSED` tile renders when the payload contains one. |

---

## 7. Gate

Before any copy ships, every sentence maps to a **PROVEN** or **PARTIAL** row,
and PARTIAL rows are reworded to what is proven rather than deleted — the
mechanism is real, so the narrower sentence usually still sells.

**Audited 2026-08-27:** the 2 FALSE claims were reworded, #4 UNPROVEN was
reworded to what is provable, and #3 moved PARTIAL → PROVEN with a standing
assertion. Current state: **0 FALSE, 1 UNPROVEN (#6 "any portrait", pending an
external image set), 2 PARTIAL (#9 confidence band, #12 sample tile).** Copy
passes the gate; the two PARTIAL rows are worded to what is proven.
