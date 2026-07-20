# Frontend Deployment Runbook — Vercel

Deploys the Next.js app in `frontend/` to Vercel and connects it to the
already-live API on Fly.io (`https://cdt-platform-api.fly.dev`). Vercel builds
and hosts the frontend; it does **not** run the Python backend.

This is a monorepo, so the single most important setting is the **Root
Directory** — it must point at `frontend`, or the build won't find the app.

## Order of operations (there's a chicken-and-egg with CORS)

1. Deploy the frontend on Vercel → you get its URL.
2. Tell the backend to trust that URL (`CDT_CORS_ORIGINS` on Fly).
3. Verify end-to-end.

Until step 2 is done, the browser will block the frontend's API calls (CORS)
and login won't work — that's expected in the gap between steps 1 and 2.

## One-time setup on Vercel

1. Go to [vercel.com](https://vercel.com) and sign in with the GitHub account
   that owns `arvynopl/cdt-platform`.
2. **Add New… → Project**, then **Import** the `cdt-platform` repository.
3. On the configure screen:
   - **Root Directory** → click **Edit** and choose **`frontend`**. (Critical.)
   - **Framework Preset** → should auto-detect **Next.js**. Leave the build and
     output settings at their defaults.
   - **Environment Variables** → add one, for the **Production** environment:

     | Name | Value |
     |---|---|
     | `NEXT_PUBLIC_API_BASE` | `https://cdt-platform-api.fly.dev` |

     > This is read at **build time** and baked into the bundle. If you ever
     > change it, you must **redeploy** for the change to take effect.
4. Click **Deploy**. First build takes a couple of minutes.
5. When it finishes, copy the production URL (e.g.
   `https://cdt-platform.vercel.app`). This is your `<frontend-url>`.

After this, every push to `main` on GitHub triggers an automatic redeploy.

## Connect the backend (do this once, after the first Vercel deploy)

From `backend/`, point CORS at the Vercel URL (no trailing slash):

```bash
fly secrets set CDT_CORS_ORIGINS='https://<frontend-url>'
```

Setting a secret restarts the app with the new value (~30 s). If you also
haven't set the researcher/admin keys yet, do that now so `/peneliti` works in
production (see `backend/DEPLOY.md` step 3).

Cross-site login cookies are handled automatically — `CDT_COOKIE_SECURE=1` in
`fly.toml` makes the session cookie `SameSite=None; Secure`, which the browser
needs to send from the Vercel origin to the Fly origin. Nothing to configure.

## Verification checklist (after both steps)

- [ ] Open `https://<frontend-url>` — the landing page loads.
- [ ] Register a throwaway account → you reach the practice/onboarding screen.
- [ ] Complete a short path (practice → a real session) and confirm the results
      page and profile render — this proves cross-site cookies + CORS work.
- [ ] Log out and back in — proves the session cookie is being sent cross-site.
- [ ] `/peneliti` → enter the researcher key → KPIs load and a CSV downloads.
- [ ] Browser devtools → Network → any `/api/...` call has no CORS error, and
      the request carries the `cdt_session` cookie.

## Common problems

- **Build fails immediately / "next: command not found"** → Root Directory
  isn't set to `frontend`. Vercel → Project → Settings → General → Root
  Directory → `frontend`, then redeploy.
- **Login seems to work but every page bounces back to the landing screen** →
  the session cookie isn't being sent. Check `CDT_COOKIE_SECURE=1` on Fly
  (`fly secrets list` shows it) and that you're on **https** for both sites.
- **All API calls fail with a CORS error in the console** → `CDT_CORS_ORIGINS`
  doesn't exactly match the frontend origin (scheme + host, no trailing slash,
  no path). Re-run the `fly secrets set` above with the exact URL.
- **Changed `NEXT_PUBLIC_API_BASE` but the app still calls the old URL** → it's
  build-time; trigger a redeploy (Vercel → Deployments → ⋯ → Redeploy).

## Custom domain (optional, later)

Vercel → Project → Settings → Domains → add your domain. If you put the
frontend and API on the **same** registrable domain (e.g. `app.example.com` +
`api.example.com`), you may set `fly secrets set CDT_COOKIE_SAMESITE=lax`; on a
Vercel + Fly split, keep the default.
