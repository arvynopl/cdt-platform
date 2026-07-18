# Deployment Runbook — Fly.io (sin) + Neon (ap-southeast-1)

One-time setup and routine deploys for the CDT Platform API. Everything runs
from `backend/`. The app and database are co-located in Singapore by design
(audit F1 — the thesis build's FR01/NFR01 latency breaches were cross-region
network cost, not compute).

## Two places configuration lives — don't mix them up

| Where | File/command | Used for | Committed to git? |
|---|---|---|---|
| Your laptop | `backend/.env` (copy of `.env.example`) | Running the API locally | **Never** (gitignored) |
| Fly.io | `fly secrets set NAME=value` | The deployed app | Never — Fly stores them encrypted; there is **no** `.env` file in production |

`fly secrets set` is the production replacement for a `.env` file. You type it
once; Fly keeps the values and injects them as environment variables into
every deploy.

## What you need before starting

1. **Required — the Neon pooled connection string.** Neon console → project
   `cdt-platform` → **Connect** panel → toggle **Connection pooling ON** →
   copy the URI. It looks like
   `postgresql://neondb_owner:xxxx@ep-…-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
   (the `-pooler` in the hostname is how you know it's the right one).
2. **Not needed yet — frontend domain (`CDT_CORS_ORIGINS`).** This is the
   browser origin of the Next.js app, which doesn't exist until Fase 2. Skip
   it now; the config default (`http://localhost:3000`) is fine. When the
   frontend is deployed you'll set it to that site's URL (one line, step 5).
3. **Optional — Sentry (`SENTRY_DSN`).** Only if you've created a (free)
   Sentry project: sentry.io → Create Project → Python/FastAPI → copy the DSN.
   Without it the app runs fine; you just don't get error alerting yet.

## One-time setup

1. **Install flyctl** and sign in: `fly auth login`.
2. **Create the app** (first deploy only — answers come from `fly.toml`):

   ```bash
   cd backend
   fly launch --no-deploy --copy-config
   ```

3. **Set the one required secret** (paste your pooled Neon URI inside the
   quotes):

   ```bash
   fly secrets set CDT_DATABASE_URL='postgresql://…-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'
   ```

   If you have a Sentry DSN, add it the same way:
   `fly secrets set SENTRY_DSN='https://…ingest.sentry.io/…'`.

   To activate the researcher/admin endpoints (`/api/researcher/*`,
   `/api/admin/summary`), set their access keys too — pick two long random
   strings and store them in your password manager:

   ```bash
   fly secrets set CDT_RESEARCHER_PASSWORD='<long-random-1>' CDT_ADMIN_TOKEN='<long-random-2>'
   ```

   Left unset, those endpoints simply return 503 (disabled) — the rest of
   the app is unaffected.

   `CDT_COOKIE_SECURE=1` and `CDT_ENV=production` are already set in
   `fly.toml`'s `[env]` — nothing to do for those.

4. **First deploy + seed reference data** (stock catalog + market snapshots;
   idempotent):

   ```bash
   fly deploy
   fly console --command "python -m database.seed"
   ```

5. **Later, when the Fase 2 frontend is live**, point CORS at it:

   ```bash
   fly secrets set CDT_CORS_ORIGINS='https://<the-frontend-url>'
   ```

## Routine deploy

```bash
cd backend
fly deploy
```

`release_command = "alembic upgrade head"` applies pending migrations before
the new version takes traffic; a failing migration aborts the deploy and the
old version keeps serving.

## Verification checklist (after every deploy)

- [ ] `curl https://<app>.fly.dev/healthz` → `{"status":"ok"}`.
- [ ] `fly logs` shows JSON log lines, no tracebacks, and NO
      "Cookies are NOT marked Secure" warning.
- [ ] Register a throwaway account via the API; confirm `users` row in Neon.
- [ ] `X-Response-Time-Ms` on a round submit from an Indonesian connection:
      p95 target < 200 ms (FR01 budget with ~10× headroom vs the thesis
      deployment's 651 ms).
- [ ] Sentry: trigger a test event (`fly console --command "python -c 'import sentry_sdk; sentry_sdk.init(); 1/0'"` is NOT needed — use the dashboard's "send test event").

## Rollback

```bash
fly releases            # find the last good version
fly deploy --image <image-ref-of-last-good-release>
```

Database rollback: Neon → Branches → Restore (7-day point-in-time history on
the free tier). Restore to just before the bad deploy, then roll the app back.

## Latency benchmark (thesis-comparable numbers)

`scripts/bench_latency.py` measures the same FR01/NFR01 pipeline the thesis
reported (Bab VI Tabel latensi). Run it against production topology from a
machine in Indonesia to produce comparable p50/p95:

```bash
CDT_DATABASE_URL='<neon-pooled-url>' python scripts/bench_latency.py
```
