# Deploy Sylva as a public website

Sylva is one HTTPS site: the React UI and API share the same domain
(e.g. `https://sylva.onrender.com`).

## Option A — Render (recommended, free HTTPS)

1. Open the deploy link:  
   **https://render.com/deploy?repo=https://github.com/ashm-023/sylva**
2. Sign in with GitHub and allow the `ashm-023/sylva` repo.
3. Set these secret env vars in the Render dashboard:
   - `GEMINI_API_KEY` — https://aistudio.google.com/apikey
   - `OPENTOPO_API_KEY` — https://opentopography.org
4. Click **Apply** / **Create Web Service**.
5. Wait for the Docker build (~5–10 min first time).
6. Open the `.onrender.com` URL — that is your website.

### Redirect Render → Vercel

If the live site is on Vercel, set this env var on the Render service:

```
SITE_REDIRECT_URL=https://sylvagro.vercel.app/hardware
```

Redeploy Render. Visitors to `*.onrender.com` are permanently redirected to Vercel
(`/health` stays on Render for uptime checks).

Custom domain later: Render → Settings → Custom Domains → add `sylva.yourdomain.com`.

## Option B — Railway

1. New project → Deploy from GitHub → `ashm-023/sylva`
2. Railway detects the `Dockerfile`
3. Add the same env vars as above
4. Generate a public domain under Settings → Networking

## Option C — Run the production image locally

```bash
docker build -t sylva .
docker run --rm -p 8000:8000 \
  -e GEMINI_API_KEY=... \
  -e OPENTOPO_API_KEY=... \
  sylva
```

Open http://localhost:8000

## What visitors get

| URL | What it is |
|---|---|
| `/` | The Sylva website (React) |
| `/api/v1/...` | Farm profile, recommendations, sensors |
| `/health` | Uptime check |
| `/docs` | API docs |

NDVI may show as skipped until Google Earth Engine credentials are added on the server — soil matching and plans still work.

## Render: “Deploy latest” but site looks unchanged

1. **Wait for a finished deploy** — Docker rebuilds the React UI every time. Free tier often takes **5–15 minutes**. Events must show **Live** with the new commit SHA, not just “Build started”.
2. **Use Clear build cache & deploy** — Manual deploy menu → **Clear build cache & deploy**. Plain “Deploy latest commit” can reuse a stale Docker layer for the frontend.
3. **Hard-refresh the browser** — `Ctrl+Shift+R`. Old `index.html` in cache will keep showing the previous UI until revalidated.
4. **Confirm the repo/branch** — Service → Settings → Build & Deploy should point at `ashm-023/sylva` (or wherever you pushed) and branch `main`.
5. **Avoid “Deploy a specific commit”** unless you mean it — that **turns off auto-deploys**, so later pushes won’t go live until you turn auto-deploy back on.
6. **Check the build log** — If `npm run build` fails (OOM / missing deps), Render may keep the previous Live instance. Scroll the deploy log for `npm run build` / `ERROR`.
