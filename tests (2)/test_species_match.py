import pytest
from app.models.farm import FarmProfile, SoilProfile, TopsoilSummary, NDVIProfile
from app.services.species_match_service import SpeciesMatchService
from app.models.match import SpeciesMatchScore

@pytest.fixture
def mock_species_db(tmp_path):
    # Create a temporary species database file
    db_file = tmp_path / "species_db_test.json"
    data = [
        {
            "species": "Acacia aneura",
            "common_names": ["mulga"],
            "soil_ph_min": 5.5,
            "soil_ph_max": 8.0,
            "rainfall_min_mm": 100,
            "rainfall_max_mm": 500,
            "drought_tolerance": "high",
            "nitrogen_fixing": True,
            "growth_rate": "slow",
            "uses": ["food", "timber", "fodder"],
            "soil_texture_preference": ["sand", "loam"]
        },
        {
            "species": "Abelmoschus moschatus",
            "common_names": ["musk mallow"],
            "soil_ph_min": 6.0,
            "soil_ph_max": 7.8,
            "rainfall_min_mm": 1000,
            "rainfall_max_mm": 1400,
            "drought_tolerance": "medium",
            "nitrogen_fixing": False,
            "growth_rate": "moderate",
            "uses": ["food", "medicine"],
            "soil_texture_preference": ["sand", "loam", "clay"]
        },
        {
            "species": "Acidophile tree",
            "common_names": ["acid lover"],
            "soil_ph_min": 4.0,
            "soil_ph_max": 5.4,
            "rainfall_min_mm": 800,
            "rainfall_max_mm": 1200,
            "drought_tolerance": "low",
            "nitrogen_fixing": False,
            "growth_rate": "fast",
            "uses": ["timber"],
            "soil_texture_preference": ["clay"]
        }
    ]
    import json
    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return str(db_file)

def test_ph_hard_filter(mock_species_db):
    service = SpeciesMatchService(db_path=mock_species_db)
    
    # 1. Farm with pH 7.0 (Abelmoschus and Acacia should match; Acidophile should be filtered out)
    topsoil = TopsoilSummary(
        ph=7.0, texture_class="loam",
        organic_carbon_g_kg=None, nitrogen_g_kg=None, clay_pct=None, 
        sand_pct=None, silt_pct=None, bulk_density_kg_dm3=None, cec_cmol_kg=None
    )
    farm = FarmProfile(
        lat=0.0, lon=0.0, radius_km=1.0, country="Test", bbox={},
        soil=SoilProfile(source="test", topsoil=topsoil),
        ndvi=None
    )
    
    matches = service.match_species(farm, requested_uses=[])
    species_names = [m.species for m in matches]
    
    assert "Acacia aneura" in species_names
    assert "Abelmoschus moschatus" in species_names
    assert "Acidophile tree" not in species_names

def test_soil_texture_scoring(mock_species_db):
    service = SpeciesMatchService(db_path=mock_species_db)
    
    # Acidophile tree prefers "clay"
    topsoil = TopsoilSummary(
        ph=5.0, texture_class="clay",
        organic_carbon_g_kg=None, nitrogen_g_kg=None, clay_pct=None, 
        sand_pct=None, silt_pct=None, bulk_density_kg_dm3=None, cec_cmol_kg=None
    )
    farm = FarmProfile(
        lat=0.0, lon=0.0, radius_km=1.0, country="Test", bbox={},
        soil=SoilProfile(source="test", topsoil=topsoil),
        ndvi=None
    )
    
    matches = service.match_species(farm, requested_uses=[])
    
    # Find Acidophile tree match score
    acidophile_match = next(m for m in matches if m.species == "Acidophile tree")
    # Should get 15 points for clay texture preference match
    assert acidophile_match.score_breakdown["texture_match"] == 15

def test_use_case_alignment_scoring(mock_species_db):
    service = SpeciesMatchService(db_path=mock_species_db)
    
    topsoil = TopsoilSummary(
        ph=6.5, texture_class="loam",
        organic_carbon_g_kg=None, nitrogen_g_kg=None, clay_pct=None, 
        sand_pct=None, silt_pct=None, bulk_density_kg_dm3=None, cec_cmol_kg=None
    )
    farm = FarmProfile(
        lat=0.0, lon=0.0, radius_km=1.0, country="Test", bbox={},
        soil=SoilProfile(source="test", topsoil=topsoil),
        ndvi=None
    )
    
    # Requesting "timber" and "fodder"
    # Acacia has both "timber" and "fodder" -> should get 25 points
    # Abelmoschus has neither -> should get 0 points
    matches = service.match_species(farm, requested_uses=["timber", "fodder"])
    
    acacia_match = next(m for m in matches if m.species == "Acacia aneura")
    abelmoschus_match = next(m for m in matches if m.species == "Abelmoschus moschatus")
    
    assert acacia_match.score_breakdown["use_alignment"] == 25
    assert abelmoschus_match.score_breakdown["use_alignment"] == 0

def test_nitrogen_fixing_scoring(mock_species_db):
    service = SpeciesMatchService(db_path=mock_species_db)
    
    topsoil = TopsoilSummary(
        ph=6.5, texture_class="loam",
        organic_carbon_g_kg=None, nitrogen_g_kg=None, clay_pct=None, 
        sand_pct=None, silt_pct=None, bulk_density_kg_dm3=None, cec_cmol_kg=None
    )
    farm = FarmProfile(
        lat=0.0, lon=0.0, radius_km=1.0, country="Test", bbox={},
        soil=SoilProfile(source="test", topsoil=topsoil),
        ndvi=None
    )
    
    matches = service.match_species(farm, requested_uses=[])
    
    acacia_match = next(m for m in matches if m.species == "Acacia aneura")
    abelmoschus_match = next(m for m in matches if m.species == "Abelmoschus moschatus")
    
    assert acacia_match.score_breakdown["nitrogen_fixing"] == 15
    assert abelmoschus_match.score_breakdown["nitrogen_fixing"] == 0

def test_degradation_bonus(mock_species_db):
    service = SpeciesMatchService(db_path=mock_species_db)
    
    topsoil = TopsoilSummary(
        ph=6.5, texture_class="loam",
        organic_carbon_g_kg=None, nitrogen_g_kg=None, clay_pct=None, 
        sand_pct=None, silt_pct=None, bulk_density_kg_dm3=None, cec_cmol_kg=None
    )
    # NDVI of 0.2 means degraded farm
    ndvi = NDVIProfile(
        source="test", n_observations=1,
        mean_ndvi=0.2, min_ndvi=0, max_ndvi=1,
        health_score=0.2, health_label="degraded", outliers_removed=0
    )
    farm = FarmProfile(
        lat=0.0, lon=0.0, radius_km=1.0, country="Test", bbox={},
        soil=SoilProfile(source="test", topsoil=topsoil),
        ndvi=ndvi
    )
    
    matches = service.match_species(farm, requested_uses=[])
    
    acacia_match = next(m for m in matches if m.species == "Acacia aneura")
    abelmoschus_match = next(m for m in matches if m.species == "Abelmoschus moschatus")
    
    # Acacia is N-fixing AND high drought tolerance -> should get degradation bonus of 15
    assert acacia_match.score_breakdown["degradation_bonus"] == 15
    # Abelmoschus is not -> 0 bonus
    assert abelmoschus_match.score_breakdown["degradation_bonus"] == 0
