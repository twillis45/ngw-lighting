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
