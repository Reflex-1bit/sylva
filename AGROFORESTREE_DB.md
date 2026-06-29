# Agroforestree Database Documentation

## Location
The fully parsed and structured Agroforestree database is stored as a JSON file at:
**`data/species_db.json`**

## Summary
- **Source**: Agroforestree (AFT) PDF profiles.
- **Total Species Extracted**: 611 species (out of the ~616 available, a few failed to parse or timed out due to API rate limits).
- **Format**: JSON array of objects.
- **Extraction Method**: Processed via Gemini 3.1 Flash Lite (`gemini-3.1-flash-lite`) using a concurrency pipeline to extract structured agronomic and environmental parameters directly from the PDF text.

## Schema
Each entry in the database is a structured JSON object representing a specific species, including environmental tolerances and potential uses. 

Here is an example of the schema:

```json
{
  "species": "Abelmoschus moschatus",
  "common_names": [
    "ornamental okra",
    "musk mallow",
    "annual hibiscus"
  ],
  "soil_ph_min": 6.0,
  "soil_ph_max": 7.8,
  "rainfall_min_mm": 1000,
  "rainfall_max_mm": 1400,
  "drought_tolerance": "medium",
  "nitrogen_fixing": false,
  "growth_rate": "moderate",
  "uses": [
    "food",
    "essential oils",
    "medicine",
    "fibre"
  ],
  "soil_texture_preference": [
    "sand",
    "loam",
    "clay"
  ]
}
```

### Key Fields
- `species`: Scientific name of the species (string).
- `common_names`: List of known common names (array of strings).
- `soil_ph_min` / `soil_ph_max`: Tolerated soil pH range (floats).
- `rainfall_min_mm` / `rainfall_max_mm`: Tolerated annual rainfall range in millimeters (integers).
- `drought_tolerance`: Resistance to drought; typically "low", "medium", or "high" (string).
- `nitrogen_fixing`: Whether the species fixes nitrogen in the soil (boolean).
- `growth_rate`: Typical growth rate, e.g., "slow", "moderate", "fast" (string).
- `uses`: Known applications for the species, such as "food", "timber", "medicine", "fodder", etc. (array of strings).
- `soil_texture_preference`: Preferred soil textures, such as "sand", "loam", "clay", "heavy clay" (array of strings).

## Usage in Application
The database is loaded by the FastAPI application for the `/farm/match` endpoint (and other related endpoints). 
When a farm profile is submitted, the matching algorithm in `app/services/species_match_service.py` evaluates the farm's environmental conditions (like pH and texture) against the ranges defined in this JSON database to score and recommend suitable species.
