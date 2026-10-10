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
| Nature arm: open nature library + industry R&D map, search and RAG | ✅ `/api/v1/nature/*`, `/nature` (v0) |

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

## Deploy the website (public HTTPS)

- **Vercel (UI + API, secrets stay server-side):** see **[DEPLOY_VERCEL.md](DEPLOY_VERCEL.md)**
- **Render (Docker):** see **[DEPLOY.md](DEPLOY.md)** —  
  **https://render.com/deploy?repo=https://github.com/ashm-023/sylva**

On either host, set `GEMINI_API_KEY` / `OPENTOPO_API_KEY` as **server** env vars only.  
Never use `VITE_` for secrets — those are embedded in the public JavaScript bundle.

## Quickstart (local)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
cp .env.example .env
# Set OPENTOPO_API_KEY and GEMINI_API_KEY in .env

# API
uvicorn app.main:app --reload

# UI (separate terminal)
cd frontend
npm install
npm run dev
```

- UI (dev): http://127.0.0.1:5173/
- UI (production build): `cd frontend && npm run build` then http://localhost:8000/
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

### Nature arm endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/nature/meta` | Taxonomy, licence and attribution |
| GET | `/api/v1/nature/stats` | Coverage statistics (served records) |
| GET | `/api/v1/nature/library` | Search or filter the nature library (`q`, `area`, `function`, `sector`, `kind`, `status`) |
| GET | `/api/v1/nature/library/{id}` | One library record |
| GET | `/api/v1/nature/map` | Search or filter the industry R&D map |
| GET | `/api/v1/nature/map/{id}` | One map record |
| GET | `/api/v1/nature/sectors` | Sectors |
| GET | `/api/v1/nature/sectors/{id}/gaps` | Sector gaps (classified papers only, unclassified count shown) |
| POST | `/api/v1/nature/ask` | Challenge in, ranked records and a cited answer out |
| GET | `/api/v1/nature/export/{db}?format=json` or `csv` | Open export; `db` is `library` (served records only) or `industry_map` (alias `map`) |

```bash
curl -X POST http://localhost:8000/api/v1/nature/ask \
  -H "Content-Type: application/json" \
  -d '{"challenge":"surface that sheds dirt without detergent"}'
```

Without `GEMINI_API_KEY` (or its alias `GOOGLE_API_KEY`), `ask` uses BM25 plus function
recall and a deterministic answer. To switch on embeddings and the model-written answer,
set the key and run `python scripts/nature/build_index.py`. The datasheet, licence
(CC BY 4.0) and known gaps are in [`data/nature/README.md`](data/nature/README.md).

The nature data is CC BY 4.0. Attribute it as
**Sylva — nature library and industry R&D map, CC BY 4.0**. JSON exports carry the
licence and this attribution in the file. CSV exports are a plain table that carries
them only in the `Link` and `X-Attribution` response headers and the file name, so if you
reuse a CSV export you must keep the attribution with it.

## Project layout

```
sylva/
├── app/
│   ├── main.py
│   ├── routers/          # farm, match, recommendations, sensors, nature
│   ├── services/         # soil, topo, ndvi, gbif, species_match, rag
│   └── models/
├── frontend/             # React (Vite) UI
│   ├── src/App.jsx
│   └── dist/             # production build (npm run build)
├── hardware/esp32/       # soil node firmware + BOM map
├── data/species_db.json
├── data/nature/          # open nature library + industry R&D map (CC BY 4.0)
├── app/services/nature/  # store, text, bm25, embeddings, search, matcher, links, rag
├── scripts/nature/       # validate, verify sources, harvest, index, extract, review
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
- [x] Nature arm v0: 109-record nature library (extended on 2026-10-11), 507-record Iberian industry map, search + RAG, `/nature` page
- [ ] Nature arm: expert validation of library records, patents and grants in the map, embeddings live (needs `GEMINI_API_KEY`)
- [ ] Weatherproof pilot BOM + solar
- [ ] One-region subsidy checklist (human-in-the-loop)
- [ ] Persist sensor time-series (Postgres/Timescale)
