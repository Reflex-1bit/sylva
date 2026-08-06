"""
Sylva — topography via Open-Meteo elevation (no rasterio / GDAL required).

Samples a small elevation grid around the farm bbox and derives mean elevation
plus a coarse slope estimate. OpenTopography+rasterio was failing in the
Docker image; this path is free, keyless, and deploy-friendly.
"""

from __future__ import annotations

import logging
import math

import httpx

from app.models.farm import ElevationStats, SlopeStats, TopographyProfile

LOG = logging.getLogger("sylva.topo")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"


async def fetch_topography(
    bbox: dict,
    api_key: str | None = None,  # unused — kept for call-site compatibility
    demtype: str = "open-meteo",
    timeout: int = 20,
) -> TopographyProfile:
    """Estimate elevation/slope from an Open-Meteo point grid over the bbox."""
    _ = api_key  # Open-Meteo needs no key

    south, north = bbox["south"], bbox["north"]
    west, east = bbox["west"], bbox["east"]

    # 3x3 grid across the bbox
    lats = [south, (south + north) / 2, north]
    lons = [west, (west + east) / 2, east]
    lat_params: list[float] = []
    lon_params: list[float] = []
    for la in lats:
        for lo in lons:
            lat_params.append(la)
            lon_params.append(lo)

    params = {
        "latitude": ",".join(f"{v:.5f}" for v in lat_params),
        "longitude": ",".join(f"{v:.5f}" for v in lon_params),
    }

    LOG.info("Open-Meteo: elevation grid (%d points)", len(lat_params))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    elevs = data.get("elevation") or []
    elevs = [float(e) for e in elevs if e is not None]
    if not elevs:
        raise RuntimeError("Open-Meteo returned no elevation values")

    mean_m = sum(elevs) / len(elevs)
    min_m = min(elevs)
    max_m = max(elevs)

    # Coarse slope from centre vs corners, using bbox span in metres
    lat_m = abs(north - south) * 111_320
    lon_m = abs(east - west) * 111_320 * max(0.2, math.cos(math.radians((south + north) / 2)))
    run = max(lat_m, lon_m, 1.0)
    rise = max_m - min_m
    mean_slope = math.degrees(math.atan(rise / run))
    max_slope = min(45.0, mean_slope * 1.8)

    elev = ElevationStats(
        min_m=round(min_m, 1),
        mean_m=round(mean_m, 1),
        max_m=round(max_m, 1),
    )
    slp = SlopeStats(mean_deg=round(mean_slope, 2), max_deg=round(max_slope, 2))

    LOG.info("Open-Meteo: ok — mean elev=%.0fm, slope≈%.1f°", elev.mean_m, slp.mean_deg)
    return TopographyProfile(
        source="Open-Meteo elevation",
        demtype=demtype,
        elevation=elev,
        slope=slp,
        aspect_mean_deg=None,
    )
