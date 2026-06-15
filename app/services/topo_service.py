"""
Sylva — OpenTopography DEM service
"""

import logging
import math
import os
import tempfile
from pathlib import Path

import httpx
from app.models.farm import TopographyProfile, ElevationStats, SlopeStats

LOG = logging.getLogger("sylva.topo")

OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"
EARTH_KM_PER_DEG = 111.32


async def fetch_topography(
    bbox: dict,
    api_key: str | None = None,
    demtype: str = "COP30",
    timeout: int = 120,
) -> TopographyProfile:
    key = api_key or os.environ.get("OPENTOPO_API_KEY")
    if not key:
        raise RuntimeError("No OpenTopography API key — set OPENTOPO_API_KEY env var")

    params = {
        "demtype": demtype,
        "south": bbox["south"], "north": bbox["north"],
        "west": bbox["west"],  "east": bbox["east"],
        "outputFormat": "GTiff",
        "API_Key": key,
    }

    LOG.info("OpenTopography: downloading %s DEM", demtype)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(OPENTOPO_URL, params=params)
        resp.raise_for_status()

    ct = resp.headers.get("Content-Type", "")
    if not resp.content or "json" in ct or "html" in ct:
        raise RuntimeError(f"OpenTopography returned non-raster: {resp.text[:200]}")

    # Write to temp file and compute stats
    try:
        import numpy as np
        import rasterio
    except ImportError:
        raise RuntimeError("rasterio + numpy required for DEM stats (pip install rasterio numpy)")

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name

    try:
        with rasterio.open(tmp_path) as src:
            band = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                band[band == nodata] = np.nan
            res_x, res_y = src.res
            clat = (bbox["north"] + bbox["south"]) / 2
            mx = res_x * EARTH_KM_PER_DEG * 1000 * math.cos(math.radians(clat))
            my = res_y * EARTH_KM_PER_DEG * 1000
            dzdy, dzdx = np.gradient(band, my, mx)
            slope = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))
            # Aspect
            aspect = np.degrees(np.arctan2(-dzdx, dzdy)) % 360

        elev = ElevationStats(
            min_m=round(float(np.nanmin(band)), 1),
            mean_m=round(float(np.nanmean(band)), 1),
            max_m=round(float(np.nanmax(band)), 1),
        )
        slp = SlopeStats(
            mean_deg=round(float(np.nanmean(slope)), 2),
            max_deg=round(float(np.nanmax(slope)), 2),
        )
        aspect_mean = round(float(np.nanmean(aspect)), 1)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    LOG.info("OpenTopography: ok — mean elev=%.0fm, slope=%.1f°", elev.mean_m, slp.mean_deg)
    return TopographyProfile(
        source="OpenTopography",
        demtype=demtype,
        elevation=elev,
        slope=slp,
        aspect_mean_deg=aspect_mean,
    )
