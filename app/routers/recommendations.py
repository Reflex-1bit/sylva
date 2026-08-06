"""
Sylva — /farm/recommendations router

Chains:
  farm profile → SpeciesMatchService → rag_service → FarmRecommendations
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from app.models.farm import FarmProfileRequest
from app.models.match import FarmRecommendations
from app.routers.farm import PROFILE_TIMEOUT_S, _build_profile
from app.services import rag_service
from app.services.species_match_service import SpeciesMatchService

LOG = logging.getLogger("sylva.router.recommendations")
router = APIRouter()
_match_service = SpeciesMatchService()

RECOMMEND_TIMEOUT_S = PROFILE_TIMEOUT_S + 35


@router.get("/farm/recommendations", response_model=FarmRecommendations)
async def get_recommendations(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, ge=0.5, le=100.0),
    country: str | None = Query(default=None),
    uses: str | None = Query(
        default=None,
        description="comma-separated desired uses, e.g. timber,fodder",
    ),
    top_n: int = Query(default=10, ge=1, le=50),
):
    """Profile the farm, match suitable species, generate a transition plan."""
    try:
        return await asyncio.wait_for(
            _recommend(lat, lon, radius_km, country, uses, top_n),
            timeout=RECOMMEND_TIMEOUT_S,
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Recommendations timed out after {RECOMMEND_TIMEOUT_S}s. Try again.",
        )


async def _recommend(
    lat: float,
    lon: float,
    radius_km: float,
    country: str | None,
    uses: str | None,
    top_n: int,
) -> FarmRecommendations:
    req = FarmProfileRequest(lat=lat, lon=lon, radius_km=radius_km, country=country)
    profile = await _build_profile(req)

    if profile.soil is None or profile.soil.topsoil.ph is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "No soil data for this location, so species can't be matched. "
                "Try a coordinate on cultivated land."
            ),
        )

    requested_uses = [u.strip() for u in uses.split(",") if u.strip()] if uses else []

    try:
        matches = _match_service.match_species(profile, requested_uses, top_n=top_n)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    match_dicts = [m.model_dump() for m in matches]
    rag_result = await rag_service.generate_farm_plan(profile.model_dump(), match_dicts)

    return FarmRecommendations(
        profile=profile.model_dump(),
        recommended_species=matches,
        plan=rag_result.plan,
        plan_model=rag_result.model,
        retrieved_knowledge=rag_result.retrieved_chunks,
    )
