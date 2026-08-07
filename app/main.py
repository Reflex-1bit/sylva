"""
Sylva — Agroforestry Intelligence Platform
Backend API + production website (React build)
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.routers import farm, match, recommendations, sensors  # noqa: E402

app = FastAPI(
    title="Sylva",
    description=(
        "Agroforestry intelligence — farm profiling, species matching, "
        "and transition plans backed by soil verification hardware."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(farm.router, prefix="/api/v1", tags=["farm"])
app.include_router(match.router, prefix="/api/v1", tags=["match"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["recommendations"])
app.include_router(sensors.router, prefix="/api/v1", tags=["sensors"])

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0", "ui": (FRONTEND_DIST / "index.html").exists()}


def _serve_spa_file(full_path: str = "") -> FileResponse:
    """Serve built React assets; fall back to index.html for the app shell."""
    if not FRONTEND_DIST.exists():
        raise HTTPException(
            status_code=503,
            detail="Website build missing. Run: cd frontend && npm ci && npm run build",
        )

    # Prevent path traversal
    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST.resolve())):
        return FileResponse(candidate)

    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=503, detail="frontend/dist/index.html not found")
    return FileResponse(index)


@app.get("/")
def serve_root():
    return _serve_spa_file()


# Static hashed assets from Vite
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/favicon.svg")
def favicon():
    return _serve_spa_file("favicon.svg")


@app.get("/icons.svg")
def icons():
    return _serve_spa_file("icons.svg")


@app.get("/hardware")
@app.get("/hardware/")
def hardware_spa():
    """SPA route — React Router owns /hardware."""
    return _serve_spa_file()
