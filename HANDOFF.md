# HANDOFF — NGW Lighting

**Read this first, before `docs/` or the long-form log.**
Measured reality, not intentions. Updated every session.

Last updated: **August 26, 2026** · deploy verified 12:10 EDT

---

## 1. Measured state

| | |
|---|---|
| Branch | `main` |
| HEAD | `7000e2d` — Fail before Cloudflare does |
| Unpushed | **0** — `main` deployed and verified 12:10 EDT |
| Test suite | **2,609 passed · 4 failed · 48 skipped** (233s) |
| The 4 failures | Pre-existing engine tests, unrelated to recent work — `test_advanced_passes`, `test_complexity_profile`, `test_perception_layer`, `test_vlw_reconciliation`. Verified identical before and after every change this session by stashing and re-running at HEAD. |
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

Every one of these cost a wrong turn this session.

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

- **`.venv` console scripts had stale shebangs — FIXED 2026-08-29.** I first
  recorded this as "the venv is broken." That was too broad and cost time. The
  *interpreter* was always fine: `.venv/bin/python3` resolves to a working
  Python 3.10.6 and every dependency imports. Only the 23 generated console
  scripts carried `#!/Users/toddwillis/Code/ngw-core/.venv/bin/python3` — a path
  from a repo rename — so `.venv/bin/uvicorn` died with `bad interpreter` while
  `.venv/bin/python3 -m uvicorn` would have worked all along. Shebangs and the
  three `activate*` scripts are rewritten; the API starts and answers on
  `/api/health`. **If a venv script ever fails again, check the shebang before
  concluding the environment is broken** — and prefer `.venv/bin/python3 -m <mod>`,
  which cannot go stale.
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
  CV-only **0.7s**, full pipeline **28.1s**. A CV-only tier is fast as well as free.
- **A test double that drifts from its real signature fails for the wrong reason.**
  `_fake_describe` lacked a new kwarg and six tests failed on the signature, not behavior.
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
