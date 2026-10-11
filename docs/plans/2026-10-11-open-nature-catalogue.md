# Open Nature Catalogue — implementation plan

Status: READY. The user confirmed sorting decisions S1–S6 and S8–S9 on 2026-10-11. S7 is assumed (not answered). The user asked for this plan on 2026-10-11: "Yes lets build towards this huge database, write the plan for creating this database and ask me questions on how exactly you are going to sort the data."

## 1. Goal

Build a large, open, downloadable catalogue of biomimicry ideas and nature-friendly solutions. Target: 25,000 to 50,000 records.
- Every record is sorted by industry sector.
- Every record points to a conservation group that protects the source organism or habitat.
- The website shows the whole catalogue sector by sector, and every sector and the whole set can be downloaded as CSV and JSON.
- No RAG, no LLM, no embeddings. Sorting is deterministic, so anyone can re-run it and get the same result.

How it differs from the existing nature library (`data/nature/library.json`, 109 hand-checked records):

| | Library (existing) | Catalogue (new) |
|---|---|---|
| Size | ~100 served | 25k–50k |
| How built | sourced, reviewed record by record | bulk-harvested from open sources, sorted by rules |
| Trust label | `ai_extracted` / `peer_reviewed` | `machine_sorted` on every record, plus a published precision figure from a human spot-check |
| Use | ask / RAG | browse and download |

The two stay separate files. A catalogue record may link to a library record (`library_id`), never the other way round.

Out of scope (the user said "leave the agroforestree database for now"): the Agroforestree licence and PDFs, and Sylva species data.

## 2. Sorting decisions (confirmed by the user 2026-10-11 unless marked)

| # | Question | Decision |
|---|---|---|
| S1 | Which sectors? | The 10 existing taxonomy sectors plus new sectors only where harvested data demands them (see Phase 1), all mapped to NACE Rev.2.1. Anything that fits none goes in `other`, which is shown, not hidden. |
| S2 | One sector per record or several? | One `primary_sector` (decides where the record appears on the page) plus up to 3 `sector_tags` (filters and secondary listing). |
| S3 | How to order records inside a sector? | Group by area (form, process, materials, energy, circularity, systems, place), then by evidence type (project > patent > paper), then newest first. |
| S4 | What counts as "eco"? | Biomimicry / bio-inspired work, plus nature-based solutions. Green tech that is not inspired by nature is excluded, otherwise patents alone would run to hundreds of thousands. |
| S5 | How is a record sorted? | Rules only: the source's own codes (patent CPC, OpenAlex topic/subfield, CORDIS EuroSciVoc, Climate-ADAPT sector) through a written concordance to NACE, then keyword rules from `taxonomy.json`. The classifier score is stored as `sort_confidence`. |
| S6 | Donation group granularity | By habitat (about 14 habitats, for example marine, freshwater, wetland, forest, dehesa/savanna, grassland, mountain, arid, coastal, soil, urban, pollinators, birds) with a curated list of groups per habitat. Flagship organisms get a species-specific group where one exists. |
| S7 | Donation purpose | ASSUMED (not answered): (C) Plain outbound donation links now. Company pay-back pledges come later, with Sylva acting as a directory only, never taking money. |
| S8 | Quality check | A separate Claude review agent marks a 200-record stratified sample (sector right/wrong, relevant/irrelevant), and the user skims its calls. The published figure is labelled "agent-checked sample, owner-skimmed", never "human-verified". |
| S9 | Entries whose source text is not openly licensed | Show title, organism, sector, year and a link to the original. A summary appears only where the source licence passes the gate. No generated summaries. |

## 3. Phase 0 — Documentation discovery (done 2026-10-11; consolidated)

Sources: job research reports `tmp/research/sources.md` and `tmp/research/donations.md` (copied into `docs/plans/research/` in Phase 1), plus repo reads.

### 3.1 Allowed data sources (GREEN: open licence and bulk access)

| Source | Licence (quoted) | Access to use | What we keep |
|---|---|---|---|
| OpenAlex works | "Our complete dataset is free under the CC0 license" (help.openalex.org) | REST `https://api.openalex.org/works`, cursor paging, `per_page` ≤ 200, keyless. Pattern: `scripts/nature/harvest_openalex.py` `build_params` / `cached_fetch` / `harvest_sector` | metadata, topics, DOI, OA licence. Abstract text ONLY when `best_oa_location.license` is `cc-by` or `cc0` |
| CORDIS projects | "Editorial content owned by the EU is licensed under CC BY 4.0"; attribution "European Union, CORDIS - https://cordis.europa.eu - CC BY 4.0" | bulk CSV/JSON from data.europa.eu (H2020, Horizon Europe, FP7 project files) | title, objective, keywords, programme, EuroSciVoc, coordinator country |
| PatentsView (USPTO) | "all content is licensed under a Creative Commons Attribution 4.0 License" | bulk TSV zips (`g_patent`, `g_patent_abstract`, `g_cpc_current`); no account | title, abstract, CPC, date, assignee organisation |
| Climate-ADAPT (EEA) | "EEA materials are published under the CC-BY license … commercial or non-commercial" (legal notice); third-party content excluded | polite sitemap harvest, ~130 case studies | title, summary, sector tags, location |
| GBIF backbone | CC BY 4.0 | `https://api.gbif.org/v1/species/match` (pattern already in `scripts/nature/verify_sources.py`) | taxon key, canonical name, kingdom/class |
| Natura 2000 (EEA) | EEA legal notice: CC-BY (dataset licence to re-check in Phase 7) | EEA download | ES/PT site ↔ habitat ↔ species, for suggesting reserves |
| Wikidata | CC0 | SPARQL | identifiers only (taxon ↔ GBIF ↔ org) |

### 3.2 Link-only (AMBER): facts and a URL, no copied text, no bulk harvest
PANORAMA (CC BY-NC), WOCAT (CC BY-NC-SA), Oppla/NetworkNature, Ellen MacArthur Foundation, WIPO GREEN, Urban Nature Atlas, EU Ecolabel (licence unverified). v1 lists them on a "More directories" panel. No records are created from them.

### 3.3 Banned (RED)
- **AskNature.** Its ToS bans copying, robots, data mining and reproducing its taxonomy, and it is all-rights-reserved. This is the same failure as Agroforestree.
- **Drawdown bulk**, because scraping is banned.
- **WDPA / Protected Planet, KBA, IUCN Red List data.** These bar redistribution, and "commercial" includes non-profit revenue.

### 3.4 Repo patterns to copy
- HTTP with retry and Retry-After: `scripts/nature/_http.py` `fetch_json`.
- Paged, cached harvest: `scripts/nature/harvest_openalex.py:332-400` (`build_query`, `build_params`, `cached_fetch`, `harvest_sector`).
- Keyword sector classifier: `harvest_openalex.py:142-176` (`sector_hits`, `classify`) over `taxonomy.json` `sectors[].keywords_en/keywords_es` and `nace_rev21_divisions`.
- Organism detection from titles: `harvest_openalex.py:178` `find_organism`.
- Licence gate regex: `app/models/nature.py`, `re.fullmatch(r"CC-BY(-\d\.\d)?|CC0(-1\.0)?", ...)`.
- Export conventions: `app/routers/nature.py:367` `/nature/export/{db}`. Covers the JSON wrapper `{licence, licence_url, attribution, version, db, records}`, CSV `Link` / `X-Attribution` headers, `_csv_cell` formula-injection guard, and the `-CC-BY-4.0` filename.
- Store loading and the 503 pattern: `app/services/nature/store.py` `NatureStore`, `NatureDataError`.
- Frontend page and tabs: `frontend/src/Nature.jsx`, `frontend/src/api.js`, `Nature.css`.
- Tests: `tests/nature/test_harvest_openalex.py` (mocked fetch), `tests/nature/test_router.py`.

### 3.5 Anti-patterns (grep these in every phase)
- Any email in an HTTP request: `mailto`, `email=`, `User-Agent` containing `@`. Crossref's polite pool is NOT used.
- `asknature.org` in any harvester or fetch call (a link in docs is OK).
- Copying abstract/summary text from a source whose licence fails the licence gate.
- Any LLM or embedding call in the catalogue pipeline (`generativelanguage`, `embed`, `gemini`).
- Committing raw harvest caches (`data/nature/catalogue/raw/` must be in `.gitignore`).
- Inventing API params. Use only the params in the patterns above or in the source's docs, cited in a code comment.

## 4. Data model

`data/nature/catalogue/` (new):
- `sectors.json` — catalogue sector list (S1): id, labels en/es/pt, NACE divisions, keywords, CPC prefixes, OpenAlex subfield ids, EuroSciVoc ids.
- `habitats.json` — habitat list (S6): id, labels, keywords, organism classes (GBIF class/order).
- `groups.json` — curated conservation groups: id, name, country, habitats[], flagship_taxa[], donate_url, every_org_slug|null, source_url (where the donate URL was found), checked_on.
- `concordance.json` — CPC prefix → sector, OpenAlex subfield → sector, EuroSciVoc → sector, Climate-ADAPT sector → sector. Every row carries a note.
- `build/` (generated, git-ignored except `manifest.json`): `catalogue.json`, `catalogue.csv`, `sector-<id>.json`, `sector-<id>.csv`, `manifest.json` (counts per sector/area/source, build date, source snapshot dates, spot-check precision).

Catalogue record (Pydantic `CatalogueRecord` in `app/models/catalogue.py`; `extra="forbid"` like the library models):
```
id: "cat-000001"
title: str
summary: str | null          # only when source licence passes the gate; else null
summary_licence: str | null
kind: "paper" | "patent" | "project" | "case_study"
source: "openalex" | "cordis" | "patentsview" | "climate_adapt"
source_id: str               # W…, patent number, CORDIS rcn/id, page slug
url: str                     # canonical landing page
doi: str | null
year: int | null
countries: [ISO2]
organism: {name, gbif_key, rank} | null
habitat_id: str | null
primary_sector: str
sector_tags: [str] (≤3)
area: str | null             # from taxonomy areas
functions: [str]             # from taxonomy functions, may be empty
sort_confidence: float 0-1
sort_reason: str             # e.g. "cpc:E04B1/74 -> construction-materials"
group_ids: [str]             # donation groups via habitat/flagship
library_id: str | null
provenance: "machine_sorted"
licence: "CC-BY-4.0"         # licence of the catalogue record itself
source_licence: str
```

## 5. Phases

Each phase ends with a commit on `worktree-connected-systems-manifesto` (or a new branch cut from it), a push, and a ledger line. No phase calls an LLM.

### Phase 1 — Schema, sector list, concordance
What:
- Copy the research reports into `docs/plans/research/`.
- Write `app/models/catalogue.py`, copying the model style and licence validator in `app/models/nature.py`.
- Write `sectors.json`, `habitats.json`, `concordance.json` and an empty `groups.json`.
- Write `scripts/nature/catalogue/validate.py`, copying `scripts/nature/validate_db.py`.

Sector list (S1), default: the 10 existing sectors plus these candidates. Each is kept only if Phase 3 data shows ≥ 300 records:
- `health-medical` (NACE 21, 32.5, 86)
- `electronics-ict` (26, 61-63)
- `machinery-robotics` (28)
- `aerospace-transport` (30, 49-51)
- `buildings-architecture` (41-43, 71.1)
- `forestry-fisheries` (02, 03)
- `waste-recycling` (38)
- `other`

Docs: `taxonomy.json` sectors shape; NACE Rev.2.1 division list (cite Eurostat page in the file header); CPC scheme section titles (cite WIPO/EPO CPC page).

Verify:
- pytest for the model, covering the licence gate for summary, ≤3 sector_tags, and that primary_sector is in sectors.json.
- validate.py exits 0 on a 5-record fixture.

Guards: no new top-level dependency without a note; ids are stable slugs.

### Phase 2 — OpenAlex harvester
What: `scripts/nature/catalogue/harvest_openalex.py`, copying the paging and cache logic from `scripts/nature/harvest_openalex.py:332-400`.
- Query: title/abstract search over the biomimicry term list (biomimetic, biomimicry, bioinspired, bio-inspired, nature-inspired, biomimetics) plus a nature-based-solutions list (S4).
- Fields: `select` only what we need.
- `per_page=200`, cursor paging, keyless.
- The raw cache is written to `data/nature/catalogue/raw/openalex/`.
- Abstract rebuilt from `abstract_inverted_index` only if `best_oa_location.license` ∈ {cc-by, cc0}.

Verify:
- Mocked-fetch tests, copying the `tests/nature/test_harvest_openalex.py` style.
- A dry run of 2 pages live logs counts.
- Grep shows no email in params.

Guards: a request budget flag; resume from the last cursor; no S3 snapshot (the API is enough at ~165k works / 200 per page ≈ 830 calls).

### Phase 3 — CORDIS, PatentsView, Climate-ADAPT harvesters
What:
- **CORDIS:** download the project bulk files (H2020, HORIZON, FP7) from data.europa.eu into raw/, then keyword-filter the title, objective and keywords.
- **PatentsView:** download the bulk zips into raw/ (several GB; this phase checks free disk first). Filter by bio-inspired keywords in title/abstract, plus CPC families listed in concordance.json (for example B81, B82Y, A01N, E04B, C02F, Y02).
- **Climate-ADAPT:** sitemap harvest with 1 request/second and a `User-Agent` naming the project (no email). Skip pages marked third-party.

Each harvester writes a normalised `raw/<source>/records.jsonl` with the common fields, before any sorting.

Docs: data.europa.eu CORDIS dataset pages; the PatentsView bulk data dictionary; the Climate-ADAPT legal notice (quote in file header).

Verify:
- Unit tests with tiny fixture files per source.
- A real run prints counts per source.
- Licence fields are set on every row.

Guards: no EU Login and no PatentsView API key (bulk only); do not keep CORDIS deliverables or personal names.

### Phase 4 — Normalise, dedupe, link organisms
What: `scripts/nature/catalogue/build.py` step 1.
- Merge the JSONL files.
- Dedupe by DOI, then by normalised title + year; patents and papers by the same group stay separate.
- Detect organisms with `find_organism` plus a list of organism words; confirm against the GBIF species match (pattern from `verify_sources.py`), with an on-disk cache.
- Flag biochemical/genetic records (keywords: peptide, enzyme, gene, DNA, protein sequence…) with `genetic_resource_hint: true`. They are still listed (they are public publications) but get no "pay-back" wording (Nagoya ABS note).

Verify:
- Tests for dedupe and the GBIF cache.
- A report of the duplicate rate and the share of records with an organism.

### Phase 5 — Sort (the S1–S5 rules)
What: `build.py` step 2, pure functions in `scripts/nature/catalogue/sort.py`.
- primary_sector, in priority order: source codes through concordance.json, then `taxonomy.json` keyword hits (copy `classify`), then `other`.
- sector_tags: the next best ≤ 3 with score ≥ threshold.
- Also area, functions and habitat.
- `sort_confidence` and `sort_reason` on every record.

Verify:
- A table-driven test of 30 hand-labelled examples.
- Coverage report: per sector, per area and per source, plus the `other` share.
- The build fails if `other` > 25% (the threshold can be tuned in sectors.json).

Guards: no LLM. Rules live in JSON, not code, so they can be reviewed.

### Phase 6 — Spot-check (S8)
What:
- `scripts/nature/catalogue/spotcheck.py sample` draws 200 records, stratified by sector with a fixed seed, into `spotcheck.csv` with columns `id, title, url, primary_sector, sort_reason, verdict_sector, verdict_relevant, note`.
- A separate review subagent (sonnet; it did not write the rules) fills the verdict columns using only the title, the source page and `sectors.json` definitions.
- The user skims the CSV and can overturn any row.
- `spotcheck.py score` computes precision per sector and overall, and writes it to `manifest.json` with `checked_by: "agent, owner-skimmed"`.

Verify: the manifest shows precision; any sector under 70% gets its rules fixed and is re-sampled before publishing, or the page shows a warning on it.

Note: the user's skim is the one step that needs a person.

### Phase 7 — Donation groups
What:
- Curate `groups.json` by hand: about 40 groups, both ES/PT and global, covering every habitat. Seed list from the research: SEO/BirdLife, WWF España, ANP|WWF Portugal, Quercus, LPN, Rewilding Spain, Rewilding Portugal, Rewilding Europe, World Land Trust, Rainforest Trust and others.
  - `donate_url` is the group's own page.
  - `every_org_slug` is set only where listed, giving the link `https://www.every.org/<slug>#donate`.
- Assign each record's groups: flagship taxon match first, then its habitat's groups (max 3).
- Optional: suggest Natura 2000 sites for ES/PT records with an organism, after re-checking the dataset licence.

Verify:
- validate.py checks every habitat has ≥ 2 groups, every URL is https, and every group has `checked_on`.
- A link check script (HEAD/GET, no email) reports dead links.

Guards:
- No WDPA/KBA/IUCN data.
- Wording on the page: "Support the people protecting this habitat". Never "benefit sharing" and never "pays the reserve" (Nagoya).
- Sylva never handles money.

### Phase 8 — Publish files
What: `build.py` step 3.
- Write the `build/` shards; each CSV gets a licence column, and the JSON keeps the export wrapper shape.
- Write `manifest.json`.
- Write `data/nature/catalogue/README.md` covering sources, licences, attribution lines (OpenAlex CC0, CORDIS line, PatentsView line, EEA line, GBIF), method, precision and known gaps.
- Size budget: if `catalogue.json` > 50 MB, publish the full set as a GitHub Release asset and commit only per-sector gz shards for the website (decided at build time; recorded in the ledger).

Verify:
- Re-running the build gives byte-identical output (deterministic).
- The formula-injection guard is applied to CSV (copy `_csv_cell`).
- validate.py exits 0 on the full build.

### Phase 9 — Website
What: a "Catalogue" view in the frontend, either a new tab in `Nature.jsx` or a new `Catalogue.jsx` route; copy the existing tab and fetch patterns.
- Sector list with counts from `manifest.json`.
- Clicking a sector lazy-loads `sector-<id>.json` and shows records grouped by S3 order.
- Client-side text filter.
- Columns: title, organism, kind, year, source link, and donation group buttons.
- A "machine-sorted" badge and the sector's precision.
- Download buttons: this sector (CSV/JSON) and everything.
- A "More directories" panel lists the AMBER sources as links.
- Long lists use a simple windowed list or a "show 100 more" control (no new heavy dependency).

Serving: shards are served as static files (Vite `public/` or the API static route; pick whichever deploys on Vercel without hitting function size limits, and check `vercel.json`).

Verify:
- `npm run build`.
- A manual check in the browser on desktop and phone width.
- The download opens and carries attribution.

### Phase 10 — Final verification
- `python -m pytest -q`, catalogue validate, `npm run build`.
- Run every grep from 3.5; all must return nothing.
- Re-run the build: the hash is unchanged.
- Docs: a catalogue section in the root README and in `connected-systems/07-building-the-nature-arm.md`.
- Memory: update `nature-arm-v0.md`.
- Ledger closed; branch pushed; draft PR only if the user asks.

## 6. Estimates
- OpenAlex 20k–40k usable, CORDIS 3k–8k, PatentsView 5k–15k, Climate-ADAPT ~130.
- After dedupe and the S4 scope filter: 25k–50k. These are honest ranges from live counts on 2026-10-11, not promises.
- Records with a reusable summary: about 30–40% (the OA CC-BY share). The rest show title, link and sorted facts only.

## 7. Risks
- **Sorting noise at scale.** Mitigated by the published precision, the `sort_reason` on every row and the `other` cap.
- **Biomedical flood.** OpenAlex "biomimetic" is heavy in drug delivery and tissue engineering. S1/S4 decide whether it gets a `health-medical` sector or is excluded.
- **Donation links rot.** `checked_on` plus a link-check script.
- **Repo and deploy size.** The Phase 8 size budget.
