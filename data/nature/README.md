# Sylva nature databases: datasheet

Version 0.1.0. Licence CC BY 4.0 (see `LICENSE.txt`).

Attribution: **Sylva — nature library and industry R&D map, CC BY 4.0**

This folder holds two open databases and the vocabulary that joins them.

| File | What it is |
|---|---|
| `taxonomy.json` | Areas, functions, sectors, TRL levels, evidence grades, provenance statuses. Our own wording. |
| `library.json` | The nature library: mechanisms, materials, processes and practices, each with sources. |
| `industry_map.json` | The industry R&D map: papers and companies in Spain and Portugal, by sector. |

Files created on demand: `library_staging.json` (extraction output awaiting review) and `review_log.jsonl` (reviewer actions) are local and git-ignored; `index/` (embeddings, only after `build_index.py` runs with a key) can be committed so the vectors ship with the data.

The design is in `connected-systems/07-building-the-nature-arm.md` (sections 7.2 and 7.3) and `connected-systems/02-biomimicry-blueprint.md` (the ranking, section 2.4).

## Coverage (v0)

Generated with `python scripts/nature/validate_db.py --markdown`.

| Metric | Value |
|---|---|
| Library records | 66 |
| Served by the API | 61 |
| Quarantined (never served) | 5 |
| Provenance (served records) | 57 ai_extracted, 4 disputed, 0 expert_validated |
| Records with a measured value | 2 (3.3%) |
| Records by kind (served) | 38 mechanism, 9 material, 6 process, 8 practice |
| Records by area (served) | form 35, energy 19, place 14, materials 14, systems 14, circularity 8, process 5 (a record can have several areas) |
| Map records | 507: 502 papers, 5 companies |
| Map by country | ES 322, PT 185 |
| Map by sector | steel-aluminium 58, construction-materials 59, packaging 57, cosmetics 51, textiles 53, automotive 47, energy 42, agrifood 41, water-utilities 50, chemicals 49 |

Source checks: 87 of 88 DOIs in the library verify against Crossref (see Known gaps for the one that does not).

Nothing in v0 has been validated by an expert. Every served record says so in its provenance, and the API and the web page show it.

## Taxonomy

- **Areas (7):** form, process, materials, energy, circularity, systems, place. Each has a guiding question.
- **Functions (about 40 in 12 groups):** what a thing does, in our own words, for example `shed-water`, `self-clean`, `absorb-impact`, `biodegrade`. Each function has English and Spanish keywords, used to read a challenge and to label map papers. An optional `asknature_group` holds only the short name of the matching AskNature group, as a crosswalk. Groups: manage water, manage heat, manage air and gases, resist and support loads, protect surfaces, attach and join, make and assemble, break down and recycle, sense and respond, move efficiently, sustain ecosystems, optimise systems.
- **Sectors (10):** steel-aluminium, construction-materials, packaging, cosmetics, textiles, automotive, energy, agrifood, water-utilities, chemicals. Each maps to NACE Rev.2.1 divisions, equal to CNAE-2025 at 2 digits.
- **TRL (1 to 9):** Horizon Europe wording, verbatim, with the source URL in the file.
- **Evidence grades:** `strong` (two or more sources with a DOI or URL, and at least one measured value), `moderate` (two or more sources, or one source with a measured value), `weak` (one source, no measured value), `contested` (provenance `disputed`, or a popular-claim note is set). Computed in code, never stored.
- **Provenance statuses:** `ai_extracted` (written by a model from the cited source, not yet checked by a person), `expert_validated` (checked by a named expert on a date), `disputed` (an expert or reviewer has questioned it).

## Schemas

Both are enforced by pydantic models in `app/models/nature.py` (unknown fields are rejected).

### Library record

| Field | Meaning |
|---|---|
| `id` | `lib-0001` style. |
| `kind` | mechanism, material, process, practice. |
| `title`, `summary` | Our own words, 1 to 4 sentences. |
| `areas`, `functions`, `sector_tags` | Taxonomy ids. At least one area and one function. |
| `organism` | scientific name, common names, kingdom, GBIF usage key and match type. Optional. |
| `trait`, `structure`, `mechanism` | What the organism does and how. `mechanism` is required for kind mechanism. |
| `trait_type` | morphological, biochemical, genetic, behavioural, ecological, not_applicable. |
| `legal_review` | not_required, pending, cleared. Biochemical and genetic traits cannot be not_required. |
| `knowledge_source` | peer_reviewed, grey_literature, traditional, field_observation. |
| `consent` | not_applicable, pending, granted. Traditional knowledge cannot be not_applicable. |
| `performance` | list of metric, value (or null), units, and where it was measured (literature, reproduced, field). |
| `evidence` | At least one: citation, DOI, URL, year, open access flag, licence, supporting sentence, page, verified flag. |
| `known_products` | Products that use the idea, if any. |
| `popular_claim_note` | Used when a famous claim is wrong or overstated. |
| `provenance` | status, who extracted it and when, who validated it and when. Validated needs both. |
| `confidence` | low, medium, high. |
| `caveat` | Required. What a reader must know before relying on the record. |
| `source_region`, `contributors`, `see_also` | Where the knowledge comes from, who contributed, links (AskNature is link only). |

### Industry map record

| Field | Meaning |
|---|---|
| `id` | `map-0001` style. |
| `type` | paper, patent, grant, project, company. v0 holds papers and companies. |
| `title`, `summary` | Summary is empty for auto-harvested items. |
| `sector`, `nace_divisions` | Sector id and NACE Rev.2.1 divisions. |
| `problem_functions` | Taxonomy functions the item works on. This is the join key to the library. Often empty (see Known gaps). |
| `areas`, `nature_link` | biomimetic, bio_based, nature_based_solution, circular, other. |
| `country`, `region`, `organisations` | ISO country, organisations with kind and ROR id where known. |
| `year`, `trl` | Publication year, and TRL 1 to 9 when known. |
| `identifiers` | DOI, OpenAlex id, patent number, grant id, URL. |
| `library_links` | Library ids, set by reviewers. |
| `source` | Name, licence and retrieval date. |
| `provenance` | Same shape as the library. |

## Source policy

| Allowed in these files | Link or cite only, never copy |
|---|---|
| Our own summaries, written from primary literature | AskNature text and taxonomy |
| DOI, title, year, venue, institutions (facts; OpenAlex and Crossref) | Publisher abstracts (the OpenAlex abstract field is never stored) |
| GBIF names and usage keys (CC BY 4.0, attributed) | EPO OPS or Lens raw data |
| NACE Rev.2.1 / CNAE-2025 codes, Horizon Europe TRL wording | Sylva's `data/species_db.json` |
| A verbatim supporting sentence, only from papers licensed CC BY or CC0 (not SA, NC or ND) | Client problems or findings |

No DOI, GBIF key, company or measured value is invented. A null is used instead of a guess. Every DOI is checked by `scripts/nature/verify_sources.py`.

## Serving gate

A record stays in `library.json` with its status visible, but is **never served** by the API, the web page or the exports when either holds:

- the trait is biochemical or genetic and `legal_review` is `pending`, or
- the knowledge is traditional and `consent` is not `granted`.

In v0, 5 of 66 records are quarantined this way (for example PHA and bacterial cellulose, held for legal review). Map `library_links` that point at a quarantined record are dropped from responses. The gate is `NatureStore.is_servable` in `app/services/nature/store.py`.

## How a record is ranked

Retrieval and ranking are deterministic and published. The model never ranks, scores or sets provenance.

`score = evidence (0 to 30) + provenance (0 to 25) + fit (0 to 20) + manufacturability (0 to 15) + regional (0 to 10)`

- Evidence: strong 30, moderate 20, weak 10, contested 0.
- Provenance: expert_validated 25, ai_extracted 10, disputed 0.
- Fit: 20 times the retrieval score (min-max normalised over the hit list) times (0.5 + 0.5 times the share of the challenge's parsed functions the record covers).
- Manufacturability: 15 if the record lists known products or a map record links to it.
- Regional: 10 if the record names a reserve, 5 if it names a region.

Two rules sit on top of the formula:

1. **Function-first tiers.** When the challenge parses to at least one function, records that match one of those functions rank above all others. Within a tier, the score decides. A record outside the first tier cannot get a "promising" verdict.
2. **Function-based recall.** Records carrying the parsed functions are added to the candidates even when their text does not match the query. This is why a challenge written in Spanish or Portuguese finds the English-language records: the function is read from the Spanish or Portuguese keywords, and the library text is English.

The answer text is phrased by a model when `GEMINI_API_KEY` (or its alias `GOOGLE_API_KEY`) is set. It can only cite record ids that were retrieved, and a citation guard enforces that. Without a key, retrieval is BM25 plus function recall only, and the answer is a deterministic fallback built from the ranked records. The embedding index and the model path are implemented, but have only been tested with mocks so far. To activate them, set the key and run `python scripts/nature/build_index.py`.

Sector gaps are computed from classified map papers only. The response always shows how many papers in the sector are unclassified.

## Using the data

- API: `GET /api/v1/nature/library`, `/map`, `/sectors`, `/sectors/{id}/gaps`, `/stats`, `/meta`, `POST /api/v1/nature/ask`, and `GET /api/v1/nature/export/{library|industry_map}?format=json|csv` (`map` is accepted as an alias for `industry_map`). Library exports contain served records only.
- Licence in exports: JSON exports are an object `{"licence", "licence_url", "attribution", "version", "db", "records": [...]}`. CSV exports stay a plain table with no comment rows; the licence travels in the `Link: <https://creativecommons.org/licenses/by/4.0/>; rel="license"` and `X-Attribution` headers (ASCII, with "-" for the dash) and in the file name (`...-CC-BY-4.0.csv`). **If you use a CSV export, you must keep the attribution with it yourself.**
- Files: read the three JSON files directly. Remember to apply the serving gate if you republish the library.
- Web page: `/nature`.

## Contributing and validating

1. Add or edit records in `library.json` or `industry_map.json`. Use only taxonomy ids from `taxonomy.json`. Write summaries in your own words from the primary source.
2. Run `python scripts/nature/validate_db.py`. It must print `OK` and exit 0. Add `--markdown` for the coverage table.
3. Run `python scripts/nature/verify_sources.py` to check DOIs against Crossref (network needed; `--dry-run` skips writes).
4. For model-assisted extraction from papers: `python scripts/nature/extract_mechanisms.py --dois ...` writes to `library_staging.json`. A person then runs `python scripts/nature/review.py list|show|promote|validate|dispute`, with `--by <name>`. Promoted records stay `ai_extracted` until an expert runs `validate`. Biochemical and genetic records are promoted as `legal_review: pending`.
5. To refresh the map: `python scripts/nature/harvest_openalex.py` (an optional `OPENALEX_API_KEY` raises the daily budget).
6. Run `python -m pytest -q`.

Reviewers are welcome, especially for traditional knowledge (consent) and the biochemical records waiting on legal review.

## Known gaps

- **No expert validation yet.** No record is expert_validated. Treat every record as a lead to check, not a finding.
- **Few measured values.** 2 records (3.3%) carry a measured value, so most records grade as weak or moderate evidence.
- **The map's function labels come from keywords.** Precision was favoured over recall: about 22% of the labels that exist are estimated to be doubtful, and about 69% of papers (347 of 502) have no label at all. Gap counts are therefore biased low and are reported as "classified papers only", with the unclassified count shown.
- **The map holds papers and companies only.** No patents, grants or projects in v0. Company type comes from OpenAlex and is taken at face value (a synchrotron facility is tagged as a company).
- **Map labels are not linked to the library yet.** `library_links` is empty until reviewers set it.
- **Iberia only.** Spain and Portugal, 10 sectors. The library has no Spanish or Portuguese text; Spanish and Portuguese challenges work through function keywords.
- **One DOI does not verify automatically.** Chertow 2000 is correct, but its Crossref title contains markup, so the title check fails. 87 of 88 DOIs verify.
- **`known_products` is loose.** Some entries are product categories rather than specific products, and still earn the manufacturability points.
- **Keyword overlaps.** A few terms (superhydrophobic, aerodynamics) sit under two neighbouring functions, so a query can pull in both.
- **Embeddings and the model path are untested live.** They need `GEMINI_API_KEY` (or `GOOGLE_API_KEY`).
- **CC BY or CC0 is undecided** (7.9, item 4).
