# Sylva 🌳

**Agroforestry intelligence platform** — geospatial farm profiling API.

Given a GPS coordinate, Sylva pulls soil, topography, vegetation health, and observed species data to build a structured farm profile. This is the data foundation for species matching and agroforestry transition planning.

## Stack

- **FastAPI** — async REST API
- **SoilGrids (ISRIC)** — soil pH, organic carbon, texture, nitrogen, CEC
- **OpenTopography** — SRTM/COP30 DEM → elevation + slope
- **Google Earth Engine** — Sentinel-2 NDVI vegetation health timeseries
- **GBIF** — observed plant species occurrences

## Quickstart

```bash
# 1. Clone and set up environment
git clone https://github.com/YOUR_USERNAME/sylva.git
cd sylva
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set API keys
cp .env.example .env
# Edit .env and add your OPENTOPO_API_KEY

# 4. Authenticate Earth Engine (once)
earthengine authenticate

# 5. Run the API
uvicorn app.main:app --reload
```

API docs at: http://localhost:8000/docs

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/farm/profile` | Full farm profile (JSON body) |
| GET | `/api/v1/farm/profile` | Full farm profile (query params) |

### Example request

```bash
curl "http://localhost:8000/api/v1/farm/profile?lat=37.9&lon=-4.7&radius_km=5&country=Spain"
```

### Example response

```json
{
  "lat": 37.9,
  "lon": -4.7,
  "radius_km": 5.0,
  "country": "Spain",
  "bbox": { "south": 37.855, "north": 37.945, "west": -4.763, "east": -4.637 },
  "soil": {
    "topsoil": {
      "ph": 7.8,
      "organic_carbon_g_kg": 12.3,
      "texture_class": "clay loam",
      ...
    }
  },
  "topography": {
    "elevation": { "mean_m": 312.4, ... },
    "slope": { "mean_deg": 3.2, ... }
  },
  "ndvi": {
    "mean_ndvi": 0.42,
    "health_score": 0.61,
    "health_label": "moderate vegetation"
  },
  "observed_species": [
    { "name": "Olea europaea", "occurrences": 14 },
    ...
  ],
  "errors": {},
  "warnings": []
}
```

## Project structure

```
sylva/
├── app/
│   ├── main.py              # FastAPI app
│   ├── routers/
│   │   └── farm.py          # /farm/profile endpoint
│   ├── services/
│   │   ├── soil_service.py  # SoilGrids
│   │   ├── topo_service.py  # OpenTopography
│   │   ├── ndvi_service.py  # Earth Engine NDVI
│   │   └── gbif_service.py  # GBIF species
│   ├── models/
│   │   └── farm.py          # Pydantic schemas
│   └── utils/
│       ├── geometry.py      # Bbox / coordinate math
│       └── soil.py          # USDA texture classifier
├── tests/
├── requirements.txt
├── .env.example
└── .gitignore
```

## Roadmap

- [ ] Species agronomic database (AgroForestree extraction)
- [ ] Species suitability filter (pH, rainfall, frost tolerance)
- [ ] CAP eco-scheme eligibility checker (Spain)
- [ ] Financial projection engine (NPV, carbon credits)
- [ ] React frontend dashboard
