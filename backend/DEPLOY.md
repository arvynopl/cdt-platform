# Deployment Runbook — Fly.io (sin) + Neon (ap-southeast-1)

One-time setup and routine deploys for the CDT Platform API. Everything runs
from `backend/`. The app and database are co-located in Singapore by design
(audit F1 — the thesis build's FR01/NFR01 latency breaches were cross-region
network cost, not compute).

## One-time setup

1. **Install flyctl** and sign in: `fly auth login`.
2. **Create the app** (first deploy only — answers come from `fly.toml`):

   ```bash
   cd backend
   fly launch --no-deploy --copy-config
   ```

3. **Set secrets** (never commit these; `CDT_DATABASE_URL` is the **pooled**
   Neon connection string):

   ```bash
   fly secrets set \
     CDT_DATABASE_URL='postgresql://…-pooler.ap-southeast-1.aws.neon.tech/…?sslmode=require' \
     CDT_CORS_ORIGINS='https://<frontend-domain>' \
     SENTRY_DSN='https://…@….ingest.sentry.io/…'
   ```

   `CDT_COOKIE_SECURE=1` and `CDT_ENV=production` are already set in
   `fly.toml`'s `[env]`.

4. **Seed reference data** (stock catalog + market snapshots; idempotent):

   ```bash
   fly console --command "python -m database.seed"
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
