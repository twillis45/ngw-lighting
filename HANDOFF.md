# HANDOFF — NGW Lighting

**Read this first, before `docs/` or the long-form log.**
Measured reality, not intentions. Updated every session.

Last updated: **August 26, 2026**

---

## 1. Measured state

| | |
|---|---|
| Branch | `main` |
| HEAD | `6bc355b` — Enumerating auth sweep + surface declarations |
| Unpushed | **1 commit** |
| Test suite | **2,602 passed · 4 failed · 51 skipped** (197s) |
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
- **Audit, no code changed** — legacy vs Studio comparison across visual,
  functional, and workflow layers. Findings in §4.

---

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
- **One `/lab` route is public by design** — `face-preflight`. Do not copy the
  pattern to a new `/lab` route; the sweep will catch it, but know why.

---

## 4. Next steps, in order

1. **Push** — 1 commit unpushed on `main`.
2. **Studio back stack** — P1. No history; `onBack` is hardcoded per screen and
   8 of 11 go to `home`, so any second hop loses your place. `prevScreenRef`
   exists but only picks an animation. Legacy's `AppContext` history array is the
   working model. §XII scope pass is done and approved; needs `data-testid`s
   before the browser walk can assert it.
3. **Gate the three `REVIEW:` telemetry routes** — `/api/intelligence/score`,
   `/score/history`, `/patterns` expose aggregate engine-accuracy data publicly.
   One dependency each.
4. **Non-reactive layout branches** — 23 raw `window.innerWidth` reads evaluated
   once at render against 11 reactive `useIsDesktop()` usages, with hardcoded
   thresholds (`820`, `768`, `1024`) beside the named constants.
5. **White Balance** — legacy shows WB + detected CCT; Studio shows no colour
   temperature anywhere. The one real data gap between the shells.
6. **Lab has no entry point in Studio** — URL-only, and its back button exits to
   Settings, which has no way in.
7. **No `npm run check`** — the stage-4 "guard script passes" gate has nothing
   to run.

---

## 5. Open decisions for Todd

- **Studio is `facing: internal`** (see `docs/SURFACES.md`). Making it the default
  is a **stage-9 Promotion**, retroactively requiring four public gates — none
  run against it yet.
- **Two paywall impression routes** accept anonymous writes keyed on a
  caller-supplied id with no ownership check. Analytics-integrity risk only.
- **Stripe is in test mode with the wrong entity name** — Line 1 cannot collect
  regardless of the auth work.
