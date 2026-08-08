# Deploy Sylva on Vercel (secure, under size limit)

Vercel serves the **React UI** and a **slim FastAPI** function (`api/index.py`).

Earth Engine / heavy Google packages are **not** installed on Vercel (they blew the
225 MB function limit). NDVI stays off (`ENABLE_NDVI=0`). Gemini still works via
**httpx REST** using `GEMINI_API_KEY` on the server.

## Secrets (never use `VITE_`)

In Vercel → Project **sylva** → Settings → Environment Variables:

| Name | Notes |
|---|---|
| `GEMINI_API_KEY` | Server only |
| `SENSOR_INGEST_TOKEN` | Long random string |
| `ALLOWED_ORIGINS` | `https://sylva-reflex-1bits-projects.vercel.app` (and custom domain) |
| `OPENTOPO_API_KEY` | Optional |
| `ENABLE_API_DOCS` | `0` in production |
| `ENABLE_NDVI` | `0` (default on Vercel) |

**Do not** add `VITE_GEMINI_API_KEY` or any secret as `VITE_*`.

## GitHub link (important)

Vercel must build **this** codebase — not an empty “Initial commit” from vercel.com/new.

- Linked repo should contain `vercel.json`, `frontend/`, `api/index.py`, `app/`
- For Reflex-1bit: push `main` to `https://github.com/Reflex-1bit/sylva`

## Verify no key leak

After deploy: DevTools → `assets/*.js` → search your key / `AIza` → nothing.
