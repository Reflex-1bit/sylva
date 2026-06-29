import json
import os
from typing import List, Optional
from app.models.farm import FarmProfile
from app.models.match import SpeciesMatchScore

class SpeciesMatchService:
    def __init__(self, db_path: str = "data/species_db.json"):
        self.db_path = db_path
        self.db = []
        self.load_db()
        
    def load_db(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
        else:
            self.db = []
            
    def match_species(self, farm_profile: FarmProfile, requested_uses: List[str], top_n: int = 10) -> List[SpeciesMatchScore]:
        results = []
        
        farm_ph = None
        farm_texture = None
        if farm_profile.soil and farm_profile.soil.topsoil:
            farm_ph = farm_profile.soil.topsoil.ph
            farm_texture = farm_profile.soil.topsoil.texture_class
            
        farm_ndvi = None
        if farm_profile.ndvi:
            farm_ndvi = farm_profile.ndvi.mean_ndvi

        for species in self.db:
            # 1. Hard filters
            if farm_ph is not None:
                min_ph = species.get("soil_ph_min")
                max_ph = species.get("soil_ph_max")
                if min_ph is not None and farm_ph < min_ph:
                    continue
                if max_ph is not None and farm_ph > max_ph:
                    continue
                    
            # 2. Soft scores
            score = 0
            breakdown = {}
            
            # Soil texture (15)
            pref_textures = species.get("soil_texture_preference", [])
            texture_score = 0
            if farm_texture and pref_textures:
                if any(t.lower() in farm_texture.lower() for t in pref_textures):
                    texture_score = 15
            elif not pref_textures: # If it doesn't care, give some points
                texture_score = 5
            score += texture_score
            breakdown["texture_match"] = texture_score
            
            # Drought tolerance vs NDVI (20)
            drought_tol = str(species.get("drought_tolerance", "")).lower()
            drought_score = 0
            if farm_ndvi is not None:
                if farm_ndvi < 0.3 and "high" in drought_tol:
                    drought_score = 20
                elif farm_ndvi < 0.5 and "medium" in drought_tol:
                    drought_score = 15
                elif farm_ndvi >= 0.5:
                    drought_score = 20 # doesn't matter as much
            score += drought_score
            breakdown["drought_tolerance"] = drought_score
            
            # Use-case alignment (25)
            use_score = 0
            species_uses = [u.lower() for u in species.get("uses", [])]
            if requested_uses and species_uses:
                matches = sum(1 for req in requested_uses if any(req.lower() in su for su in species_uses))
                use_score = min(25, int((matches / len(requested_uses)) * 25))
            elif not requested_uses:
                use_score = 25 # No specific uses requested
            score += use_score
            breakdown["use_alignment"] = use_score
            
            # N-fixation (15)
            n_fix_score = 15 if species.get("nitrogen_fixing") else 0
            score += n_fix_score
            breakdown["nitrogen_fixing"] = n_fix_score
            
            # Growth rate (10)
            growth = str(species.get("growth_rate", "")).lower()
            growth_score = 10 if "fast" in growth else 5 if "moderate" in growth else 0
            score += growth_score
            breakdown["growth_rate"] = growth_score
            
            # Degradation bonus (15)
            deg_bonus = 0
            if farm_ndvi is not None and farm_ndvi < 0.3:
                # If farm is degraded (low NDVI), give bonus to hardy, N-fixing, fast growing species
                if species.get("nitrogen_fixing") and "high" in drought_tol:
                    deg_bonus = 15
            score += deg_bonus
            breakdown["degradation_bonus"] = deg_bonus
            
            results.append(SpeciesMatchScore(
                species=species.get("species", "Unknown"),
                total_score=score,
                score_breakdown=breakdown,
                profile=species
            ))
            
        results.sort(key=lambda x: x.total_score, reverse=True)
        return results[:top_n]
