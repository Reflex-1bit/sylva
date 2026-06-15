"""
Sylva — NDVI timeseries service (Google Earth Engine via ee)

NDVI is strictly bounded [-1, 1]. Values outside this range are nodata/fill
values from the satellite pipeline and must be removed before any analysis.
This was the core bug in the previous pipeline run.
"""

import logging
from datetime import datetime, timezone

from app.models.farm import NDVIProfile

LOG = logging.getLogger("sylva.ndvi")

NDVI_MIN = -1.0
NDVI_MAX = 1.0

# Health score maps NDVI -> [0, 1] via a clamped linear ramp.
# Below 0.2 = effectively bare/stressed (score 0), above 0.8 = dense
# healthy canopy (score 1). This range is standard for agricultural land.
HEALTH_NDVI_LOW = 0.2
HEALTH_NDVI_HIGH = 0.8


def _health_score(mean_ndvi: float) -> float:
    """Clamped linear normalisation of mean NDVI to a 0-1 health score."""
    score = (mean_ndvi - HEALTH_NDVI_LOW) / (HEALTH_NDVI_HIGH - HEALTH_NDVI_LOW)
    return round(max(0.0, min(score, 1.0)), 3)


def _health_label(mean_ndvi: float) -> str:
    """Human-readable band for a mean NDVI value."""
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
    """Build an NDVIProfile from a clean list of in-range NDVI values."""
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


async def fetch_ndvi(bbox: dict, years: int = 2) -> NDVIProfile:
    """
    Pull Sentinel-2 NDVI timeseries via Earth Engine Python API.
    Requires: earthengine-api authenticated (ee.Authenticate() run once).
    """
    try:
        import ee
    except ImportError:
        raise RuntimeError("earthengine-api not installed (pip install earthengine-api)")

    try:
        ee.Initialize()
    except Exception as e:
        raise RuntimeError(f"Earth Engine init failed: {e}")

    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - years)

    region = ee.Geometry.Rectangle([bbox["west"], bbox["south"], bbox["east"], bbox["north"]])

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        .filterBounds(region)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI"))
    )

    raw = collection.getRegion(region, 100).getInfo()  # 100m scale
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
    LOG.info("NDVI: ok — n=%d, mean=%.3f, outliers_removed=%d, label=%s",
             profile.n_observations, profile.mean_ndvi, outliers, profile.health_label)
    return profile


def clean_ndvi_series(raw_series: dict[str, float]) -> NDVIProfile:
    """
    Utility: clean an already-fetched date->NDVI dict (e.g. from a saved JSON)
    and return an NDVIProfile. Removes values outside [-1, 1].
    This fixes the bug in the previous pipeline run.
    """
    values: list[float] = []
    outliers = 0
    for val in raw_series.values():
        if val is None:
            continue
        if NDVI_MIN <= val <= NDVI_MAX:
            values.append(val)
        else:
            outliers += 1

    if not values:
        raise RuntimeError(f"no valid NDVI values (removed {outliers} outliers)")

    return _summarise(values, outliers, "cleaned from saved series")
