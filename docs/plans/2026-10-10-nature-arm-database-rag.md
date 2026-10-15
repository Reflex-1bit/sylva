# Nature arm: open databases + RAG — implementation plan

Written 2026-10-10. Governing spec: `connected-systems/07-building-the-nature-arm.md` (§7.3, steps 4, 5, 10) and `connected-systems/02-biomimicry-blueprint.md` (§2.2–2.7). This plan builds the software side of steps 4 and 5: the **industry R&D map**, the **nature library**, and a **RAG system** that answers an industry challenge from the library, linked to the map.

Each phase is self-contained: an implementer with no other context should be able to execute it from this file plus the files it cites.

---

## Phase 0 — Documentation discovery (done; consolidated findings)

### 0.1 Existing code patterns to copy (verified by reading the code)

| Pattern | Where | Use it for |
|---|---|---|
| Router: bare `router = APIRouter()`, prefix + tags set in `main.py` | `app/main.py:98-101`, `app/routers/match.py:61-118` (`GET /species/search`) | `app/routers/nature.py` |
| Pydantic models: `from __future__ import annotations`, `BaseModel`, `Field`, `Optional` | `app/models/match.py`, `app/models/farm.py` | `app/models/nature.py` |
| Lazy cached JSON DB loader, `FileNotFoundError` → 503 | `app/services/species_match_service.py:23-46`, `app/routers/recommendations.py:77-79` | `NatureStore` |
| Gemini REST `generateContent` via httpx, model fallback list, `params={"key":...}`, `responseMimeType: application/json`, `_parse_json` fence strip, deterministic fallback when no key / on error | `app/services/rag_service.py:27-32, 204-316, 337-385` | `app/services/nature/rag.py` |
| Prompt no-invention clause: "Do not invent species that are not in the matched list." | `app/services/rag_service.py:171-194` | Same rule for record ids |
| Literature → JSON records pipeline (concurrency semaphore, backoff on 429, incremental save) | `scripts/ingest_aft_pdfs.py:73-127` | `scripts/nature/extract_mechanisms.py` |
| Tests: pytest, `tmp_path` fixture writing a small JSON DB, service constructed with `db_path=` | `tests (2)/test_species_match.py:6-54` | All nature tests |
| SPA route registered for Docker/Render | `app/main.py:147-171` (`/hardware`) | Add `/nature` |
| Frontend API wrapper | `frontend/src/api.js` (`API_BASE`, `fetchWithTimeout`) | `fetchNature*` helpers |
| Frontend route | `frontend/src/main.jsx` (react-router v7, lazy `Hardware`) | lazy `Nature` page |

Environment facts: Python 3.14 locally, 3.12 in Docker (avoid 3.13+-only syntax). numpy 2.x available and already in slim `requirements.txt`. pytest-asyncio is in STRICT mode (`@pytest.mark.asyncio` needed). Run tests with `python -m pytest -q` from repo root (5 pass at start). No conftest, no pytest.ini.

Deployment facts: Vercel bundles only files listed in `vercel.json` → `functions."api/index.py".includeFiles` (currently `{data/species_db.json,app/**/*.py}`); every new data file must be added there. `.vercelignore` excludes `*.npz`, `*.pkl`, `*.h5` — store vectors as `.npy`. `excludeFiles` drops all `*.md`. Slim deps budget ~225 MB: **no new runtime dependencies**. Docker copies all of `data/`.

### 0.2 Allowed external APIs (verified from official docs, 2026-10)

**Gemini embeddings** (https://ai.google.dev/gemini-api/docs/embeddings, https://ai.google.dev/api/embeddings)
- Model: `gemini-embedding-2` (current, stable). `outputDimensionality: 768`.
- `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents`, header `x-goog-api-key: <KEY>`.
- Body: `{"requests":[{"model":"models/gemini-embedding-2","content":{"parts":[{"text":"..."}]},"embedContentConfig":{"outputDimensionality":768}}]}`; response `{"embeddings":[{"values":[...]}]}` in request order.
- `gemini-embedding-2` does **not** take `taskType`; format text instead: documents `title: {title} | text: {content}`, queries `task: search result | query: {content}`.
- Chunk batches at ≤ 100 requests. Always L2-normalise vectors yourself.
- If the nested `embedContentConfig` is rejected (HTTP 400), retry once with top-level `outputDimensionality`.

**Gemini generation**: reuse `rag_service._api_key`, `rag_service._call_gemini`, `rag_service._parse_json` (URL, payload, model fallback list).

**OpenAlex** (https://help.openalex.org) — data CC0.
- `GET https://api.openalex.org/works?filter=title_and_abstract.search:<q>,authorships.institutions.country_code:ES|PT,publication_year:2015-2026&per_page=100&cursor=*&select=id,doi,title,publication_year,authorships,topics,open_access,primary_location,cited_by_count,type`
- Optional `api_key` query param from env `OPENALEX_API_KEY` (free key; keyless budget ≈100 searches/day). `mailto` is ignored since Feb 2026.
- Boolean `AND`/`OR`/`NOT` uppercase; URLs over ~4 KB return 400.
- `authorships[].institutions[]` has `display_name`, `ror`, `country_code`, `type` (`company`, `education`, `facility`, `government`, `nonprofit`, `healthcare`, `archive`, `other`).
- Do **not** store `abstract_inverted_index` (abstracts are publisher copyright).

**Crossref** — `GET https://api.crossref.org/works/{doi}` with optional `mailto=`; use `message.title[0]`, `message.issued`, `message.license[]`. Polite pool 10 req/s, concurrency 3. Do not store abstracts.

**GBIF** — `GET https://api.gbif.org/v1/species/match?name=<scientific name>`; fields `usageKey`, `scientificName`, `canonicalName`, `rank`, `status`, `confidence`, `matchType`, `kingdom`, `acceptedUsageKey`. Accept only `matchType ∈ {EXACT, FUZZY}` and `confidence ≥ 90`; `HIGHERRANK`/`NONE` → needs review. Backbone licence CC BY 4.0.

**Horizon Europe TRL** — verbatim list, Horizon Europe WP 2026-2027 General Annexes p.15 (https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027/horizon/wp-call/2026-2027/wp-15-general-annexes_horizon-2026-2027_en.pdf):
1 Basic principles observed · 2 Technology concept formulated · 3 Experimental proof of concept · 4 Technology validated in a lab · 5 Technology validated in a relevant environment (industrially relevant environment in the case of key enabling technologies) · 6 Technology demonstrated in a relevant environment (industrially relevant environment in the case of key enabling technologies) · 7 System prototype demonstration in an operational environment · 8 System complete and qualified · 9 Actual system proven in an operational environment (competitive manufacturing in the case of key enabling technologies, or in space).

**Sector codes** — CNAE-2025 (RD 10/2025, in force 2025-01-16) = NACE Rev.2.1 to the 3rd level. Key the map on 2-digit NACE Rev.2.1 / CNAE-2025 divisions.

### 0.3 Licensing rules for what may enter the open (CC BY 4.0) databases

| Allowed | Link / reference only, never copy |
|---|---|
| Our own summaries written from primary literature | AskNature text and its taxonomy (all-rights-reserved / CC BY-NC) |
| DOI, title, year, venue, authors' institutions (facts; OpenAlex/Crossref CC0) | Publisher abstracts |
| GBIF usage keys and names (CC BY 4.0, attribute) | EPO OPS / Lens raw data |
| NACE Rev.2.1 / CNAE-2025 codes, Horizon Europe TRL definitions | Sylva's `data/species_db.json` (Agroforestree, all rights reserved — ch.7 §7.3) |
| Verbatim supporting sentence **only** from papers with a CC BY/CC0 licence | Client problems or findings |

### 0.4 Anti-patterns (do NOT do)

- Do not use `text-embedding-004` / `embedding-001` (shut down) or `taskType` with `gemini-embedding-2`.
- Do not add dependencies to `requirements.txt` (no rank_bm25, scikit-learn, faiss, chroma, sqlite-vss, langchain). Hand-roll BM25 with numpy.
- Do not save `.npz`/`.pkl` (Vercel ignores them).
- Do not invent DOIs, GBIF keys, companies or measured values. A null is more honest than a guess (ch.2 §2.3). Every seed DOI is checked by `verify_sources.py`.
- Do not copy AskNature sentences, abstracts or taxonomy labels. Our function vocabulary is our own wording.
- Do not let the LLM rank, score or set provenance; ranking is deterministic and published. The LLM only phrases, and may cite only retrieved record ids.
- Do not import or touch `data/species_db.json` from any nature module.
- Do not make network calls in tests (monkeypatch the HTTP layer).

---

## Shared design (all phases refer to this)

### Files

```
data/nature/
  taxonomy.json          # areas, functions, sectors, TRL, evidence grades, statuses (CC BY 4.0, our wording)
  library.json           # nature library records (array)
  industry_map.json      # industry R&D map records (array)
  library_staging.json   # extraction pipeline output awaiting review (not served)
  review_log.jsonl       # reviewer actions with timestamps
  index/                 # optional embeddings: library.npy, industry_map.npy, index_meta.json
  LICENSE.txt            # CC BY 4.0 notice + attribution rules
  README.md              # datasheet: schema, sources, coverage, how to contribute
app/models/nature.py
app/services/nature/__init__.py
app/services/nature/store.py        # load + validate + serving gate + stats
app/services/nature/text.py         # tokenizer (EN+ES stopwords, accent fold)
app/services/nature/bm25.py         # numpy BM25
app/services/nature/embeddings.py   # Gemini embedding REST client + index load
app/services/nature/search.py       # hybrid search (BM25 + embeddings, RRF) + filters
app/services/nature/matcher.py      # function parsing + deterministic scoring (ch.2 §2.4)
app/services/nature/links.py        # library <-> map links, sector gaps
app/services/nature/rag.py          # ask: retrieve -> score -> Gemini phrase -> citation guard -> fallback
app/routers/nature.py
scripts/nature/validate_db.py
scripts/nature/verify_sources.py
scripts/nature/harvest_openalex.py
scripts/nature/build_index.py
scripts/nature/extract_mechanisms.py
scripts/nature/review.py
tests/nature/ (with __init__.py)
frontend/src/Nature.jsx, frontend/src/Nature.css
```

### Taxonomy (`data/nature/taxonomy.json`)

Top-level keys: `version`, `licence`, `areas`, `functions`, `function_groups`, `sectors`, `trl`, `evidence_grades`, `provenance_statuses`.

- `areas`: the seven from ch.7 §7.2 — ids `form, process, materials, energy, circularity, systems, place`, each `{id, label, question}` (question text copied from the ch.7 table).
- `function_groups` + `functions`: Sylva's own vocabulary, ~40 functions in ~12 groups, ids kebab-case, each function `{id, group, label, keywords_en[], keywords_es[], asknature_group?}`. `asknature_group` is an optional crosswalk holding only the short AskNature group name. Groups (our wording): `manage-water` (shed water, capture water, filter water, store water, move water), `manage-heat` (cool passively, insulate, recover heat, regulate temperature), `manage-air-and-gases` (ventilate, capture gases, filter air), `resist-and-support-loads` (stiffen, lighten structure, absorb impact, resist fracture, resist fatigue), `protect-surfaces` (self-clean, prevent fouling, resist microbes, resist wear, reduce drag, resist corrosion), `attach-and-join` (adhere reversibly, adhere underwater, join without fasteners), `make-and-assemble` (make at ambient conditions, self-assemble, colour without pigment, grow material), `break-down-and-recycle` (biodegrade, design for disassembly, reuse waste as input, repair), `sense-and-respond` (sense environment, respond adaptively), `move-efficiently` (reduce friction, move fluids efficiently, improve aerodynamics), `sustain-ecosystems` (build soil, support pollinators, provide habitat, regulate water cycle), `optimise-systems` (distribute through networks, share resources symbiotically, source locally).
- `sectors`: 10, each `{id, label_en, label_es, nace_rev21_divisions[], keywords_en[], keywords_es[]}`: `steel-aluminium` ["24"], `construction-materials` ["23","41","42","43"], `packaging` ["17","22"], `cosmetics` ["20"], `textiles` ["13","14"], `automotive` ["29"], `energy` ["35"], `agrifood` ["01","10","11"], `water-utilities` ["36","37"], `chemicals` ["20"].
- `trl`: 1–9 with the verbatim Horizon Europe wording above plus source URL.
- `evidence_grades`: `strong` (≥2 sources with a DOI or URL and ≥1 measured value), `moderate` (≥2 sources, or 1 source with a measured value), `weak` (1 source, no measured value), `contested` (provenance `disputed` or `popular_claim_note` set). Computed in code, never stored on records.
- `provenance_statuses`: `ai_extracted`, `expert_validated`, `disputed` with one-line meanings.

### Nature library record (pydantic, `extra="forbid"` = `additionalProperties: false`)

```
id: str                     # "lib-0001"
kind: "mechanism" | "material" | "process" | "practice"
title: str
summary: str                # our own words, 1–4 sentences, no copied text
areas: list[AreaId]         # >=1
functions: list[FunctionId] # >=1, must exist in taxonomy
sector_tags: list[SectorId]
organism: Organism | None   # {scientific_name, common_names[], kingdom?, gbif_usage_key?, gbif_match_type?}
trait: str | None; structure: str | None; mechanism: str | None   # mechanism required when kind == "mechanism"
trait_type: "morphological" | "biochemical" | "genetic" | "behavioural" | "ecological" | "not_applicable"
legal_review: "not_required" | "pending" | "cleared"    # biochemical/genetic must not be "not_required"
knowledge_source: "peer_reviewed" | "grey_literature" | "traditional" | "field_observation"
consent: "not_applicable" | "pending" | "granted"        # traditional must not be "not_applicable"
performance: list[{metric, value: float | None, units: str | None, measured_in: "literature" | "reproduced" | "field"}]
evidence: list[Evidence]    # >=1
  Evidence = {citation: str, doi: str | None, url: str | None, year: int | None,
              open_access: bool = False, licence: str | None, supporting_sentence: str | None,
              page: str | None, verified: bool = False}
              # supporting_sentence allowed only if licence starts with "CC-BY" or "CC0"
known_products: list[str]
popular_claim_note: str | None          # e.g. Eastgate termite-mound myth
provenance: {status, extracted_by, extracted_on (date), validated_by?, validated_on?}  # expert_validated needs both
confidence: "low" | "medium" | "high"
caveat: str                             # required, non-empty
source_region: {region: str, reserve_id: str | None, note: str | None} | None
contributors: list[{name, role, place?}]
see_also: list[str]                     # URLs, e.g. AskNature pages (link only)
```

**Serving gate** (`NatureStore.is_servable`): served by API and exports only if not (`trait_type` in biochemical/genetic and `legal_review == "pending"`) and not (`knowledge_source == "traditional"` and `consent != "granted"`). Quarantined records stay in the repo file with their status visible but are never served or exported.

### Industry R&D map record

```
id: str                       # "map-0001"
type: "paper" | "patent" | "grant" | "project" | "company"
title: str
summary: str | None           # our words; None for auto-harvested items
sector: SectorId
nace_divisions: list[str]
problem_functions: list[FunctionId]   # the join key to the library
areas: list[AreaId]
nature_link: "biomimetic" | "bio_based" | "nature_based_solution" | "circular" | "other"
inspiration: {organism: str | None, note: str | None} | None
country: str                  # ISO-3166 alpha-2
region: str | None
organisations: list[{name, country: str | None, kind: "company"|"university"|"research_centre"|"public_body"|"other", ror: str | None}]
year: int | None
trl: int | None               # 1–9
identifiers: {doi?, openalex_id?, patent_number?, grant_id?, url?}
library_links: list[str]      # lib ids, set by reviewers
source: {name: str, licence: str, retrieved_on: date}
provenance: same as library
```

### Ranking (deterministic, published) — ch.2 §2.4 adapted

`score = evidence (0–30) + provenance (0–25) + fit (0–20) + manufacturability (0–15) + regional (0–10)`
- evidence: strong 30, moderate 20, weak 10, contested 0.
- provenance: expert_validated 25, ai_extracted 10, disputed 0.
- fit: 20 × (retrieval score normalised to [0,1] over the hit list) × (0.5 + 0.5 × function-overlap ratio; ratio = 1 when no functions parsed).
- manufacturability: 15 if `known_products` non-empty or any map record links it; else 0.
- regional: 10 if `source_region.reserve_id`, 5 if `source_region` set, else 0.
- When `strict_functions=true` and the challenge parses to ≥1 function, records with no overlap are removed.
Return a per-record `breakdown` dict like `SpeciesMatchScore.breakdown`.

---

## Phase 1 — Taxonomy, models, store, validator

**Implement**
1. `data/nature/taxonomy.json` per "Shared design".
2. `app/models/nature.py`: all models above with `model_config = {"extra": "forbid"}`; `Literal` types for enums; `model_validator(mode="after")` for: mechanism-kind field, legal_review/consent rules, expert_validated fields, supporting_sentence licence rule. Response/request models: `LibraryHit {record, score, breakdown, evidence_grade}`, `MapHit {record, score}`, `NatureStats`, `AskRequest {challenge: str (min 8, max 2000), sector: str | None, areas: list[str] = [], functions: list[str] = [], strict_functions: bool = False, top_k: int = 8 (1–20)}`, `AskResponse {challenge, parsed_functions, verdict, answer: dict, library_hits, map_hits, gaps, model, licence}`.
3. `app/services/nature/store.py`: `class NatureStore(data_dir: Path = DEFAULT_DIR)` where `DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "nature"`; lazy-load and validate `taxonomy.json`, `library.json`, `industry_map.json`; referential checks (ids unique, function/area/sector ids exist in taxonomy, `library_links` exist) raising `NatureDataError(ValueError)` listing all problems. Methods: `taxonomy()`, `library(servable_only=True)`, `industry_map()`, `get_library(id, servable_only=True)`, `get_map(id)`, `is_servable(rec)`, `evidence_grade(rec)`, `stats()` → `{version, licence, library_total, library_served, quarantined, by_status, by_area, by_kind, with_measured_values, validated_share, measured_share, map_total, map_by_sector, map_by_type, map_by_country}`, `reload()`. Module-level `get_store()` singleton (`functools.lru_cache`).
4. `scripts/nature/validate_db.py`: loads via `NatureStore`, prints stats (and `--markdown` table), exits non-zero on any error. Must run as `python scripts/nature/validate_db.py` from repo root (insert repo root on `sys.path`).
5. Create `data/nature/library.json` and `industry_map.json` as `[]`.

**Docs to copy**: `app/models/match.py` (style), `app/services/species_match_service.py:23-46` (lazy loader), `tests (2)/test_species_match.py:6-54` (fixture style).

**Verify**: `python -m pytest -q tests/nature` — tests for: extra field rejected; mechanism without `mechanism` rejected; biochemical + not_required rejected; supporting_sentence with closed licence rejected; expert_validated without validator rejected; serving gate hides pending-legal and traditional-no-consent records; unknown function id fails referential check; `evidence_grade` cases; `stats()` counts. `python scripts/nature/validate_db.py` exits 0.

**Guards**: no network; no import of `species_db.json`.

---

## Phase 2 — Nature library seed (v0) + source verification

**2a. `scripts/nature/verify_sources.py`** (code + mocked tests)
- For each library record: Crossref lookup of each `evidence.doi` → set `verified=True` when the DOI resolves and the normalised Crossref title shares ≥ 60% of its tokens with `citation`; fill `year`; set `open_access`/`licence` from Crossref `license[]` (only creativecommons.org `by` / `zero` URLs count; map to `CC-BY-4.0`, `CC0-1.0` etc.). GBIF match for `organism.scientific_name` → fill `gbif_usage_key`, `gbif_match_type`, `kingdom` when accepted per Phase 0.2 rule.
- Pure functions for the decisions (`title_matches`, `licence_from_crossref`, `accept_gbif`) so they test without network; HTTP via one injectable `fetch_json(url, params)` function.
- Writes the file back (`indent=2`, UTF-8, `ensure_ascii=False`) and prints a failure report; `--dry-run`; `--report path.json`. Sequential with small sleep, optional `CROSSREF_MAILTO` env.
- Tests: title-match accept/reject; licence mapping; GBIF HIGHERRANK not accepted; end-to-end on a tmp library with monkeypatched `fetch_json`.

**2b. Seed content** (~60 records, authored in batches; each batch passes `validate_db.py`)
- Coverage: all seven areas; each of the 10 sectors tagged by ≥3 records; kinds roughly 35 mechanisms, 10 materials, 8 processes, 7 practices.
- Must include (named in ch.2/ch.6/ch.7): lotus leaf self-cleaning (Barthlott & Neinhuis 1997, doi 10.1007/s004250050096); gecko adhesion (Autumn et al. 2000, Nature); cork from *Quercus suber* as material; dehesa silvopastoral system (practice, areas place/systems, `source_region.region` "Dehesa (Extremadura / Andalucía)"); holm oak *Quercus ilex*; termite-mound ventilation with `popular_claim_note` on Eastgate (Turner & Soar 2008) and status `disputed`; shark-skin denticles with note on swimsuits (Oeffner & Lauder 2012); kingfisher / Shinkansen nose as `disputed`, low confidence; Namib beetle fog capture; mussel adhesion (biochemical → `legal_review: pending`, quarantined — demonstrates the gate); spider silk (biochemical, pending); nacre toughness; trabecular bone lattices; humpback whale flipper tubercles; Morpho structural colour; mycelium composites; Kalundborg industrial symbiosis; constructed wetlands; green roofs; countercurrent heat exchange; natural-fibre packaging; plus others filling gaps.
- Every record: `provenance.status: "ai_extracted"` (except the disputed ones), `extracted_by: "claude-opus-5-5 (seed v0, from literature knowledge)"`, `extracted_on: "2026-10-10"`; `supporting_sentence: null`; `caveat` e.g. "Summarised from the cited literature; not reproduced in a lab; not design advice."; `performance.value` null unless the number is well established in the cited paper; only DOIs the author is confident of — if unsure, give `citation` (+ `url`) without DOI and lower `confidence`.

**2c. Run verification live** — `python scripts/nature/verify_sources.py`; fix or remove every DOI that fails; records whose evidence are all unverified get `confidence: "low"`.

**Verify**: validator passes; ≥ 55 records; ≥ 80% of DOIs `verified: true`; ≥ 2 quarantined; every area and sector covered.

**Guards**: no AskNature text; no abstracts; no invented numbers.

---

## Phase 3 — Industry R&D map v0 (OpenAlex harvest)

**Implement** `scripts/nature/harvest_openalex.py`
- For each sector: query OpenAlex works with `authorships.institutions.country_code:ES|PT`, `publication_year:2015-2026`, `title_and_abstract.search:` = `(biomimetic OR bioinspired OR "bio-inspired" OR biomimicry OR "nature-inspired" OR "bio-based") AND (<2–4 sector keywords joined by OR>)`; cursor paging; `--per-sector` cap (default 60); `--max-calls` budget (default 60); cache raw responses under `scripts/nature/.cache/` (gitignored).
- Convert each work → map record `type: "paper"`: title, year, doi, openalex_id, `organisations` from authorship institutions (OpenAlex `type`: company→company, education→university, facility→research_centre, government→public_body, else other), `country` = most frequent ES/PT institution country, `sector` = query sector, `problem_functions` + `areas` + `nature_link` + `inspiration.organism` by deterministic keyword rules over title and OpenAlex topic display names using taxonomy keywords (`provenance.extracted_by: "rules:harvest_openalex v0"`), `summary: null`, `source: {name: "OpenAlex", licence: "CC0", retrieved_on}`. A work found under several sectors keeps the sector with most keyword hits.
- Emit one `type: "company"` record per distinct OpenAlex institution with `type == "company"` and an ES or PT country, `sector` = its most frequent sector, `identifiers.url` = its OpenAlex or ROR URL, `problem_functions` = union over its papers.
- Pure converter functions (`work_to_record`, `classify`, `aggregate_companies`) tested offline.
- Run live; write `data/nature/industry_map.json`; validate.

**Verify**: validator passes; ≥ 8 sectors have ≥ 5 records; ≥ 1 company record; `abstract` never appears in `industry_map.json`.

**Guards**: `OPENALEX_API_KEY` from env only, never committed; never store abstracts.

---

## Phase 4 — Search: tokenizer, BM25, embeddings, hybrid

**Implement**
1. `text.py`: `normalise(s)` (lowercase, NFKD accent strip), `tokenize(s)` (regex `[a-z0-9]+`, drop EN+ES stopwords and tokens < 2 chars, light plural strip).
2. `bm25.py`: `class BM25(docs: list[list[str]], k1=1.5, b=0.75)` with `scores(query_tokens) -> np.ndarray`; numpy only.
3. `embeddings.py`: `async embed_texts(texts, *, kind: "document"|"query", api_key, titles=None, model=env NATURE_EMBED_MODEL or "gemini-embedding-2", dim=768, client=None) -> np.ndarray` (batches ≤100, task-prefix formatting per 0.2, header auth, L2-normalise, 400 → one retry with top-level `outputDimensionality`); `load_index(name, data_dir, expected_hash) -> (matrix, ids) | None` reading `index/{name}.npy` + `index/index_meta.json` (must match model, dim and content hash, else None).
4. `search.py`: `doc_text(record, taxonomy)` (title + summary + mechanism/structure/trait + organism names + function labels + area labels + sector labels); `class NatureSearch(store)` building BM25 per db lazily; `async search_library(query, *, areas, functions, sectors, kinds, statuses, k, api_key=None)` and `async search_map(query, *, sector, types, country, year_from, year_to, k, api_key=None)`: BM25 always; if api_key and a valid index → cosine; fuse with reciprocal-rank fusion (k=60); return `list[(record, score_normalised_0_1)]`.
5. `scripts/nature/build_index.py`: embeds both DBs and writes `.npy` + `index_meta.json` (model, dim, ids, sha256 of the `doc_text` list per db). Exits 0 with a message when no key.

**Verify**: tests — accent fold ("compresión" → "compresion"); BM25 ranks the obvious doc first; RRF order; stale index ignored; embeddings request JSON + normalisation (monkeypatched transport); search with no key works. Acceptance (ch.7 step 5 "returns at least five relevant records with sources"): test against the real `data/nature/library.json` that each of 5 challenges ("surface that sheds dirt without detergent", "reduce cooling energy in a building", "lighter structural component for cars", "packaging that biodegrades", "capture water from air") returns ≥ 5 records, the top 3 sharing ≥1 expected function.

**Guards**: no new dependency; no `.npz`; no network in tests.

---

## Phase 5 — Matcher, links/gaps, RAG

**Implement**
1. `matcher.py`: `parse_functions(text, taxonomy) -> list[str]` (EN+ES keyword hits on normalised text); `score_library(hits, parsed_functions, store, map_records) -> list[LibraryHit]` per Ranking.
2. `links.py`: `sectors_for_record(record, store)` → `{using: [...], candidate: [...]}` (using = sectors with a map record that links it or whose title mentions its organism canonical name / genus; candidate = sectors whose map `problem_functions` overlap the record's functions and that do not use it); `sector_gaps(sector_id, store, limit=10)` → records whose functions overlap the sector's map problem functions (weighted by count) and that the sector does not use, ranked by evidence grade then weighted overlap; each `{record_id, title, functions_overlap, weight, evidence_grade}`.
3. `rag.py`: `async ask(req, store, search) -> AskResponse`:
   - parse functions (+ `req.functions`); search library (k = 3 × top_k) and map (k = 10); score; keep top_k; gaps if `req.sector`.
   - Deterministic verdict: `promising` if top score ≥ 60 and its grade is strong/moderate; `weak` if any hit; else `no_strong_option`.
   - No key → fallback answer. Else prompt Gemini via `rag_service._call_gemini`. Prompt rules: answer only from the records given; cite record ids in square brackets; never add a mechanism, number or organism not in the records; say plainly when no record is a strong fit and conventional engineering may be better ("nature is the first place to look, not the only answer"); do not use "biomimetic" or "nature-positive"; separate "inspired by" from "better for nature"; JSON `{summary, options: [{record_id, why, caveat}], open_questions: [], next_steps: []}`.
   - Citation guard: drop `options[]` whose `record_id` was not retrieved; strip unknown `[lib-…]`/`[map-…]` ids from text; list them in `answer._guard.dropped_ids`.
   - Any LLM error → fallback, `model = "fallback (LLM error: …)"`, like `rag_service`.

**Verify**: tests — function parsing; score breakdown arithmetic; gaps on a fixture; citation guard drops an invented id (monkeypatch `_call_gemini`); fallback without key; verdict rules.

**Guards**: LLM never changes ranking or verdict; reuse `rag_service` Gemini helpers.

---

## Phase 6 — API router + wiring

**Implement** `app/routers/nature.py` (template `app/routers/match.py:61-118`), mounted in `app/main.py` as `app.include_router(nature.router, prefix="/api/v1", tags=["nature"])`:
- `GET /nature/meta` → licence (`CC BY 4.0`, attribution text, licence URL), version, taxonomy.
- `GET /nature/stats`
- `GET /nature/library` (q, area, function, sector, kind, status, limit 1–100 default 20) → `list[LibraryHit]`; without `q`, filtered records sorted by id.
- `GET /nature/library/{record_id}` → record + evidence_grade + `sectors_for_record`; 404 if missing or quarantined.
- `GET /nature/map` (q, sector, type, country, year_from, year_to, limit) → `list[MapHit]`
- `GET /nature/map/{record_id}`
- `GET /nature/sectors` → taxonomy sectors with map counts; `GET /nature/sectors/{sector_id}/gaps` (404 unknown sector)
- `POST /nature/ask` (AskRequest) with `asyncio.wait_for` 60 s → 504
- `GET /nature/export/{db}` (`db ∈ {library, industry_map}`, `format=json|csv`) → servable records only, header `X-License: CC-BY-4.0`, `Content-Disposition: attachment`; CSV flattens lists with `; ` and nested objects as JSON strings.
- 503 on `FileNotFoundError` / `NatureDataError`.
- `app/main.py`: `/nature` SPA route next to `/hardware`; `APP_VERSION = "0.3.0"`.
- `vercel.json` `includeFiles` → `{data/species_db.json,data/nature/*.json,data/nature/index/*,app/**/*.py}`.
- `.env.example`: `# OPENALEX_API_KEY=`, `# CROSSREF_MAILTO=`, `# NATURE_EMBED_MODEL=gemini-embedding-2`.

**Verify**: `fastapi.testclient.TestClient(app)` tests for every endpoint (404 on quarantined id, CSV header row, licence header, ask fallback without key via monkeypatched env). All tests pass.

---

## Phase 7 — Extraction pipeline + review CLI (ch.2 §2.2)

**Implement**
1. `scripts/nature/extract_mechanisms.py`: input `--dois file.txt`; for each DOI fetch OpenAlex work (`/works/doi:<doi>`); if OA with CC BY/CC0 licence and `--fetch-text`, fetch the OA URL text (HTML stripped; PDF only if `pdfplumber` importable) — otherwise use title + topics only and never quote. Call Gemini through `rag_service._call_gemini` with a prompt returning a LibraryRecord JSON (schema + taxonomy ids in the prompt); semaphore 2 + backoff copied from `ingest_aft_pdfs.py`; validate with pydantic (hallucination gate: invalid → logged and dropped); force `provenance.status = "ai_extracted"`; `supporting_sentence` kept only if it is a substring of the fetched text and the licence allows it, else null; id `stg-NNNN`; append to `library_staging.json`.
2. `scripts/nature/review.py`: `list`; `show <id>` (logs open time); `promote <stg-id> --by NAME` (moves to library with next `lib-` id); `validate <lib-id> --by NAME` (sets `expert_validated`, `validated_by`, `validated_on`); `dispute <lib-id> --by NAME --reason TEXT` (status `disputed`, reason appended to caveat); `timing` (median minutes from `show` to `validate`/`dispute` per record — the month-12 checkpoint "validating a record takes under an hour", ch.7 §7.7). Every action appends to `review_log.jsonl`. All file paths overridable with `--data-dir` for tests.

**Verify**: tests with monkeypatched Gemini/OpenAlex: invalid JSON dropped; sentence not in text → null; promote/validate/dispute mutate files and log; timing calc.

---

## Phase 8 — Frontend `/nature`

**Implement** `frontend/src/Nature.jsx` + `Nature.css`, lazy route in `main.jsx`, nav link in `App.jsx` topbar next to the `/hardware` link, API helpers in `api.js` (`fetchNatureStats`, `fetchNatureMeta`, `searchLibrary`, `askNature`, `fetchSectorGaps`, `searchMap`).
- Header: coverage stats (records, validated share, measured share, map records, licence badge "CC BY 4.0" + export links).
- "Ask nature" tab: challenge + optional sector + area chips → verdict pill, summary, option cards (title, organism, evidence grade, provenance badge, caveat, DOI links), open questions, next steps, map evidence, sector gaps.
- "Library" tab: filters (area, sector, kind, status) + cards.
- "Industry map" tab: sector selector → counts, records, gaps.
- Reuse `App.css` variables / visual language. No new npm dependencies.

**Verify**: `cd frontend && npm run build` succeeds.

---

## Phase 9 — Docs + final verification

**Implement**
- `data/nature/README.md` (datasheet): both databases, schema tables, taxonomy summary, licence + attribution, source policy (0.3), serving gate, provenance meaning, coverage stats (from `validate_db.py --markdown`), how to contribute and validate, known gaps.
- `data/nature/LICENSE.txt`: CC BY 4.0 notice, attribution string ("Sylva — nature library and industry R&D map, CC BY 4.0"), note that GBIF/OpenAlex/Crossref data keep their own licences, and that the CC BY vs CC0 choice is still open (ch.7 §7.9 item 4).
- Root `README.md`: nature endpoints, layout, roadmap lines.
- `connected-systems/07-building-the-nature-arm.md`: short "Build status (2026-10-10)" note after §7.5 step 5 pointing to the code and v0 numbers.

**Final verification checklist**
- `python -m pytest -q` → all pass.
- `python scripts/nature/validate_db.py` → exit 0.
- `cd frontend && npm run build` → success.
- Anti-pattern greps return nothing: `text-embedding-004|taskType` in `app/services/nature`; `species_db` in `app/services/nature` and `app/routers/nature.py`; `rank_bm25|sklearn|faiss|chromadb|langchain` in `app`, `scripts/nature`, `requirements.txt`; `abstract_inverted_index` in `data/nature`; `asknature.org` in `library.json` only inside `see_also`.
- `vercel.json` includes `data/nature`.
- Uvicorn smoke: `/api/v1/nature/stats`, `POST /api/v1/nature/ask` (fallback) return 200.
