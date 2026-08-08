# Deploy Sylva on Vercel (secure)

Vercel hosts the **website only** (React).  
Your FastAPI API stays on **Render/Docker** with all secrets.

Why not Python on Vercel? The full API bundle (~260 MB with scientific deps) exceeds Vercel’s **225 MB** function limit. A tiny Edge proxy stays well under the limit and keeps keys off the client.

```
Browser  →  Vercel (static UI, no secrets)
         →  /api/*  →  Edge proxy  →  Render FastAPI (GEMINI_*, tokens, …)
```

## Critical: secrets never hit the website

| Variable | Where | In browser? |
|---|---|---|
| `GEMINI_API_KEY` | **Render** (or Docker) only | No |
| `OPENTOPO_API_KEY` | Render only | No |
| `SENSOR_INGEST_TOKEN` | Render only | No |
| `API_UPSTREAM_URL` | Vercel (e.g. `https://sylva.onrender.com`) | No — server/Edge only |
| `VITE_*` secrets | **Never** | Would leak |

## Setup

### 1. Keep / deploy the API on Render

Use [DEPLOY.md](DEPLOY.md). Confirm:

- `https://YOUR-APP.onrender.com/health` returns OK  
- Env vars `GEMINI_API_KEY`, etc. are set **there**

### 2. Import the real GitHub repo on Vercel

Do **not** use a blank “Initial commit” from vercel.com/new.

1. [vercel.com/new](https://vercel.com/new) → **Import** `ashm-023/sylva` (or your fork)  
2. Framework: **Other** (root `vercel.json`)  
3. Root directory: leave empty (repo root)  
4. Add Environment Variable (Production + Preview):

   ```
   API_UPSTREAM_URL=https://YOUR-APP.onrender.com
   ```

   No other secrets on Vercel.

5. Deploy.

### 3. Lock CORS on the API

On Render, set:

```
ALLOWED_ORIGINS=https://YOUR-PROJECT.vercel.app
```

Redeploy Render once.

### 4. Verify keys are not in the client

DevTools → Network → open `assets/index-*.js` → search for your Gemini key / `AIza` → **nothing**.

## Local

```bash
# API with .env secrets
uvicorn app.main:app --reload --port 8000

# UI
cd frontend && npm run dev
```

## If you previously created an empty Vercel project

Delete that project (Settings → Delete). Import `ashm-023/sylva` again so builds use this repo’s `vercel.json`, not an empty initial commit.
