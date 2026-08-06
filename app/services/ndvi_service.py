"""
Sylva — NDVI timeseries service (Google Earth Engine via ee)

Disabled by default in production — ee.Initialize() can hang for minutes
without credentials, which freezes the website on "Working…".

Set ENABLE_NDVI=1 and provide Earth Engine auth to turn it on.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.models.farm import NDVIProfile

LOG = logging.getLogger("sylva.ndvi")

NDVI_MIN = -1.0
NDVI_MAX = 1.0
HEALTH_NDVI_LOW = 0.2
HEALTH_NDVI_HIGH = 0.8


def _health_score(mean_ndvi: float) -> float:
    score = (mean_ndvi - HEALTH_NDVI_LOW) / (HEALTH_NDVI_HIGH - HEALTH_NDVI_LOW)
    return round(max(0.0, min(score, 1.0)), 3)


def _health_label(mean_ndvi: float) -> str:
    if mean_ndvi >= 0.6:
        return "healthy vegetation"
    if mean_ndvi >= 0.4:
        return "moderate vegetation"
    if mean_ndvi >= 0.2:
        return "sparse / stressed vegetation"
    if mean_ndvi >= 0.0:
        return "bare soil or very sparse"
    return "water / non-vegetated"


def _summarise(values: list[float], outliers: int, source: str) -> NDVIProfile:
    mean_ndvi = round(sum(values) / len(values), 4)
    return NDVIProfile(
        source=source,
        n_observations=len(values),
        mean_ndvi=mean_ndvi,
        min_ndvi=round(min(values), 4),
        max_ndvi=round(max(values), 4),
        health_score=_health_score(mean_ndvi),
        health_label=_health_label(mean_ndvi),
        outliers_removed=outliers,
    )


def _ndvi_enabled() -> bool:
    return os.getenv("ENABLE_NDVI", "").strip().lower() in {"1", "true", "yes", "on"}


async def fetch_ndvi(bbox: dict, years: int = 2) -> NDVIProfile:
    """
    Pull Sentinel-2 NDVI via Earth Engine.
    Fails immediately unless ENABLE_NDVI=1 (avoids deploy hangs).
    """
    if not _ndvi_enabled():
        raise RuntimeError("NDVI skipped (set ENABLE_NDVI=1 + Earth Engine auth to enable)")

    try:
        import ee
    except ImportError as e:
        raise RuntimeError("earthengine-api not installed") from e

    try:
        ee.Initialize()
    except Exception as e:
        raise RuntimeError(f"Earth Engine init failed: {e}") from e

    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - years)

    region = ee.Geometry.Rectangle(
        [bbox["west"], bbox["south"], bbox["east"], bbox["north"]]
    )

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        .filterBounds(region)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI"))
    )

    raw = collection.getRegion(region, 100).getInfo()
    if not raw or len(raw) < 2:
        raise RuntimeError("Earth Engine returned no NDVI data for this region/period")

    headers = raw[0]
    ndvi_idx = headers.index("NDVI")
    values: list[float] = []
    outliers = 0
    for row in raw[1:]:
        v = row[ndvi_idx]
        if v is None:
            continue
        if NDVI_MIN <= v <= NDVI_MAX:
            values.append(v)
        else:
            outliers += 1

    if not values:
        raise RuntimeError("No valid NDVI values after outlier removal")

    profile = _summarise(values, outliers, "Sentinel-2 SR (Google Earth Engine)")
    LOG.info(
        "NDVI: ok — n=%d, mean=%.3f, outliers_removed=%d, label=%s",
        profile.n_observations,
        profile.mean_ndvi,
        outliers,
        profile.health_label,
    )
    return profile
