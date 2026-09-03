# HANDOFF — NGW Lighting

**Read this first, before `docs/` or the long-form log.**
Measured reality, not intentions. Updated every session.

Last updated: **September 2, 2026** · deploy verified, `origin/main` == `HEAD`

---

## 1. Measured state

| | |
|---|---|
| Branch | `main` |
| HEAD | Read it, do not trust this row: `git log -1 --oneline`. A pinned SHA here is stale the moment the commit recording it lands — this row has been wrong before, by five commits. |
| Unpushed | **0** — verify with `git rev-list --count origin/main..HEAD` BEFORE writing "shipped" anywhere. On 2026-08-29 that count was 24 while the artifact said SHIPPED, a live rate-limit bypass stayed exploitable and the accuracy page kept hiding a real miss, for a day. |
| Test suite | **2,985 collected / 2,898 selected** (re-counted 2026-09-03 after the board found the previous figure — 2,930/2,843, dated the same day and labelled "not estimated" — off by 47) (87 deselected by marker — see traps; one of them is the accuracy gate). Counted 2026-09-03, not estimated. **It could not pass in one run until 2026-08-31** — two tests had been red for five months (`/recommend` required `session_id` from 2026-03-25; the tests were last touched twelve days earlier), and one passed alone but failed in the suite because the rate limiter's buckets are process-global and were never reset between tests, so the result depended on ORDERING. Both fixed; `conftest.py` now clears the buckets around every test. |
| Running it | **`.venv/bin/python -m pytest` — 70 seconds.** No `-q`: `pytest.ini` already sets it, so passing it again runs at `-qq` and hides the summary line. The ~40 minutes this row used to claim was 492 live OpenAI calls, removed 2026-09-02; see traps. CI runs the same command on every push and PR (`.github/workflows/tests.yml`). |
| Production | `https://app.noguessworksystems.com` — `/health` **200** |
| Deploy target | **Render**, Docker runtime, `render.yaml`. Never Vercel/Netlify. |
| CI | `.github/workflows/` — `benchmark.yml`, `nightly.yml`, `static-assets.yml` |
| Admin identity | `NGW_ADMIN_EMAILS` (backend, read at call time) · `VITE_NGW_ADMIN_EMAILS` (frontend, baked at build) |

---

## 2. What shipped this session

- **`1314537` → merged `baa3abf`, deployed.** Admin identity centralized behind
  `NGW_ADMIN_EMAILS` (`config/admin.py`), removing a hardcoded address from ten
  modules. `/api/lab/face-preflight` opened to anonymous callers — the Studio
  shell fetches it with no Authorization header, so a gated dependency returned
  **401** (not the 403 the prior handoff recorded) before the paywall was ever
  evaluated. Verified in production: preflight 200, curator routes still 401.
- **`6bc355b`** — `tests/test_protected_routes_sweep.py` (enumerating auth gate,
  275 routes, red-proofed) and `docs/SURFACES.md` (axis-1 declarations).
- **`1272d3c`** — `run_vlm` made real. **`4e8a9ce`** — customers can analyze a photo:
  `/api/analyze` replaces the curator-gated `/api/lab/analyze`, which is deleted rather
  than aliased. **`7000e2d`** — analysis timeout 180s → 90s to fail before Cloudflare.
- **Audit, no code changed** — legacy vs Studio comparison across visual,
  functional, and workflow layers. Findings in §4.

---

## 2b. Working artifacts

Published pages for this work. Private until shared; `/artifacts` in the terminal lists them.

| Artifact | What it holds |
|---|---|
| [Reverse the Light](https://claude.ai/code/artifact/c5febdcd-e6da-4695-baa8-6e39db188d18) | **This project's Path to Production artifact.** Eleven stages 0–10 with their gates, the four-phase marketing track, directions kept and struck, and the corrections. Source: `docs/artifact/reverse-the-light.html` — the **template**, carrying `__STATE__` and `__TPL__` placeholders. It cannot be published as-is: hydrate it first (state JSON + base64 of itself), then publish the hydrated copy passing the artifact URL as `url` to keep this URL stable. Last republished 2026-08-28 with the stage-4 Nielsen findings. |
| [NGW Company Register](https://claude.ai/code/artifact/4df93834-44b4-41d1-b754-d91bab76b85d) | **Canonical.** Entity, domains, registry + mail infra, identities, project register, architecture, every service console. Mirrored at `ngw-os/docs/COMPANY-REGISTER.md` |
| [NGW Business Tree](https://claude.ai/code/artifact/f32753df-6e11-4628-9f06-3d676a2eafcf) | Five lines, every project mapped, and five contradictions between the source documents |
| [NGW Lighting Rate Card](https://claude.ai/code/artifact/afa45439-f5bc-4b28-a99f-b0a90b11e0ae) | Pricing and financing mechanisms, measured COGS, margin per tier, 8 tracked references |
| [Elixxier Gap Tracker](https://claude.ai/code/artifact/3341d158-78f9-4d59-8e42-6a383c102c36) | 16 gaps vs set.a.light 3D scored by impact/day, plus the 4 places we already win |

Committed companions: `docs/SURFACES.md`, `docs/STRIPE-ACTIVATION.md`,
`ngw-os/skills/measure-unit-cost/`, `ngw-leadgen/docs/2026-08-25-market-promotion-handoff.md`,
`ngw-event-planner/demo/docs/claude-skills/REVIEW_BOARD_ROSTER.md`.

**Artifacts carry unverified figures deliberately.** The elixxier prices are secondhand
from a review; their own pricing page shows nothing without going to checkout. Anything
quoted outward clears `claim-verification` first.

## 3. Active traps — the part that pays

Every one of these cost a wrong turn. The block below was re-verified by
EXECUTION on 2026-09-02/03 — each was reproduced, not remembered — and three
long-standing traps were fixed outright rather than documented again.

**Fixed 2026-09-03, do not re-add as traps:** the suite dirtying
`data/reference_dataset/_version.json` on every run (root cause: two helpers in
`engine/reference_dataset.py` ignored the `dataset_root` their callers
resolved, so a tmp-dir test wrote the real corpus); `pytest .` exiting 3
(`norecursedirs`); and 492 live calls per run to `api.openai.com` (conftest
clears the key — measured 492 to 0, zero failures).

- **A default run takes 70 SECONDS, and `-q` hides the answer.**
  Measured 2026-09-03: `2848 passed, 50 skipped, 87 deselected in 69.93s`.
  **The old figure in this row was ~40 minutes** (2417.52s, 2026-09-02) and it
  was wrong within hours of being written: that run predates the `conftest.py`
  guard that removed 492 live calls to `api.openai.com`. The suite was never
  slow — it was waiting on a network round trip per test. This row even said
  "re-time it now that the VLM guard has landed" and then kept the 40-minute
  headline, which sent the next session to detach and poll for forty minutes on
  a seventy-second command. Caught by the stage-8 review board, not by its
  author.
  **Do NOT pass `-q`.** `pytest.ini` already carries it in `addopts`, so `-q`
  on the command line runs at `-qq` and SUPPRESSES the summary line — a green
  run and a crashed run then look identical. Just:
  `.venv/bin/python -m pytest`

- **Bare `pytest` is the SYSTEM Python 3.9, not the venv.** `which pytest` →
  `/usr/local/bin/pytest`, shebang `#!/usr/local/opt/python@3.9/bin/python3.9`.
  It reports `48 errors during collection` with
  `TypeError: Unable to evaluate type annotation 'Confidence | None'` — PEP 604
  unions 3.9 cannot parse. This reads as "the codebase is broken." It is the
  wrong interpreter. Always `.venv/bin/python -m pytest`, or `make test`.

- **The shell's `grep` silently skips gitignored files, and returns EMPTY, not
  `0`.** It is a function wrapping `ugrep` with `--ignore-files -I`. Measured:
  `grep -rn NGW_DEV_MODE .` misses `.env` line 18 entirely; `/usr/bin/grep`
  finds it. The `-I` half also skips any file containing a single NUL byte —
  that cost an hour on `skill-index/server.js`, where a literal NUL in a cache
  key made all 178 KB invisible and led to "the gate model has no source in the
  repo." No source file in THIS repo currently trips the NUL half. Use
  `/usr/bin/grep` whenever the answer might live in an ignored file: `.env*`,
  `ui/*.mjs`, `benchmarks/results/`, `*.log`.

- **`.env` sets `NGW_DEV_MODE=1`, and it poisons the paywall for raw scripts.**
  `get_optional_user` returns a dev user and `_analysis_key`
  (`db/database.py:775`) collapses every session to `user:dev-mode`. After 3
  requests **every** later call 402s forever, even with a fresh `session_id`,
  because the count is keyed to the user and persists in `data/ngw_users.db`.
  Measured with five distinct fresh session_ids: `200 200 200 402 402`. The 402
  is about you, not the code. Use `NGW_DEV_MODE=0`, as `tests/conftest.py` does.
  Clear a poisoned counter with
  `delete from session_analysis_counts where session_id='user:dev-mode'`.
  Also: `/recommend` is mounted at **root, not `/api`** (`main.py:343`).

- **87 tests are invisible to a default run, and one is the accuracy gate.**
  `addopts` deselects `stress`, `benchmark` and `slow_visual`:
  `test_benchmark_scorecard.py` 29, `test_lighting_benchmarks.py` 21,
  `test_benchmark_regression.py` 10, `test_benchmarks.py` 7, `test_stress.py` 7,
  `test_debug_overlay.py` 7, `e2e/test_accuracy_screen_geometry.py` 5, and
  **`test_corpus_accuracy_gate.py` 1**. A further 50 skip at runtime, mostly
  `skipif(not HAS_CV2)` and "reference corpus not present" — a missing corpus
  turns real gates into green skips. Before claiming accuracy or performance,
  run `.venv/bin/python -m pytest -m "benchmark"` explicitly.

- **RETIRED 2026-09-03 — `test_face_box_coordinate_space.py` no longer has any
  xfail or XPASS.** This trap told the next session to watch an XPASS count of
  2. `0de96ef` applied b6, collapsing the two coordinate spaces, and all 12
  tests now pass unmarked: a run reports **zero xfailed, zero xpassed**. Kept
  visible rather than deleted because the instruction had already been read
  once; a stale trap costs more than a missing one.


- **OPEN QUESTION — did the seeded benchmark case survive a deploy?** One case
  was created in production on 2026-08-31 (`POST /api/lab/benchmarks/cases` →
  **201**, confirmed present by a follow-up GET). A later successful `ci-run`
  reported **`total_cases: 0`**. Two explanations remain and they are NOT
  equivalent:
  1. The case persisted and something else returns zero — `get_benchmark_cases`
     applies no status filter and `init_benchmark_tables` contains no `DROP`,
     so this would be a third cause not yet found.
  2. `/data` is not actually persisting, so the case died with the container.
     The startup log prints `Database path: /data/ngw_users.db`, but that is the
     configured path — **not proof the disk is mounted there.**
  **The decisive test needs an admin token:** create a case, note the count,
  trigger a deploy, check the count again. Do not seed the remaining 29 until
  this is answered — seeding into ephemeral storage looks identical to success.
  Note the disk usage graph reading ~0 GB is NOT evidence either way; a
  few-megabyte SQLite file renders as ~0 on a 1 GB axis.

- **PARKED 2026-08-31 — rename the Render service.** Three names exist for one
  thing: repo `ngw-lighting`, `render.yaml` declares `ngw-api`, and the live
  service is **`ngw-core`** (a fossil from before the repo was renamed). Nobody
  can find it by name, which cost five rounds. **Renaming would take the site
  down**: `app.noguessworksystems.com` is a CNAME straight to
  `ngw-core.onrender.com`, so the rename must be followed immediately by a
  Cloudflare CNAME update. And do NOT lead with `render.yaml` — changing `name:`
  on a connected Blueprint can make Render create a NEW service and orphan the
  old one. Order: rename in the dashboard, verify, update the CNAME, then update
  `render.yaml`. **Find the service by its connected repo, never by name.**
- **`cd` persists between Bash calls, and it has bitten three times.** A `cd ui`
  left a later `python3 -m http.server` serving the wrong root, which read as a
  total render failure; a `cd ui/src` later made absolute-looking edits fail with
  FileNotFoundError. Prefix with `cd /Users/toddwillis/Code/ngw-lighting &&` or
  use absolute paths.

- **The vision payload carries TWO coordinate spaces, and that is load-bearing.**
  Measured 2026-08-29: `_img_bgr`, all four masks and `region_attribution.face_box`
  are in UPSCALED space; `catchlights` and `face_geometry` are in ORIGINAL space.
  A consumer pairing `face_box` with a mask is correct today; one pairing it with
  a catchlight is not. **Do not "fix" `face_box` on its own** — the patch at
  `docs/patches/face-box-coordinate-fix.patch` does exactly that and costs 10
  points of exact accuracy, because it moves one field out of the group it
  agrees with. See `tests/test_face_box_coordinate_space.py` for the audit.
- **`analyze_image` reassigns `h, w` after the resize** (`vision_pipeline.py:1161`,
  `:1167`), which is why everything computed afterwards is in upscaled space.
  That line is the origin of the whole two-space situation.
- **Corpus runs take ~90s** for 33 images and the full gate ~3 minutes. Background
  them with a log file and poll; a foreground pytest run will hit the tool timeout.


- **`input[0]` is not the first visible field on the login screen.** The username
  input lives in an animated slot that is present-and-`disabled` in every mode
  except register, rather than unmounted. A test that grabs `querySelectorAll(
  'input')[0]` types into a disabled field and reports a false failure. Filter on
  `:not([disabled])`, or select by type.
- **A green build is not evidence here.** The password-reset wiring was
  red-proofed by restoring the original `TODO` handler: the flow became
  unreachable and `npm run build` still reported **zero errors**. Only driving the
  screen caught it.
- **The Browser preview tool cannot see this project.** Its cwd is
  `/Users/toddwillis`, so it reads `~/.claude/launch.json`, not this repo's.
  `preview_start` with the project's server names fails. Drive puppeteer directly
  — which `measure-dont-look` prefers anyway.
- **`docs/artifact/reverse-the-light.html` is a TEMPLATE, not a page.** It carries
  `__STATE__` and `__TPL__` placeholders and renders blank if published as-is.
  Hydrate first (state JSON + base64 of itself), then publish passing the
  artifact URL as `url`.

- **Studio vs legacy is invisible in the DOM.** `sessionStorage.ngw_studio_active`
  decides which shell mounts; both serve from `/ui`. Check it *before* comparing
  anything. Four screenshots were published as a "legacy vs Studio comparison"
  that were in fact the same login screen.
- **`?_demo=` loses to `sessionStorage`.** Navigating to `?_demo=results` while
  Studio is active silently renders Studio Home. Clear with `?studio=off` first —
  and note that `studio=off` reloads and **strips other query params**.
- **`/lab` and `/studio` are 404s.** They are query params on `/ui`, not paths.
  `{"detail":"Not Found"}` means you used a path. `/ui/` with a trailing slash
  **307s to `http://`** and drops the query string.
- **Programmatic `.focus()` does not trigger `:focus-visible`.** It will report
  "no focus ring" on a shell that has one. Real Tab presses, and the page needs a
  real click first or keystrokes never reach it.
- **Contrast math must composite alpha.** Reading `rgba(132,158,184,0.35)`
  naively gives 7.09:1; composited over the real background it is **1.82:1**.
  Wrong by 4×, in the direction that says "passes."
- **The preview pane blocks `file://` scripts via CSP**, so JS probes silently
  return nothing. Use a scripted browser for anything load-bearing.
- **The frontend is prebuilt and committed.** `Dockerfile:1` — Render does *not*
  build the UI. `static/ui/assets/` is what ships. A frontend change needs a
  local `npm run build` committed with it, or it never reaches production.
- **Prod builds** are always prefixed `AUTH_BYPASS=false` with an empty
  OpenWeather key.
- **`NGW_ADMIN_EMAILS` and `NGW_DEV_EMAILS` replace, never append.** Listing only
  a new address silently revokes the old one. Admin is keyed to a row in the
  `users` table — the account must exist and be logged into *before* the variable
  is set, or there are zero working admins.
- **`plan_guard` caches its list in a module global.** Plan-tier changes need a
  Render restart; admin routes update at call time. They will disagree.
- **`run_vlm` was a dead parameter** until 2026-08-26. It sat in `analyze_image()`'s
  signature and docstring and was never threaded, so four routes — including the paid
  `/api/v1` tier — passed `run_vlm=False` and got the VLM anyway. Its default is now
  **True**, which preserves the old behavior rather than changing it.
- **Cloudflare sits in front of Render** (`server: cloudflare`, cf-ray on every
  response) with a **100s** default origin timeout. `NGW_ANALYSIS_TIMEOUT` is 90s so the
  server fails first with its own 504. Raising it past ~95s brings back opaque 524s.
- **The VLM is ~97% of analysis wall time**, not just cost. Measured on an M3 Max:
  CV-only **1.4–9.4s, median 4.6s** (n=5, warm, 2026-09-02). This said **0.7s**
  and the artifact said **7.7s** — two numbers for one measurement, neither
  reproducible, and nothing recorded how either was taken. Re-measure with
  `analyze_image(path, run_vlm=False)` over several images after a warm-up
  call, since the first invocation carries model load and is not
  representative. The spread is wide because image size drives it, so a
  single figure was always going to be wrong. The point it supports still
  holds: no API spend, same accuracy as the paid path.
- **One `/lab` route is public by design** — `face-preflight`. Do not copy the
  pattern to a new `/lab` route; the sweep will catch it, but know why.

---

## 4. Next steps, in order

1. **White Balance** — legacy shows WB + detected CCT; Studio shows no colour
   temperature anywhere. The one real data gap between the shells, and colour
   temp sits alongside aperture for a photographer matching a look.
2. **Lab has no entry point in Studio** — URL-only (`?lab=1`), and its back
   button exits to Settings, which has no way in. A one-way door.
3. **No `npm run check`** — the stage-4 "guard script passes" gate has nothing
   to run. `check:static-assets` exists; nothing aggregates.
4. **Two paywall impression routes** still accept anonymous writes keyed on a
   caller-supplied id with no ownership check. Analytics-integrity only; still
   allowlisted as REVIEW in the sweep.
5. **Duplicate verdict controls** on the Studio result — `Nailed It / Close
   Read / Missed It` and `✓ Nailed It / ~ Almost / ✕ Off`, same screen.

### Done this session — do not redo

- Studio back stack (`d1643c5`) — verified in production: Home → Recipes →
  Build → Back lands on **Recipes**, second back reaches Home.
- Three engine-telemetry routes gated (`b43ec19`) — verified 401 in prod.
- Layout regimes made reactive (`5bfff85`).
- Enumerating route sweep + surface declarations (`6bc355b`).

## 5. Open decisions for Todd

- **Studio is `facing: internal`** (see `docs/SURFACES.md`). Making it the default
  is a **stage-9 Promotion**, retroactively requiring four public gates — none
  run against it yet.
- **Two paywall impression routes** accept anonymous writes keyed on a
  caller-supplied id with no ownership check. Analytics-integrity risk only.
- **Stripe is in test mode with the wrong entity name** — Line 1 cannot collect
  regardless of the auth work.
