# Surfaces — NGW Lighting

Path to Production, axis 1. Every surface declares `facing` and `platform`,
because *"if a surface's platform is undeclared, that is the first thing to
fix — every gate below it inherits the wrong defaults."*

Measured August 26, 2026 against `main`.

| # | Surface | `facing` | `platform` | Spine stage |
|---|---|---|---|---|
| 1 | **App — legacy shell** (`/ui`) | public | web (responsive) | 8 · Maintain |
| 2 | **App — Studio shell** (`/ui?studio=1`) | **internal** | web (responsive) | 4 · Verify |
| 3 | **Lab / curator console** (`/ui?lab=1`) | internal | web | 8 · Maintain |
| 4 | **Marketing pages** (`/`, `/features`, `/pricing`, `/library`, `/blog`, `/early-access`) | public | web | 8 · Maintain |
| 5 | **Studio API** (`/api/v1/*`) | public | HTTP API | 8 · Maintain |
| 6 | **Internal tooling** (`scripts/`) | internal | CLI | 8 · Maintain |

## Surface 2 is internal, and that matters

The Studio shell is reachable only by typing `?studio=1`. It is session-scoped
(`sessionStorage.ngw_studio_active`), nothing in the product links to it, and
`?studio=off` clears it.

**Making Studio the default is a stage-9 Promotion, not a deploy.** It
retroactively runs the four public gates it skipped while internal:

- Stage 2 — activation/UX doctrine (Ruthless Host Lens, Attention System)
- Stage 4 — Nielsen 10-heuristics critique
- Stage 5 — full security & data review
- Stage 7 — instrumentation wired, tracker synced

None of the four has been run against Studio.

## Platform gates that now apply

`platform: web (responsive)` on surfaces 1 and 2 means:

- **Stage 2** — mobile is the flagship; design at 390px first.
- **Stage 4** — a measurement pass is **mandatory**: both shells render in
  three layout regimes (`<768`, `768–1023` `TABLET_MIN_WIDTH`, `≥1024`
  `LAYOUT_DESKTOP_MIN`). `ui/src/utils/useIsDesktop.js` warns in its own
  docstring that mismatched thresholds create *"a conflict zone where screens
  render desktop layouts inside mobile-scaled FitToViewport frames."*
- **Stage 6** — web ships on our schedule; no store review latency.

**Verified not a problem:** the viewport meta tag is present in `ui/index.html`
and the shipped bundle (`width=device-width, initial-scale=1.0,
viewport-fit=cover`), so the skill-index 390px trap does not apply here.

**Open:** 23 raw `window.innerWidth` branches are evaluated once at render and
never re-run, against 11 reactive `useIsDesktop()` usages. Hardcoded thresholds
(`>= 820`, `>= 768`, `>= 1024`, `< 768`) sit alongside the named constants.

## Security posture

Surface 5 (`/api/v1/*`) requires an `X-API-Key` prefixed `ngw_studio_` **plus**
an active paid Studio subscription — it is not reachable with a browser JWT.

`tests/test_protected_routes_sweep.py` is the stage-4/5 enumerating gate for
all HTTP surfaces: it walks the live route table (275 routes) and requires
every route to either reject an anonymous caller or appear on `PUBLIC_ROUTES`
with a written reason. Red-proofed August 26, 2026.
