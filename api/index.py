"""
Vercel Python entrypoint for Sylva FastAPI (slim deps — no Earth Engine).

Secrets: set GEMINI_API_KEY / SENSOR_INGEST_TOKEN / etc. in Vercel
Project → Settings → Environment Variables (never VITE_*).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SYLVA_API_ONLY", "1")
os.environ.setdefault("VERCEL", "1")
os.environ.setdefault("ENABLE_NDVI", "0")
os.environ.setdefault("ENABLE_API_DOCS", "0")

from app.main import app  # noqa: E402

__all__ = ["app"]
