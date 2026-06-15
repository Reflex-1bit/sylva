"""
Sylva — Agroforestry Intelligence Platform
Backend API
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import farm

app = FastAPI(
    title="Sylva",
    description="Agroforestry intelligence platform — farm profiling API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(farm.router, prefix="/api/v1", tags=["farm"])


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
