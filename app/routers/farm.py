"""
Sylva — /farm router
"""

import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException, Query

from app.models.farm import FarmProfile, FarmProfileRequest
from app.utils.geometry import bbox_from_radius
from app.services import soil_service, topo_service, ndvi_service, gbif_service

LOG = logging.getLogger("sylva.router.farm")
router = APIRouter()

# Hard ceiling for the whole profile request. Individual services have their
# own (shorter) timeouts; this guards against the total stacking up.
PROFILE_TIMEOUT_S = 150


async def _build_profile(req: FarmProfileRequest) -> FarmProfile:
    bbox = bbox_from_radius(req.lat, req.lon, req.radius_km)
    errors: dict[str, str] = {}
    warnings: list[str] = []

    profile = FarmProfile(
        lat=req.lat,
        lon=req.lon,
        radius_km=req.radius_km,
        country=req.country,
        bbox=bbox,
    )

    # Run the independent external calls concurrently rather than serially.
    tasks = {
        "soil": soil_service.fetch_soil(req.lat, req.lon),
        "ndvi": ndvi_service.fetch_ndvi(bbox),
        "species": gbif_service.fetch_species(bbox),
    }

    api_key = os.environ.get("OPENTOPO_API_KEY")
    if api_key:
        tasks["topography"] = topo_service.fetch_topography(bbox, api_key=api_key)
    else:
        warnings.append("OPENTOPO_API_KEY not set — topography skipped")

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    for name, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            LOG.warning("%s failed: %s", name, result)
            errors[name] = str(result)
            continue
        if name == "soil":
            profile.soil = result
        elif name == "ndvi":
            profile.ndvi = result
        elif name == "species":
            profile.observed_species = result
        elif name == "topography":
            profile.topography = result

    profile.errors = errors
    profile.warnings = warnings
    return profile


@router.post("/farm/profile", response_model=FarmProfile)
async def get_farm_profile(req: FarmProfileRequest):
    """
    Full farm profile: soil + topography + NDVI vegetation health + observed
    species. Each source runs concurrently and independently — partial results
    are returned if a source fails.
    """
    try:
        return await asyncio.wait_for(_build_profile(req), timeout=PROFILE_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"farm profile timed out after {PROFILE_TIMEOUT_S}s",
        )


@router.get("/farm/profile", response_model=FarmProfile)
async def get_farm_profile_get(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, ge=0.5, le=100.0),
    country: str | None = Query(default=None),
):
    """GET convenience wrapper — same behaviour as POST."""
    return await get_farm_profile(
        FarmProfileRequest(lat=lat, lon=lon, radius_km=radius_km, country=country)
    )
