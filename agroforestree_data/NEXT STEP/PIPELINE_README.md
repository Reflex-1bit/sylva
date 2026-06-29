# Sylva Species Matching Pipeline

## Architecture

```
species_index.json          ←  AFT species list with PDF URLs
       │
       ▼
scripts/ingest_aft_pdfs.py  ←  Downloads PDFs, extracts text, uses GPT-4o-mini
       │                        to parse each into a structured JSON profile
       ▼
data/species_db.json         ←  Complete species database (one JSON object per tree)
       │
       ▼
app/services/species_match_service.py   ←  Hard filter + weighted scoring engine
       │
       ▼
app/routers/match.py         ←  FastAPI endpoints that call farm profiling + matching
       │
       ▼
POST /api/v1/farm/match      ←  Single call: GPS → farm profile + ranked species list
GET  /api/v1/species/search  ←  Direct DB query (no farm profile needed)
```

---

## Step 1 — Build the species database

```bash
# Install ingestion deps (one-time)
pip install pdfplumber openai httpx tqdm

# Set your OpenAI key
export OPENAI_API_KEY=sk-...

# Run ingestion (processes 10 species at a time, crash-safe/resumable)
python scripts/ingest_aft_pdfs.py \
    --species-index data/species_index.json \
    --pdf-cache    data/pdfs/ \
    --output       data/species_db.json \
    --batch-size   20

# Resume from where you left off
python scripts/ingest_aft_pdfs.py --start-from 20 --batch-size 20
# ...continue until all species are processed
```

**Cost estimate**: ~$0.002/species at gpt-4o-mini → ~$1 for 500 species.

---

## Step 2 — Connect to Sylva

1. Copy these files into your Sylva repo:
   - `scripts/ingest_aft_pdfs.py`
   - `app/services/species_match_service.py`
   - `app/routers/match.py`

2. Update `app/main.py`:
   ```python
   from app.routers import farm, match
   app.include_router(match.router, prefix="/api/v1", tags=["match"])
   ```

3. Put `species_db.json` in the project root `data/` directory.

4. Start the server: `uvicorn app.main:app --reload`

---

## Step 3 — Test it

```bash
# Combined farm profile + species matching
curl -X POST http://localhost:8000/api/v1/farm/match \
  -H "Content-Type: application/json" \
  -d '{
    "lat": -1.286, "lon": 36.817, "radius_km": 5,
    "country": "Kenya",
    "requested_uses": ["food", "timber", "nitrogen_fixing"],
    "top_n": 10
  }'

# Direct species search (no GPS needed)
curl "http://localhost:8000/api/v1/species/search?soil_ph=6.2&ndvi_health=0.3&uses=nitrogen_fixing,food&top_n=5"

# Reload DB after re-running ingestion
curl -X POST http://localhost:8000/api/v1/species/reload
```

---

## Scoring Algorithm

| Stage | Method | Points |
|---|---|---|
| Hard filter | pH compatibility | Pass/fail |
| Hard filter | Rainfall compatibility | Pass/fail |
| Soft score | Soil texture match | 0–15 |
| Soft score | Drought tolerance vs NDVI health | 0–20 |
| Soft score | Use-case alignment | 0–25 |
| Soft score | N-fixation / soil improvement | 0–15 |
| Soft score | Growth rate | 0–10 |
| Soft score | Degradation bonus (low NDVI) | 0–15 |
| **Total** | | **0–100** |

---

## Next steps to add

- [ ] Rainfall data from CHIRPS API (auto-fetch per GPS)
- [ ] Hardiness zone lookup from coordinates
- [ ] Companion crop compatibility matrix
- [ ] Carbon credit eligibility filter
- [ ] LLM narrative summary: "Why these 3 trees are best for your farm"
