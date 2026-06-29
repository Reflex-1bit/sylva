from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.farm import FarmProfileRequest, FarmProfile

class FarmMatchRequest(FarmProfileRequest):
    requested_uses: List[str] = Field(default_factory=list, description="Requested uses (e.g. food, timber, nitrogen_fixing)")
    top_n: int = Field(default=10, description="Number of top species to return")
    
class SpeciesMatchScore(BaseModel):
    species: str
    total_score: float
    score_breakdown: dict
    profile: dict
    
class FarmMatchResponse(BaseModel):
    farm_profile: FarmProfile
    matches: List[SpeciesMatchScore]
