# Handoff — NGW Lighting revenue-blocker fix

**Repo:** `~/Code/ngw-lighting`
**Branch (current):** `test/real-dispatch-export-variants` — confirm the fix should land here or on a new branch off `main`. Prod is `main@59b229d` (May 9), Render + Cloudflare, `app/lighting.noguessworksystems.com`.
**Date handed off:** August 25, 2026

## Why this matters
Five NGW products are live and none of them charge. NGW Lighting is the closest to
collecting, and it is blocked by an auth defect, not a missing feature. Fixing this is
payment-capability work, not build-completion work.

## The defect
The signed-in account is `info@noguessworksystems.com`. Admin is hardcoded to
`todd@toddwillisphoto.com` in ten places, so the real user is not recognized as admin.
Separately, `/api/lab/face-preflight` is dev-gated, so non-dev users get a 403 and the
light pools starve on the same 403.

## The three-part fix (designed August 24, not yet applied)
1. **Open `face-preflight`** — remove the dev gate so non-dev users can reach it. The
   demo shell depends on `/api/lab/analyze` and `/api/lab/face-preflight`, both gated;
   `/api/v1/analyze` is the public route. Confirm which the shell should call.
2. **Repoint Studio** to the correct (non-gated) analyze route.
3. **Centralize admin** behind an `NGW_ADMIN_EMAILS` env var, comma-separated, defaulting
   to the current hardcoded value so nothing regresses if the var is unset.

## Exact sites for part 3 (verified by grep this morning)
Backend — each declares its own `ADMIN_EMAILS` literal:
- `api/routes/experiments.py:27`
- `api/routes/failures.py:36`
- `api/routes/flags.py:23`
- `api/routes/health.py:27`
- `api/routes/intelligence.py:47`
- `api/routes/track.py:23`
- `db/pg_provenance.py:48`
- `db/provenance.py:58` (plus the docstring at line 32 that names the hardcoded value)

Frontend:
- `ui/src/hooks/usePlan.js:17` — `ADMIN_EMAILS` array
- `ui/src/hooks/usePaywall.js:40` — admin list
- `ui/src/context/AppContext.jsx:694` — dev-admin fallback user
- `ui/src/main.jsx:75` — `_devModeUser`

Not source, leave alone: `migrations/004_backfill_provenance.sql:36`,
`static/ui/assets/index-*.js` (build output), `ui/.figma-audit-screens.md`.

## Placement question to resolve first
`db/` must not import from `api/`. The repo already has `config/settings.py` and
`core/logging.py`. Put the resolver in `config/settings.py` (or a small
`config/admin.py`) so both `api/` and `db/` can import it. `db/provenance.py` already
reads `NGW_DEV_EMAILS` and `NGW_EXPERT_EMAILS` from env — **match that existing parsing
convention exactly** rather than inventing a new one.

## Definition of done (machine-checkable)
- A test asserts that with `NGW_ADMIN_EMAILS=a@x.com,b@y.com` set, both addresses resolve
  as admin and an unlisted address does not.
- A test asserts that with the var unset, `todd@toddwillisphoto.com` still resolves as
  admin (no regression).
- `grep -rn "toddwillisphoto" api/ db/ ui/src/` returns only the default constant in the
  single resolver module — zero hits in route files or hooks.
- A request to `face-preflight` as a non-dev, non-admin user returns 200, not 403.
  Write this test first and watch it fail before touching the gate.
- Existing test suite passes before and after.

## Constraints
- Prod build env must be prefixed with `AUTH_BYPASS=false` and an empty OWM key.
- Deploys go to Render, not Vercel/Netlify.
- Surgical changes only — the four dev-mode/fallback frontend sites are user-identity
  seeds, not admin gates. Decide deliberately whether they belong in this diff; if they
  do not, say so and leave them.
- Do not remove the pre-existing hardcoded value from the migration SQL.

## Open question for Todd
Auth approval for opening `face-preflight` was requested August 24 and never answered.
Confirm before shipping part 1.

## Uncommitted state in the working tree right now
Modified: `data/reference_dataset/_version.json`
Untracked: `docs/DESIGN_STANDARD.md`, `ngw_chatgpt_os_project_pack/`,
`ui/screenshots/`, `ui/scripts/`, `ui/visual-explorations-canvas.js`
None of this is part of the fix. Do not sweep it into the commit.
