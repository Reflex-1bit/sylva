# Sylva

**Agroforestry decision-support** for farms transitioning toward regenerative /
tree-integrated systems — with verifiable soil data from a low-cost field node.

Lead with the **plan** (species match + phased roadmap). Use hardware to make
that plan defensible for subsidies and buyers. Do not pretend a solo project is
a global 30-year financial + carbon engine.

## What works today

| Layer | Status |
|---|---|
| Farm profile (SoilGrids, OpenTopo, NDVI, GBIF) | ✅ API |
| Species DB + suitability scoring | ✅ `data/species_db.json` |
| RAG transition plan (Gemini + fallback) | ✅ `/farm/recommendations` |
| Web UI | ✅ `frontend/` served at `/` |
| ESP32 soil node prototype | ✅ `hardware/esp32/` |
| Sensor ingest stub | ✅ `/sensors/ingest` |

## Realistic scope (keep it narrow)

**In scope for the next 3–6 months**

1. One pilot region (e.g. Spain or Ontario)
2. ~species DB you already extracted + scoring filter
3. ESP32 moisture/temp node for compliance curves
4. Farmer-facing plan: layout + priority species + year phases
5. Manual subsidy notes (human + checklist), not auto-filed applications

**Out of scope until you have agronomist partners + funding**

- Global multi-objective “farm redesign engine”
- Bank-grade 30-year NPV / carbon credit issuance
- On-device local LLM in the field (Pi can come later for farm-office Q&A)

## Stack

- **FastAPI** — async REST API
- **SoilGrids / OpenTopography / Earth Engine / GBIF** — site characterisation
- **Species match** — rules over AgroForestree-derived JSON
- **Gemini** — plan prose over retrieved agroforestry chunks (+ deterministic fallback)
- **ESP32** — offline-first soil moisture + temperature node

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
cp .env.example .env
# Set OPENTOPO_API_KEY and GEMINI_API_KEY in .env

# Optional NDVI
earthengine authenticate

# API
uvicorn app.main:app --reload

# UI (separate terminal)
cd frontend
npm install
npm run dev
```

- UI (dev): http://127.0.0.1:5173/
- UI (built, served by API): `cd frontend && npm run build` then http://localhost:8000/
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### Example — full recommendation

```bash
curl "http://localhost:8000/api/v1/farm/recommendations?lat=37.9&lon=-4.7&radius_km=5&country=Spain&top_n=10"
```

Without `GEMINI_API_KEY` the plan still returns (deterministic fallback).
With a key, Gemini writes richer JSON using retrieved knowledge chunks.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET/POST | `/api/v1/farm/profile` | Soil + topo + NDVI + GBIF |
| POST | `/api/v1/farm/match` | Profile + ranked species |
| GET | `/api/v1/farm/recommendations` | Profile + match + RAG plan |
| GET | `/api/v1/species/search` | Direct DB search |
| POST | `/api/v1/sensors/ingest` | ESP32 batch upload |
| GET | `/api/v1/sensors/{id}/latest` | Recent node samples |

## Project layout

```
sylva/
├── app/
│   ├── main.py
│   ├── routers/          # farm, match, recommendations, sensors
│   ├── services/         # soil, topo, ndvi, gbif, species_match, rag
│   └── models/
├── frontend/             # React (Vite) UI
│   ├── src/App.jsx
│   └── dist/             # production build (npm run build)
├── hardware/esp32/       # soil node firmware + BOM map
├── data/species_db.json
├── scripts/ingest_aft_pdfs.py
└── requirements.txt
```

## ESP32 prototype

See [`hardware/esp32/README.md`](hardware/esp32/README.md) for BOM, wiring,
payload schema, and why ESP32 is the field unit (Pi LLM is optional later).

## Roadmap

- [x] Species agronomic DB extraction
- [x] Suitability filter + recommendations API
- [x] RAG plan with Gemini + offline fallback
- [x] ESP32 soil-node sketch + ingest stub
- [ ] Weatherproof pilot BOM + solar
- [ ] One-region subsidy checklist (human-in-the-loop)
- [ ] Persist sensor time-series (Postgres/Timescale)
