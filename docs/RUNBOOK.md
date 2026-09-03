# NGW Lighting — Operations Runbook

Written 2026-09-03 because stage 8's gate asks where the runbook lives and the
answer was nowhere. Every fact below was verified by running the command shown,
not recalled. Where something does not exist, this says so rather than
describing what a well-run service would have.

## The service

| | |
|---|---|
| Render service | `ngw-core` (`srv-d71blf5gffc73fn63d0`), workspace "My Workspace" |
| Account | tw@toddwillisphoto.com |
| Hosts | `app.noguessworksystems.com` and `lighting.noguessworksystems.com` both serve it |
| DNS | `app.` CNAMEs directly to `ngw-core.onrender.com` |
| Persistent disk | mounted at `/data`; `NGW_DATA_DIR=/data` |

## Is it up?

```bash
curl -s https://app.noguessworksystems.com/health
```

Returns `{"status":"ok","engine_version":"1.0.0"}`.

**A 200 here does not mean the app works.** This endpoint checks nothing — not
the database, not the disk, not the VLM provider. It proves the process is
listening. Treat it as a liveness probe and nothing more.

The real check is admin-only:

```bash
curl -s https://app.noguessworksystems.com/health/system \
  -H "Authorization: Bearer $NGW_ADMIN_TOKEN"
```

`api/routes/health.py:133` — uptime, upload storage free space and writability,
scheduler status and last error, VLM rolling stats. **You need an admin token to
diagnose this service**, which has itself been a blocker: on 2026-09-01 a
benchmark question went unanswered for want of one.

## How to roll back

There is no CLI path. Render dashboard → `ngw-core` → Events → the previous
successful deploy → **Redeploy**. Deploys are triggered by commits to `main`
(`autoDeployTrigger: commit`).

Rolling back the CODE does not roll back the DATA. The SQLite database on
`/data` survives a rollback, so a bad migration is not undone by redeploying the
previous image.

## The kill switch

**There is none.** Verified: no `MAINTENANCE`, `maintenance_mode`, `kill_switch`
or `READ_ONLY` anywhere in `main.py`, `api/`, `engine/`, `db/` or `auth/`.

The only levers are:
- **Suspend the service** in the Render dashboard — hard down, 502 for everyone.
- **Roll back** to a prior deploy, if the problem arrived with a deploy.
- **Revoke a key** at the provider (Stripe, OpenAI) to disable one integration.

Recorded as debt, not described as a feature. Whoever needs to stop this service
in a hurry today has one option and it is "turn it off".

## Known operational traps

- **Uploaded images do not survive a deploy.** `NGW_UPLOAD_DIR` is unset, so
  `api/routes/shoot_match.py:74` writes to `static/uploads`, which is gitignored
  and recreated empty at boot (`main.py:167`). The database on `/data` persists
  `image_path` in several tables (`db/database.py:129,141,166,316`). So rows
  survive, files do not, and after any deploy those paths are dangling.
- **The storage health check watches a path the app may not use.**
  `api/routes/health.py:144` hardcodes `static/uploads`, while the uploader reads
  `NGW_UPLOAD_DIR`. Set that variable and the health check silently reports free
  space for the wrong filesystem.
- **Stripe is in TEST MODE.** No transaction has ever settled. See
  `docs/STRIPE-ACTIVATION.md` for the switch sequence; it needs the `sk_live_`
  secret and live-mode Price IDs, which are the owner's to enter.

## DEPLOY.md is unsafe to follow as written

Ruled by the stage-8 board, 2026-09-03. Two of its specifics are wrong, and they
are the two most likely to be trusted during an incident:

- `DEPLOY.md:36` documents `ADMIN_EMAILS`. The code reads **`NGW_ADMIN_EMAILS`**
  (`ui/src/config/admin.js`, `config/admin.py`). Setting the documented variable
  grants nobody anything, silently.
- `DEPLOY.md:44` says the persistent disk mounts at **`/app/data`**. It mounts at
  **`/data`**, and `render.yaml` spends fourteen lines explaining that `/app/data`
  is the path that SHADOWS the repo's own `data/` directory and destroys the
  gallery. A new operator following DEPLOY.md reintroduces the data-loss bug
  that was fixed on 2026-08-31.

Until DEPLOY.md is corrected, this file is the deployment reference.

## Who may do what

The board's standing delegation covers DECISIONS. It does not cover acts that
need the owner's own accounts: entering the Stripe live key, changing Render
environment variables, and anything requiring the admin token. Those remain his.
