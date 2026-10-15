# Sylva

**Agroforestry decision-support** for farms transitioning toward regenerative /
tree-integrated systems — with verifiable soil data from a low-cost field node.

Lead with the **plan** (species match + phased roadmap). Use hardware to make
that plan defensible for subsidies and buyers. Do not pretend a solo project is
a global 30-year financial + carbon engine.

## What's new (2026-10-15)

- **Sylva-wild at `/wild` (new).** A marine-blue copy of the Sylva page for companies. It takes three steps:
  choose **fix a problem** or **build something new**, pick your industry, and describe the problem in a sentence
  or two. Sylva then searches all 99,309 open catalogue records and returns nature-inspired solutions. Each
  solution cites the actual studies and gives donation links to groups that protect the habitat behind them.
  With a Gemini key, the question is rewritten into search phrases and the results are grouped into cited
  solutions. Without a key, the page shows the closest studies. See [Sylva-wild](#sylva-wild).
- **Nature page at `/nature`, redesigned.** It keeps only the **Library** (100 records) and the **Industry
  map** (507 records). The Ask tab and the stats/export block are gone. Instead, two counters pop up and count
  to the live totals. The page has new styling: drifting background light, a pill tab switch, and cards
  that lift on hover. Motion is reduced for users who ask for it.
- **The `/catalogue` page was removed.** The 99,309-record catalogue is still built and kept, now as the
  search corpus behind Sylva-wild (see [Open nature catalogue](#open-nature-catalogue)).
- **Safer on small hosts.** The API now starts without the Sylva-wild search libraries (numpy/scipy). Where the
  index is not installed, `/wild` reports this instead of the whole API failing. Gemini keys of both forms
  (`AIza…` and `AQ.…`) are redacted from logs.

## What works today

| Layer | Status |
|---|---|
| Farm profile (SoilGrids, OpenTopo, NDVI, GBIF) | ✅ API |
| Species DB + suitability scoring | ✅ `data/species_db.json` |
| RAG transition plan (Gemini + fallback) | ✅ `/farm/recommendations` |
| Web UI | ✅ `frontend/` served at `/` |
| ESP32 soil node prototype | ✅ `hardware/esp32/` |
| Sensor ingest stub | ✅ `/sensors/ingest` |
| Nature arm: open nature library + industry R&D map, search and RAG | ✅ `/api/v1/nature/*`; `/nature` page shows the library and map (the ask endpoint is API-only) |
| Open nature catalogue (99,309 records, sector-sorted) | ✅ `data/nature/catalogue/` (data only; the `/catalogue` page was removed) |
| Sylva-wild: onboarding + cited nature solutions over the catalogue | ✅ `/wild`, `/api/v1/wild/*` (needs the local search index; see below) |

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

The live Vercel project builds from the GitHub repo it is connected to. Check that this is
`ashm-023/sylva` (Vercel → project → Settings → Git) before expecting a merge into `main` to deploy.
On Vercel, `/wild` loads but cannot answer questions: the search index (about 75 MB) and its
libraries (`requirements-wild.txt`) do not fit the slim function, so `/wild/ask` returns 503.
Serving Sylva-wild live needs a host with room for the index, such as Render with Docker.

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

## Open nature catalogue

A free, sector-sorted catalogue of 99,309 records about learning from nature (bio-inspired design and nature-based solutions): scholarly papers, EU research projects and adaptation case studies. Each record is filed under one industry sector, with a design area and the nature functions it touches. Records that name an organism or habitat link to groups that protect it.

- **Where it is used:** the catalogue has no page of its own any more (the `/catalogue` page was removed on 2026-10-15). It is the search corpus behind [Sylva-wild](#sylva-wild). The publish step still writes gzipped JSON chunks to `frontend/public/catalogue/`; that folder is gitignored and not served.
- **How it is sorted:** by rules only. No language model and no embeddings are used, so the same inputs give the same output. Precision was checked by independent AI agents on blind samples of 200 records: strict 62.8%, lenient 74.9%, relevance 78.7%. The owner skim is still pending. Sectors under 70% strict precision are flagged in the manifest.
- **Donation links:** each link goes to the group's own donation page and is matched by rules. Sylva does not handle money, and no partnership is implied.
- **Licence and attribution:** the compilation is CC BY 4.0 by Sylva. Every record keeps its own source licence, and a summary is stored only when its source is CC BY or CC0. The summaries are the authors' abstracts, under each record's `summary_licence`; they may be shortened and have contact details removed, and OpenAlex's own metadata is CC0. Attribution line: `Sylva - Open Nature Catalogue, CC BY 4.0. Sources: OpenAlex (CC0); CORDIS (© European Union, CC BY 4.0); Climate-ADAPT (© EEA, CC BY 4.0); GBIF Backbone Taxonomy (CC BY 4.0). Summaries are the authors' abstracts, retrieved via OpenAlex or the source named on the record, under each record's summary_licence; they may be shortened and have contact details removed. OpenAlex metadata itself is CC0.`. Keep it with any copy you make.
- **Rebuild** (from the repository root; the raw harvests under `data/nature/catalogue/raw/` are not committed, and GBIF answers come from a local cache, `scripts/nature/catalogue/.cache/gbif.json`, which is gitignored: rebuilding without it lowers organism coverage):

```bash
# Re-derive the raw records from the cached harvests (offline; applies licence mapping and scrubbing)
python -m scripts.nature.catalogue.harvest_openalex normalise
python -m scripts.nature.catalogue.harvest_cordis normalise
python -m scripts.nature.catalogue.harvest_climate_adapt normalise
python -m scripts.nature.catalogue.build merge --offline
python -m scripts.nature.catalogue.build sort
python -m scripts.nature.catalogue.build groups
python -m scripts.nature.catalogue.build publish
python scripts/nature/catalogue/validate.py --build data/nature/catalogue/build
```

  Publishing again gives byte-identical files. Method, counts and limits are in [`data/nature/catalogue/README.md`](data/nature/catalogue/README.md).
- **Known gaps:** the OpenAlex nature-based-solution keywords are not fully harvested (155 of 288 keyword jobs done, 133 pending); PatentsView patents are deferred until a USPTO API key is available, so the catalogue holds no patents yet.

## Sylva-wild

A marine-blue page at `/wild` for companies: pick **fix a problem** or **build something new**,
pick an industry (the 15 catalogue sectors, or "Not sure"), describe it in a sentence or two,
and get nature-inspired solutions that cite the actual studies, with donation links to groups
that protect the habitat behind each study. A "custom research with wildlife reserves" offer
follows the results (marked coming soon; no form yet).

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/wild/meta` | Industry list, index status, record count, privacy notice |
| POST | `/api/v1/wild/ask` | `{intent: fix\|build, sector: id\|null, problem: str}` in, solutions + cited records out |

- **Search** runs over all 99,309 catalogue records with a local index and no key
  (`data/nature/wild/README.md`). Build it once: `pip install -r requirements-wild.txt` then
  `python -m scripts.nature.wild.build_index`. Until it is built, `/ask` answers 503.
- **With `GEMINI_API_KEY`** the problem is rewritten into up to three short search phrases and the
  top 12 records are grouped into solutions citing `R1`..`R12`. A guard drops any ref the model was
  not given and any URL it writes; study links and donation links come from the records only.
- **Without a key** (or if the model fails) the page shows the closest studies, search only.
- **Free-key protection:** at most two model calls per question, answers cached for an hour,
  10 model answers per visitor per 10 minutes (then search only).
- **Privacy:** the page tells users not to include confidential details; the text is sent to
  Gemini when a key is set and is not stored by Sylva.

Run it locally (the catalogue build in `data/nature/catalogue/build/catalogue.json` must exist; see
[Open nature catalogue](#open-nature-catalogue)):

```bash
pip install -r requirements.txt -r requirements-wild.txt
python -m scripts.nature.wild.build_index      # about 2 minutes, writes data/nature/wild/index/
echo GEMINI_API_KEY=your-key >> .env           # optional: AI-written solutions
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app                           # then open http://localhost:8000/wild
```

The index loads in the background when the server starts (about 30 seconds on a laptop); until then
`/wild/ask` answers 503 "loading".

## Project layout

```
sylva/
├── app/
│   ├── main.py
│   ├── routers/          # farm, match, recommendations, sensors, nature, wild
│   ├── services/         # soil, topo, ndvi, gbif, species_match, rag
│   └── models/
├── frontend/             # React (Vite) UI
│   ├── src/App.jsx       # farm plan (/)
│   ├── src/Nature.jsx    # nature library + industry map (/nature)
│   ├── src/Wild.jsx      # Sylva-wild onboarding + results (/wild)
│   ├── src/Hardware.jsx  # ESP32 soil node walkthrough (/hardware)
│   └── dist/             # production build (npm run build)
├── hardware/esp32/       # soil node firmware + BOM map
├── data/species_db.json
├── data/nature/          # open nature library + industry R&D map (CC BY 4.0)
├── app/services/nature/  # store, text, bm25, embeddings, search, matcher, links, rag
├── app/services/wild/    # Sylva-wild: index (BM25 + int8 vectors), store, rag, limits
├── data/nature/catalogue/ # open catalogue: sectors, groups, build manifest (CC BY 4.0)
├── scripts/nature/       # validate, verify sources, harvest, index, extract, review
├── scripts/nature/catalogue/ # catalogue harvest, sort, groups, publish, spot-check
├── scripts/nature/wild/  # build_index, query
├── scripts/ingest_aft_pdfs.py
├── requirements.txt
└── requirements-wild.txt # extra packages for the Sylva-wild index (scipy, fastembed)
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
- [x] Open nature catalogue: 99,309 sector-sorted records with habitat donation links (data kept; page removed 2026-10-15)
- [x] Sylva-wild: `/wild` onboarding, local search over the whole catalogue, cited Gemini answers, free-key limits
- [x] `/nature` redesign: library and map only, pop-up record counters
- [ ] Sylva-wild relevance eval (32 test problems: hit@5, MRR, nDCG)
- [ ] Sylva-wild hosting with the index (Render/Docker) and a lead form for custom reserve research
- [ ] Weatherproof pilot BOM + solar
- [ ] One-region subsidy checklist (human-in-the-loop)
- [ ] Persist sensor time-series (Postgres/Timescale)
