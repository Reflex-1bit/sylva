"""
Sylva data models — request/response schemas
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Request ──────────────────────────────────────────────────────────────────

class FarmProfileRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Farm centre latitude")
    lon: float = Field(..., ge=-180, le=180, description="Farm centre longitude")
    radius_km: float = Field(default=5.0, ge=0.5, le=100.0, description="Radius in km")
    country: Optional[str] = Field(default=None, description="Country name (ISO or common)")

    model_config = {"json_schema_extra": {"example": {"lat": 37.9, "lon": -4.7, "radius_km": 5, "country": "Spain"}}}


# ── Soil sub-models ───────────────────────────────────────────────────────────

class SoilDepthReading(BaseModel):
    depth_label: str
    value: Optional[float]

class SoilProperty(BaseModel):
    units: Optional[str]
    depths: dict[str, Optional[float]]

class TopsoilSummary(BaseModel):
    ph: Optional[float]
    organic_carbon_g_kg: Optional[float]
    nitrogen_g_kg: Optional[float]
    clay_pct: Optional[float]
    sand_pct: Optional[float]
    silt_pct: Optional[float]
    bulk_density_kg_dm3: Optional[float]
    cec_cmol_kg: Optional[float]
    texture_class: Optional[str]

class SoilProfile(BaseModel):
    source: str
    topsoil: TopsoilSummary
    raw_properties: Optional[dict] = None


# ── Topography sub-models ─────────────────────────────────────────────────────

class ElevationStats(BaseModel):
    min_m: float
    mean_m: float
    max_m: float

class SlopeStats(BaseModel):
    mean_deg: float
    max_deg: float

class TopographyProfile(BaseModel):
    source: str
    demtype: str
    elevation: ElevationStats
    slope: SlopeStats
    aspect_mean_deg: Optional[float] = None


# ── NDVI sub-models ───────────────────────────────────────────────────────────

class NDVIProfile(BaseModel):
    source: str
    n_observations: int
    mean_ndvi: float
    min_ndvi: float
    max_ndvi: float
    health_score: float = Field(..., ge=0, le=1, description="Normalised vegetation health 0–1")
    health_label: str
    outliers_removed: int


# ── Species sub-model ─────────────────────────────────────────────────────────

class SpeciesObservation(BaseModel):
    name: str
    occurrences: int


# ── Top-level response ────────────────────────────────────────────────────────

class FarmProfile(BaseModel):
    lat: float
    lon: float
    radius_km: float
    country: Optional[str]
    bbox: dict[str, float]
    soil: Optional[SoilProfile] = None
    topography: Optional[TopographyProfile] = None
    ndvi: Optional[NDVIProfile] = None
    observed_species: Optional[list[SpeciesObservation]] = None
    errors: dict[str, str] = {}
    warnings: list[str] = []
