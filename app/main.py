"""
Sylva — Agroforestry Intelligence Platform
Backend API + (optional) production website (React build)

Security notes:
- Secrets (GEMINI_API_KEY, OPENTOPO_API_KEY, SENSOR_INGEST_TOKEN) are
  read only from process environment / server .env — never from the React bundle.
- On Vercel, set those as encrypted Environment Variables (not VITE_*).
- ALLOWED_ORIGINS restricts browser CORS when the API is on a separate origin.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

from app.routers import farm, match, recommendations, sensors  # noqa: E402

APP_VERSION = "0.2.0"
API_ONLY = os.getenv("SYLVA_API_ONLY", "").strip().lower() in {"1", "true", "yes", "on"} or bool(
    os.getenv("VERCEL")
)
# When set (e.g. on Render), send browsers to the canonical Vercel site.
# /health is left alone so Render health checks keep working.
SITE_REDIRECT_URL = os.getenv("SITE_REDIRECT_URL", "").strip().rstrip("/")


def _allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Local Vite defaults; production should set ALLOWED_ORIGINS explicitly
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


app = FastAPI(
    title="Sylva",
    description=(
        "Agroforestry intelligence — farm profiling, species matching, "
        "and transition plans backed by soil verification hardware."
    ),
    version=APP_VERSION,
    docs_url="/docs" if os.getenv("ENABLE_API_DOCS", "1").strip() not in {"0", "false"} else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Device-Token", "X-Ingest-Token"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # Do not leak server tech
        if "server" in response.headers:
            del response.headers["server"]
        return response


class SiteRedirectMiddleware(BaseHTTPMiddleware):
    """301 to SITE_REDIRECT_URL (exact); /health stays on this host."""

    async def dispatch(self, request: Request, call_next):
        if not SITE_REDIRECT_URL:
            return await call_next(request)
        path = request.url.path
        if path == "/health" or path.startswith("/health/"):
            return await call_next(request)
        return RedirectResponse(url=SITE_REDIRECT_URL, status_code=301)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SiteRedirectMiddleware)

app.include_router(farm.router, prefix="/api/v1", tags=["farm"])
app.include_router(match.router, prefix="/api/v1", tags=["match"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["recommendations"])
app.include_router(sensors.router, prefix="/api/v1", tags=["sensors"])

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "ui": (not API_ONLY) and (FRONTEND_DIST / "index.html").exists(),
        "api_only": API_ONLY,
        # Never echo whether specific secret keys are set with their values
        "secrets_configured": {
            "gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
            "ingest_token": bool(os.getenv("SENSOR_INGEST_TOKEN")),
        },
    }


def _serve_spa_file(full_path: str = "") -> FileResponse:
    """Serve built React assets; fall back to index.html for the app shell."""
    if API_ONLY:
        raise HTTPException(status_code=404, detail="Not found")

    if not FRONTEND_DIST.exists():
        raise HTTPException(
            status_code=503,
            detail="Website build missing. Run: cd frontend && npm ci && npm run build",
        )

    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST.resolve())):
        headers = {}
        if full_path.startswith("assets/") or "/assets/" in full_path.replace("\\", "/"):
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            headers["Cache-Control"] = "no-cache"
        return FileResponse(candidate, headers=headers)

    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=503, detail="frontend/dist/index.html not found")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


if not API_ONLY:

    @app.get("/")
    def serve_root():
        return _serve_spa_file()

    if (FRONTEND_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/favicon.svg")
    def favicon():
        return _serve_spa_file("favicon.svg")

    @app.get("/logo.svg")
    def logo():
        return _serve_spa_file("logo.svg")

    @app.get("/icons.svg")
    def icons():
        return _serve_spa_file("icons.svg")

    @app.get("/hardware")
    @app.get("/hardware/")
    def hardware_spa():
        return _serve_spa_file()
