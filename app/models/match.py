"""
Sylva — Species match result models
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.farm import FarmProfile, FarmProfileRequest


class SpeciesMatchScore(BaseModel):
    species: str
    common_names: list[str] = []
    total_score: float
    score_breakdown: dict[str, float]
    uses: list[str] = []
    nitrogen_fixer: bool = False
    drought_tolerance: Optional[str] = None
    growth_rate: Optional[str] = None
    soil_ph_min: Optional[float] = None
    soil_ph_max: Optional[float] = None
    rainfall_min_mm: Optional[int] = None
    rainfall_max_mm: Optional[int] = None
    soil_texture_preference: list[str] = []


class FarmMatchRequest(FarmProfileRequest):
    requested_uses: list[str] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=50)


class FarmMatchResponse(BaseModel):
    farm_profile: FarmProfile
    matches: list[SpeciesMatchScore]


class FarmRecommendations(BaseModel):
    """Full recommendation response: profile + ranked species + generated plan."""

    profile: dict
    recommended_species: list[SpeciesMatchScore]
    plan: dict
    plan_model: str
    retrieved_knowledge: list[str] = []
