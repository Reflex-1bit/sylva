"""
Sylva — Agroforestry Intelligence Platform
Backend API
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
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
    return {"status": "ok", "version": "0.2.0"}


@app.get("/")
def serve_frontend():
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return {
            "message": "Sylva API is running. Build the UI with: cd frontend && npm install && npm run build",
            "dev": "cd frontend && npm run dev → http://127.0.0.1:5173",
        }
    return FileResponse(index)


if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
