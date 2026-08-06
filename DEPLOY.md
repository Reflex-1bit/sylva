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
