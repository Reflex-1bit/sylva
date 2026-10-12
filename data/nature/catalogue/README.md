# Sylva Open Nature Catalogue

An open, sector-sorted catalogue of research and innovation records about learning from nature
(biomimicry, bio-inspired design, nature-based solutions): scholarly papers, EU research projects
and adaptation case studies. Each record is filed under one primary industry sector (plus up to three
tags), a design area and the nature functions it touches, and, where it names an organism or habitat,
links to groups that protect that habitat.

This build holds 99,309 records in 16 sectors. The compilation (the selection, sorting and grouping) is
licensed CC-BY-4.0 by Sylva. Every record keeps its own `source_licence` and `summary_licence`; a summary is
stored only when its source licence is CC BY or CC0, so only 15,319 records carry one.

## Sources, counts, licences and attribution lines

| Source | Records | Licence | Attribution line |
|---|---|---|---|
| OpenAlex (https://openalex.org) | 98,604 | CC0 | OpenAlex (CC0) |
| CORDIS (https://cordis.europa.eu) | 628 | CC BY 4.0 | CORDIS (© European Union, CC BY 4.0) |
| Climate-ADAPT (https://climate-adapt.eea.europa.eu) | 77 | CC BY 4.0 | Climate-ADAPT (© EEA, CC BY 4.0) |
| GBIF Backbone Taxonomy (organism names only) | 11,336 records linked | CC BY 4.0 | GBIF Backbone Taxonomy (CC BY 4.0) |

Counts are after de-duplication (101,669 harvested; 40 merged by DOI, 2,320 by title, year and kind).
Whole-catalogue attribution: `Sylva - Open Nature Catalogue, CC BY 4.0. Sources: OpenAlex (CC0); CORDIS
(© European Union, CC BY 4.0); Climate-ADAPT (© EEA, CC BY 4.0); GBIF Backbone Taxonomy (CC BY 4.0)`.
The manifest builds this line from the sources actually present. CSV files must keep the attribution line
with them.

## Method

Rules only. No LLM and no embeddings are used anywhere; the same inputs and GBIF cache give the same output.

1. **Merge.** Raw harvests are validated, contact clauses are scrubbed from summaries, and duplicates are
   merged. Organisms come from a common-name lexicon or a Latin binomial confirmed on the GBIF species
   match API; habitats from the lexicon or habitat keywords.
2. **Sort.** Each record scores every sector from curated concordance rows (CPC patent codes, OpenAlex
   subfields, EuroSciVoc and Climate-ADAPT terms) plus strong and weak keywords in English and Spanish.
   The highest score is the primary sector. `sort_reason` records the exact signals that won, for example
   `subfield:Catalysis(+1.0); kw:polymer(+0.05)`. A tie inside the sector order is marked `; tie`; a tie
   below 0.4 goes to `other` with a reason that names the tied sectors and their score, for example
   `weak-tie: machinery-robotics=0.25, chemicals=0.25`. A best score under 0.2 gives `other` with `no-signal`.
3. **Confidence.** `sort_confidence` is the winning score (capped at 1) reduced by the runner-up's
   share, and capped at 0.6 when no code signal (only keywords) supports the sector. When an OpenAlex
   subfield is the only code signal and no strong keyword of the sector backs it up, it counts half and
   the reason carries `[uncorroborated]`.
4. **`other` cap.** The build fails if `other` holds more than 25% of the records. This build: 8.4%.
5. **Candidate sectors collapse.** Sectors marked as candidates need a minimum number of primary records.
   `forestry-fisheries` (206) and `waste-recycling` (176) fell under 300, so their records were re-sorted
   without them and they are not published.
6. **Groups.** Flagship groups for a named organism come first, then the groups of the record's habitat, at
   most three per record.
7. **Publish.** Records are written in order inside each sector (design area, then project, case study,
   patent, paper, then newest first, then id) as gzipped JSON chunks of at most 2,000 records.

## Spot-check status

Spot-check status: **agent, owner skim pending** (verbatim from `spotcheck/results.json`).

A 200-record blind sample, seed 23, was drawn on a fresh sample after tuning. Round 2 (published figure):
strict precision 62.8%, lenient 74.9%, relevance 78.7%. Per-sector figures are in the manifest.

## Known limits

- Precision was measured by independent AI agents on blind samples; the owner skim is still pending.
  Round 1 (seed 11, before tuning): strict 58.8%, lenient 76.4%, relevance 83.4%. Round 2 (seed 23, a fresh
  sample after tuning, the published figure): strict 62.8%, lenient 74.9%, relevance 78.7%.
- Sectors below 70% strict precision are flagged in the manifest with `precision_warning`, and a sector
  with fewer than 10 sampled records carries `low_sample`; treat those figures as indicative only.
- Basic science with no application often lands in a sector rather than in `other`.
- Some strong keywords (wing, flight, locomotion, ship, hull) also occur in biology text and can pull
  biology papers into engineering sectors.
- About half of the winning reasons carry `[uncorroborated]`, which means lower confidence.
- About 85% of records have no donation group, because they have no habitat or flagship organism.
- Round 2 was measured on the build at commit a88cafc. Later changes only touched the reason text, not
  the sectors.

## Support the people protecting this habitat

Records that name a habitat or a flagship organism show buttons for groups that protect it (49 groups in
`groups.json`; 14,330 records are linked to at least one). Sylva never handles money. Every link goes to the
group's own donation page.

## Known gaps

The same list is in the manifest under `pending`.

- OpenAlex nature-based-solution keywords are not yet fully harvested: 178 of 288 keyword jobs are done and
  110 are pending (keyless daily budget).
- PatentsView patents are deferred (needs a USPTO API key).

A GitHub Release of the full files is a possible later step; none has been made.

## Rebuild

From the repository root, in order (the raw harvests under `raw/` come first and are not committed):

```
python scripts/nature/catalogue/build.py merge --offline    # GBIF answers from the cache
python scripts/nature/catalogue/build.py sort
python scripts/nature/catalogue/build.py groups
python scripts/nature/catalogue/build.py publish
python scripts/nature/catalogue/validate.py --build data/nature/catalogue/build
```

`build.py all --offline` runs the four steps. Publishing fails if the chunks exceed 60 MB (warns above
40 MB; this build is 18.4 MB) or if `validate.py --build` fails.

## File layout

```
data/nature/catalogue/
  sectors.json habitats.json groups.json concordance.json   reference data (committed)
  spotcheck/            blind-sample results (results.json is the published round)
  raw/                  harvests (not committed)
  build/stage/          merged, sorted and grouped stage files (not committed)
  build/manifest.json   copy of the public manifest (committed)
  build/catalogue.json  all records in one wrapper (local only)
  build/catalogue.csv   the same as a table, lists joined with "; " (local only)
frontend/public/catalogue/
  manifest.json                         sectors, chunks (path, count, bytes, sha256), sources, groups, gaps
  <sector_id>/chunk-NNNN.json.gz        at most 2,000 records each, read in the browser with DecompressionStream
```
