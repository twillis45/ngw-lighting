# Demo runbook — NGW Lighting

**Written 2026-09-13 for a live demo to a mixed room (advisor + investor/partner).**
Every claim below was read out of the code on this branch, not carried over from
prose. File and line references are the proof; re-read them if a session has
passed.

---

## 1. The one thing that will kill the demo

**The free tier is three analyses, enforced server-side, and the fourth returns
402 — permanently.**

| | |
|---|---|
| Threshold | `_DEFAULT_PAYWALL_THRESHOLD = 3` — `api/routes/recommend.py:29` |
| Where it counts | `_analysis_key()` — `db/database.py:775` |
| Key when signed in | `user:<id>` — **not** the session |
| Where it persists | `session_analysis_counts` in `data/ngw_users.db` |

Because the key is the **user**, not the session, a new browser, a new incognito
window, a fresh `session_id`, and a server restart all make **no difference**.
Once an account is at 3, it is at 3 until the row is deleted.

### The fix — use an internal account

`api/routes/recommend.py:100` bypasses the paywall entirely for internal
addresses, before the counter is ever read:

```python
get_internal_emails() = get_admin_emails() | _env_emails("NGW_DEV_EMAILS")
```
`db/provenance.py:66` · `db/pg_provenance.py:56`

**So any address in `NGW_ADMIN_EMAILS` already has unlimited analyses.** If
`admin@noguessworksystems.com` is set there, it is the demo account and no
further change is needed. Confirm before the room, not during it — the log line
to look for is:

```
[recommend] paywall bypass: user=<email> is_internal=True (unlimited analyses)
```

### Pre-demo check (run it, don't assume)

```bash
sqlite3 data/ngw_users.db \
  "select session_id, count from session_analysis_counts order by count desc limit 10;"
```

Clear a poisoned counter:

```bash
sqlite3 data/ngw_users.db \
  "delete from session_analysis_counts where session_id='user:dev-mode';"
```

---

## 2. Do not run the demo with `NGW_DEV_MODE=1`

`auth/dev_guard.py:29` and `auth/security.py:132` both define:

```python
_DEV_MODE_USER = {"id": "dev-mode", "email": "dev@localhost", ...}
```

With dev mode on, **every caller becomes that one user**, so every session
collapses to the single key `user:dev-mode` and shares one counter. Three
analyses across any combination of browsers and the next one 402s — and the
count survives restarts, because it is a row in a file.

Run the demo with `NGW_DEV_MODE=0` and a real signed-in account.

---

## 3. What not to demo

**Do not demo checkout or upgrade.** The Stripe account is not activated:

```
acct_1JglkMAfg2Db6k6m   name: "Toddwillisphoto"   livemode: false
```
`docs/STRIPE-ACTIVATION.md`, measured 2026-08-26

Clicking through an upgrade in front of an investor will not take a payment. If
pricing comes up, describe the tiers — do not click.

**Do not demo the paywall from the demo account.** It is internal, so the
paywall never appears. Showing "it stops you at three" requires a non-internal
account, and that account then cannot be reset without the SQL above.

---

## 4. Latency — the number nobody has measured

| Measurement | Value | Source |
|---|---|---|
| CV-only analysis | 1.4–9.4s, median **4.6s** | n=5, warm, M3 Max, 2026-09-02 |
| CV-only analysis | 0.92–2.47s, median **~1.2s** | n=14, warm, this container, 2026-09-13 |
| Stage split (CV) | `describe_image` **74%** · `extended_pipeline` **26%** | `stage_timings`, 2026-09-13 |
| Full analysis **with VLM** | **not measured** | — |
| Server timeout | **90s** | `api/routes/lab.py:114` |
| Cloudflare origin timeout | 100s | server fails first, by design |

The handoff records the VLM as "~97% of analysis wall time." That ratio is too
loose to plan with, and the two CV baselines show why: against the 4.6s M3 Max
median it implies a **~153s** total, comfortably past the 90s timeout; against
the ~1.2s median measured here it implies **~40s**, comfortably inside it. The
same claim lands on both sides of the limit depending on which CV figure you
pair it with, which means **the full-analysis number is genuinely unknown, not
merely unrecorded.** Treat it as the open risk it is:

- Run **two full analyses on the actual demo machine and network** before the
  room, and time them. That is the number that decides whether this demos live.
- If it runs long, prepare a pre-analyzed result to open instead, and say plainly
  that the analysis was run earlier — do not narrate a cached result as live.

---

## 4b. Which image to demo with — measured, not guessed

Fourteen sample images from `data/uploads/lab/` were analyzed CV-only on
2026-09-13 (container, not the demo machine). Screening criterion: no recorded
contradictions, not flagged for review, `CLASSICAL` mode, confidence ≥ 0.70.

**Seven passed.** All seven returned `loop` at `0.95 (strong)` in 0.92–1.25s:

```
lab_104abe6e8d00.jpg   loop   0.95 strong   0.93s
lab_1c6201ba31d9.jpg   loop   0.95 strong   0.92s
lab_252186bf7d7d.jpg   loop   0.95 strong   0.96s
lab_16db0328cb12.jpg   loop   0.95 strong   1.00s
lab_0cc3c7fffd11.jpg   loop   0.95 strong   1.03s
lab_0fe579d58e3e.jpg   loop   0.95 strong   1.14s
lab_057579bdbedb.jpg   loop   0.95 strong   1.25s
```

For a second pattern on screen, `lab_2c8db8ac426f.jpg` returns `clamshell` at
`0.91 (strong)` in 1.22s with one contradiction but **not** flagged for review.

**Do not demo these:**

| Image | Why |
|---|---|
| `lab_3367b42584f1.jpg` | `rembrandt` 0.39 **weak**, `BOUNDED`, 4 contradictions |
| `lab_0178aa4b409e.jpg` | `INSUFFICIENT`; headline pattern `projected` while its own candidate list holds `loop` and `rembrandt` |

`lab_03779d17f931.jpg` and `lab_061d944dff53.jpg` return `triangle` **0.95
strong** with 3 contradictions each and `needs_review=True`. These were on the
avoid list until the UI was checked — see below. They are now **good demo
material**, because the screen names the disagreement out loud.

### RESOLVED 2026-09-13 — the UI does disclose the uncertainty

An earlier revision of this file warned that `0.95 strong` appears both on a
clean result and on one carrying three contradictions, and that a contradicted
read might therefore be indistinguishable on screen. **That was checked against
the running UI and it is wrong. Do not carry the warning forward.**

`lab_03779d17f931.jpg` was uploaded through the real sign-in and crop flow on an
iPad Pro 11 viewport (`POST /api/analyze` → 200). The results screen renders,
directly beneath the pattern name and above the fold:

```
Triangle
Confident
WHAT THE ENGINE SAW
  Lights                3 sources
WHERE IT WAS NOT CERTAIN
  Two readings disagreed — loop vs projected
  clamshell was just as credible — worth a second look
WHAT LIMITED THIS READ
  Highlights are clipped — the brightest falloff is unrecoverable
```

The disagreement is named in plain photographer language, the alternate
candidate is named, and the limiting condition is stated. This is the `DT`
guardrail being *honored*, not broken — **demo it deliberately.** It is the most
credible thing on the screen to a working photographer, and it is exactly the
"trustworthy under ambiguity" claim in `CLAUDE.md` §X, shipped.

### Still open — a real inconsistency on the same screen

The Dispatch panel and the main panel disagree about light count for the same
analysis:

| Panel | Says |
|---|---|
| Dispatch (right) | `Triangle · 95% · **2 lights** · catchlights + shadow geometry` |
| Main read (left) | `Lights  **3 sources**` |

Two numbers for one analysis, both visible at once without scrolling. A
photographer will notice. Confirm which is correct before demoing this screen,
or avoid showing both panels together.

One more to verify, not assert: seven of fourteen returned the same pattern
(`loop`) at the same confidence (`0.95`). That may be correct for this sample —
it is a lab upload folder, not a balanced corpus — but it is worth one look
before claiming pattern range on screen.

---

## 4c. Two recipe filters are empty — do not tap them

Measured 2026-09-13 against the running app, Lighting Recipes:

| Filter | Setups |
|---|---|
| All | 31 |
| Headshot | 22 |
| Studio | 15 |
| Creative | 4 |
| **Event** | **0 — "No recipes in this category yet."** |
| **Video** | **0 — same empty state** |

Two of six chips lead to an empty state. Tapping either on camera reads as a
broken product rather than an unfinished category. Demo `Headshot` or `Studio`.

## 4d. The recorded walkthrough

A 1:59 screen recording of the real app (not a mockup) covers five workflows in
order: sign in → analyze a photograph → lighting recipes with filters → build a
setup from scratch → lighting journal. Recorded at 1194×834, iPad Pro 11
landscape, against a local server with `NGW_ADMIN_EMAILS` set so the paywall
never interrupts.

It exists as a fallback for the latency risk in §4: if a live analysis runs
long in the room, play the recording and say plainly that it was recorded
earlier. Do not narrate it as live.

## 5. Check before the room

- [ ] **Time two real analyses on the demo machine.** §4 — this is the one
      unmeasured thing standing between the demo and an awkward silence.
- [ ] **Confirm the demo account is internal** — look for the `paywall bypass`
      log line, or confirm it is in `NGW_ADMIN_EMAILS`.
- [ ] **`NGW_DEV_MODE=0`.**
- [ ] **Check `data/uploads/lab/` if any screen shows history or a gallery.** It
      currently holds prior uploads. Verify nobody else's photograph can appear
      on screen in front of an investor.
- [ ] **If demoing on production**, confirm the frontend you expect is the one
      deployed. Render does **not** build the UI (`Dockerfile:1`);
      `static/ui/assets/` is what ships, and a UI change needs a local
      `npm run build` committed with it.
- [ ] **If `NGW_ADMIN_EMAILS` was changed recently**: the vars *replace, never
      append*, and admin is keyed to a row in `users` — the account must have
      **logged in at least once before** the variable was set, or there are zero
      working admins.

---

## 6. Failure modes and what to say

| Symptom | Cause | In the room |
|---|---|---|
| `402 PAYWALL_LIMIT_REACHED` | Account at 3, not internal | Switch to the internal account. Do not debug live. |
| `503 SUBSCRIPTION_CHECK_FAILED` | Subscription lookup threw — `api/routes/recommend.py:112` | Retry once, then switch accounts. |
| `400 SESSION_ID_REQUIRED` | `session_id` missing from `metadata` | Client-side; reload the page. |
| Analysis hangs, then 504 | Exceeded the 90s timeout | Switch to the prepared result and say it was run earlier. |
| 404 on `/recommend` | It is mounted at **root**, not `/api` — `main.py:343` | — |

---

## 7. Honest framing for the investor half of the room

The product analyzes and gates correctly. It **cannot take a payment today**,
and that is a paperwork blocker (Stripe activation), not an engineering one. Say
that plainly if asked — it is a better answer than a vague one, and the
alternative is clicking an upgrade button that does nothing.
