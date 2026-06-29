from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
import asyncio
from app.models.match import FarmMatchRequest, FarmMatchResponse, SpeciesMatchScore
from app.models.farm import FarmProfile
from app.routers.farm import _build_profile
from app.services.species_match_service import SpeciesMatchService

router = APIRouter()

# Instantiate the service singleton
match_service = SpeciesMatchService()

@router.post("/farm/match", response_model=FarmMatchResponse)
async def get_farm_match(req: FarmMatchRequest):
    """
    Combined farm profile + species matching.
    Fetches the farm profile, then scores the agroforestree database against it.
    """
    try:
        # Re-use the profiling logic, passing it the base FarmProfileRequest properties
        profile_req = req # FarmMatchRequest inherits FarmProfileRequest
        farm_profile = await asyncio.wait_for(_build_profile(profile_req), timeout=150)
        
        # Match species
        matches = match_service.match_species(
            farm_profile=farm_profile, 
            requested_uses=req.requested_uses, 
            top_n=req.top_n
        )
        
        return FarmMatchResponse(
            farm_profile=farm_profile,
            matches=matches
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="farm profile timed out after 150s",
        )

@router.get("/species/search", response_model=List[SpeciesMatchScore])
async def search_species(
    soil_ph: Optional[float] = None,
    ndvi_health: Optional[float] = None,
    soil_texture: Optional[str] = None,
    uses: Optional[str] = None,
    top_n: int = 10
):
    """
    Direct species search bypassing the farm profiling step.
    Provide parameters directly to filter and score the database.
    """
    # Create a mock FarmProfile to use our existing scoring logic
    from app.models.farm import TopsoilSummary, NDVIProfile, SoilProfile
    
    soil_profile = None
    if soil_ph is not None or soil_texture is not None:
        topsoil = TopsoilSummary(
            ph=soil_ph,
            texture_class=soil_texture,
            organic_carbon_g_kg=None, nitrogen_g_kg=None, clay_pct=None, 
            sand_pct=None, silt_pct=None, bulk_density_kg_dm3=None, cec_cmol_kg=None
        )
        soil_profile = SoilProfile(source="mock", topsoil=topsoil)
        
    ndvi_profile = None
    if ndvi_health is not None:
        ndvi_profile = NDVIProfile(
            source="mock", n_observations=1,
            mean_ndvi=ndvi_health, min_ndvi=0, max_ndvi=1,
            health_score=ndvi_health, health_label="mock", outliers_removed=0
        )
        
    mock_profile = FarmProfile(
        lat=0, lon=0, radius_km=0, country=None, bbox={},
        soil=soil_profile, ndvi=ndvi_profile
    )
    
    requested_uses = uses.split(",") if uses else []
    
    matches = match_service.match_species(
        farm_profile=mock_profile,
        requested_uses=requested_uses,
        top_n=top_n
    )
    return matches

@router.post("/species/reload")
async def reload_species_db():
    """Reload the species database from disk."""
    match_service.load_db()
    return {"status": "success", "message": f"Loaded {len(match_service.db)} species."}
