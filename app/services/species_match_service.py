"""
Sylva — Species matching service

Scoring system (max 100 points before degradation bonus):
  pH hard filter     — species outside farm pH range are excluded entirely
  texture_match      — 15 pts if species prefers the farm's soil texture
  use_alignment      — 25 pts per matching requested use (uncapped if no uses requested)
  nitrogen_fixing    — 15 pts bonus
  degradation_bonus  — 15 pts if farm is degraded (NDVI health_score <= 0.3)
                        AND species is nitrogen-fixing AND drought tolerant
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.models.farm import FarmProfile
from app.models.match import SpeciesMatchScore

# Default DB path — the extraction script writes to data/species_db.json
DEFAULT_DB_PATH = Path("data/species_db.json")

DEGRADATION_NDVI_THRESHOLD = 0.3


class SpeciesMatchService:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._db: list[dict] | None = None

    def _load_db(self) -> list[dict]:
        if self._db is None:
            if not self._db_path.exists():
                raise FileNotFoundError(
                    f"Species DB not found at {self._db_path}. "
                    "Run ingest_aft_pdfs.py first."
                )
            self._db = json.loads(self._db_path.read_text(encoding="utf-8"))
        return self._db

    # ── Scoring helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _ph_passes(species: dict, farm_ph: float) -> bool:
        """Hard filter — returns False if farm pH is outside species tolerance."""
        lo = species.get("soil_ph_min")
        hi = species.get("soil_ph_max")
        if lo is None or hi is None:
            return True  # unknown tolerance → don't filter out
        return lo <= farm_ph <= hi

    @staticmethod
    def _texture_score(species: dict, farm_texture: Optional[str]) -> float:
        if not farm_texture:
            return 0.0
        prefs = [t.lower() for t in species.get("soil_texture_preference") or []]
        if not prefs:
            return 0.0
        return 15.0 if farm_texture.lower() in prefs else 0.0

    @staticmethod
    def _use_alignment_score(species: dict, requested_uses: list[str]) -> float:
        if not requested_uses:
            return 0.0
        species_uses = [u.lower() for u in species.get("uses") or []]
        has_match = any(u.lower() in species_uses for u in requested_uses)
        return 25.0 if has_match else 0.0

    @staticmethod
    def _nitrogen_fixing_score(species: dict) -> float:
        return 15.0 if species.get("nitrogen_fixing") else 0.0

    @staticmethod
    def _degradation_bonus(species: dict, farm: FarmProfile) -> float:
        """
        Extra 15 pts for degraded farms (low NDVI) — only applies to species
        that are both nitrogen-fixing AND highly drought tolerant, since these
        are the best candidates for land restoration.
        """
        if farm.ndvi is None:
            return 0.0
        if farm.ndvi.health_score > DEGRADATION_NDVI_THRESHOLD:
            return 0.0
        is_n_fixer = bool(species.get("nitrogen_fixing"))
        is_drought_tolerant = (species.get("drought_tolerance") or "").lower() == "high"
        return 15.0 if (is_n_fixer and is_drought_tolerant) else 0.0

    # ── Public interface ──────────────────────────────────────────────────────

    def match_species(
        self,
        farm: FarmProfile,
        requested_uses: list[str] | None = None,
        top_n: int | None = None,
    ) -> list[SpeciesMatchScore]:
        """
        Return species ranked by suitability for the given farm profile.

        Args:
            farm:           FarmProfile from the /farm/profile endpoint.
            requested_uses: Optional list of desired uses (e.g. ["timber", "fodder"]).
                            If empty/None, use_alignment scoring is skipped.
            top_n:          Return only the top N matches. None = return all.
        """
        if requested_uses is None:
            requested_uses = []

        db = self._load_db()
        farm_ph = farm.soil.topsoil.ph if farm.soil else None
        farm_texture = farm.soil.topsoil.texture_class if farm.soil else None

        results: list[SpeciesMatchScore] = []

        for sp in db:
            # Hard pH filter
            if farm_ph is not None and not self._ph_passes(sp, farm_ph):
                continue

            breakdown: dict[str, float] = {
                "texture_match":    self._texture_score(sp, farm_texture),
                "use_alignment":    self._use_alignment_score(sp, requested_uses),
                "nitrogen_fixing":  self._nitrogen_fixing_score(sp),
                "degradation_bonus": self._degradation_bonus(sp, farm),
            }

            results.append(
                SpeciesMatchScore(
                    species=sp.get("species", ""),
                    common_names=sp.get("common_names") or [],
                    total_score=sum(breakdown.values()),
                    score_breakdown=breakdown,
                    uses=sp.get("uses") or [],
                    nitrogen_fixer=bool(sp.get("nitrogen_fixing")),
                    drought_tolerance=sp.get("drought_tolerance"),
                    growth_rate=sp.get("growth_rate"),
                    soil_ph_min=sp.get("soil_ph_min"),
                    soil_ph_max=sp.get("soil_ph_max"),
                    rainfall_min_mm=sp.get("rainfall_min_mm"),
                    rainfall_max_mm=sp.get("rainfall_max_mm"),
                    soil_texture_preference=sp.get("soil_texture_preference") or [],
                )
            )

        # Sort by total score descending
        results.sort(key=lambda r: r.total_score, reverse=True)

        if top_n is not None:
            results = results[:top_n]

        return results
