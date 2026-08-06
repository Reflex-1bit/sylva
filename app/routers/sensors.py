"""
Sylva — sensor ingest stub for ESP32 soil nodes.

Accepts offline-buffered batches from field hardware. Persistence is
in-memory for the prototype; swap for Postgres/Timescale later.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

LOG = logging.getLogger("sylva.router.sensors")
router = APIRouter()

# Prototype store: device_id → list of samples
_STORE: dict[str, list[dict[str, Any]]] = {}


class SensorSample(BaseModel):
    ts_unix: int
    moisture_raw: Optional[int] = None
    moisture_pct: Optional[float] = None
    temp_c: Optional[float] = None
    ec_us_cm: Optional[float] = None
    battery_v: Optional[float] = None
    rssi: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class SensorBatch(BaseModel):
    device_id: str = Field(..., min_length=3, max_length=64)
    firmware: str = "0.1.0"
    samples: list[SensorSample] = Field(..., min_length=1, max_length=200)


@router.post("/sensors/ingest")
async def ingest_batch(
    batch: SensorBatch,
    x_device_token: str | None = Header(default=None),
):
    """
    Accept a batch of soil-node readings.
    Auth is a shared device token for the prototype (tighten later).
    """
    # Optional: set SENSOR_INGEST_TOKEN in .env to enforce
    import os

    expected = os.getenv("SENSOR_INGEST_TOKEN")
    if expected and x_device_token != expected:
        raise HTTPException(status_code=401, detail="invalid device token")

    bucket = _STORE.setdefault(batch.device_id, [])
    for s in batch.samples:
        bucket.append(s.model_dump())
    # keep last 5000 per device in memory
    if len(bucket) > 5000:
        _STORE[batch.device_id] = bucket[-5000:]

    LOG.info("ingest %s: +%d samples (total %d)", batch.device_id, len(batch.samples), len(_STORE[batch.device_id]))
    return {
        "status": "ok",
        "device_id": batch.device_id,
        "accepted": len(batch.samples),
        "stored_total": len(_STORE[batch.device_id]),
    }


@router.get("/sensors/{device_id}/latest")
async def latest(device_id: str, n: int = 20):
    rows = _STORE.get(device_id) or []
    return {"device_id": device_id, "samples": rows[-n:]}
