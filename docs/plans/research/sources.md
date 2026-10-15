# Sylva open-dataset source survey (research date 2026-10-11)

Method: WebSearch/WebFetch only. No email in any request, no accounts. Several fetches were 403 (asknature.org, panorama.solutions/en/terms-of-use, gbif.org/terms); where a licence is not verified from a primary page, it is marked UNVERIFIED. Not legal advice.

## 1. Sources consulted
- AskNature ToS (Biomimicry Institute): https://biomimicry.org/terms/ (fetched); asknature copy at https://asknature.org/terms-of-service-privacy-policy/ (403, appears in search); older paper claiming CC BY-NC 3.0: https://www.researchgate.net/publication/285216902_The_AskNature_Database_Enabling_Solutions_in_Biomimetic_Design
- OpenAlex: https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication ; https://help.openalex.org/access/snapshot.md ; https://help.openalex.org/hc/en-us/articles/28926392245399-How-is-OpenAlex-open ; live API counts via api.openalex.org
- CORDIS: https://cordis.europa.eu/llms.txt (licensing + bulk access section)
- Wikidata licensing: https://www.wikidata.org/wiki/Wikidata:Licensing ; SPARQL counts via query.wikidata.org
- GBIF backbone licence via API: https://api.gbif.org/v1/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c
- Crossref: https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-metadata-license-information ; https://community.crossref.org/t/announcing-changes-to-rest-api-rate-limits-crossref/14726 (search snippets)
- Europe PMC / PMC OA: https://pmc.ncbi.nlm.nih.gov/tools/openftlist ; NAR paper https://academic.oup.com/nar/article/46/D1/D1254/4637578
- Semantic Scholar: https://www.semanticscholar.org/product/api/license ; https://github.com/allenai/s2orc
- Climate-ADAPT legal notice: https://climate-adapt.eea.europa.eu/en/legal-notice (fetched)
- PANORAMA Solutions terms: https://panorama.solutions/en/terms-use (via search summary only; fetch 403)
- Urban Nature Atlas: https://oppla.eu/product/18399 ; https://naturvation.eu/node/1986.html
- WOCAT: https://wocat.net/documents/448/QT_English_2019_CClicence.pdf
- WIPO GREEN: https://www3.wipo.int/wipogreen/en/terms_greendatabase.html ; FAQ https://www3.wipo.int/wipogreen/en/faqs.html
- Drawdown ToU: https://www.drawdown.org/terms-of-use (fetched)
- Ellen MacArthur Foundation, NetworkNature/Oppla: search only, no licence found
- EU Ecolabel catalogue: https://environmental-data.ec.europa.eu/ecolabel/ ; data.europa.eu search
- PatentsView: https://patentsview.org/download/data-download-tables ; https://search.patentsview.org/docs/2025/04/22/2.3.2-release
- Google Patents Public Data: https://github.com/google/patents-public-data ; Google Cloud blog
- Lens.org: only Syracuse guide https://researchguides.library.syr.edu/lensguide/use (terms NOT found)
- Sector classification: Aguilar-Planet & Peralta 2024 Biomimetics (https://doaj.org/article/fcafe0cb72ec427f8650beb28d1c490a); KU Leuven taxonomy classifier https://lirias.kuleuven.be/1511206

## 2. Candidate table (ranked)

Verified counts (live queries 2026-10-11): OpenAlex works matching title/abstract "biomimetic|bioinspired|biomimicry|bio-inspired" = 164,868; of those with best OA location licence cc-by = 28,577. Wikidata items with P941 "inspired by" pointing at a taxon-class item (rough test) = 47 (negligible).

### GREEN (open licence + bulk access)
| Source | Record | Size | Access | Licence (quote/link) | ToU forbids scrape/redistribute? | Rate limits | Sector field |
|---|---|---|---|---|---|---|---|
| OpenAlex https://openalex.org | scholarly work: abstract (inverted index), topics, SDGs, OA licence | 164,868 biomimetic works (this query); ~324M works total | S3 snapshot (JSONL/Parquet), REST API cursor paging | "Our complete dataset is free under the CC0 license" (https://help.openalex.org/hc/en-us/articles/28926392245399-How-is-OpenAlex-open). Metadata; abstracts publisher-owned in principle | No | 100 req/s; daily budget; free key = 10x keyless; 10,000 result paging cap, use cursor | Topic/field/subfield/domain (not NACE); SDG tags |
| CORDIS projects https://cordis.europa.eu | project: title, objective, keywords, programme, cost | >150,000 total (H2020 35,386; FP7 25,785); bio-inspired/NbS subset est. 3-8k | data.europa.eu bulk (CSV/JSON/XML/RDF), SPARQL (EURIO), REST (EU Login) | "Editorial content owned by the EU is licensed under CC BY 4.0"; data.europa.eu: CC0 metadata, CC BY 4.0 text. Attribution: "European Union, CORDIS - https://cordis.europa.eu - CC BY 4.0". Deliverables/publications excluded (grant agreements) | Discourages page scraping; use bulk | n/a | EuroSciVoc discipline, programme/topic; no NACE |
| Climate-ADAPT (EEA) https://climate-adapt.eea.europa.eu | case study / adaptation option | ~128 case studies (2024) plus several hundred database items | Web pages; no confirmed API; light scraping/sitemap | "EEA materials are published under the CC-BY license"; "may be re-used without prior permission, free of charge, for commercial or non-commercial purposes"; excludes third-party content. https://climate-adapt.eea.europa.eu/en/legal-notice | Silent on scraping | unknown | Yes: sector tags (agriculture, water, buildings, ecosystems...) |
| GBIF Backbone Taxonomy | taxon name | millions of names | simple.txt.gz download; REST API | API metadata: "Creative Commons Attribution 4.0 (CC BY 4.0)" | No | polite | n/a (organism linking) |
| PatentsView (USPTO) https://patentsview.org | granted US patent with abstract, CPC | millions; bio-inspired/Y02 subset est. 5-15k | Bulk TSV zips, API | "all content is licensed under a Creative Commons Attribution 4.0 License", attribute PatentsView | No | API key (account) for API; bulk needs none | CPC (mappable to NACE by concordance) |
| Wikidata | item | Thin for biomimicry (47 P941 hits) | SPARQL, dumps | "released into the public domain under Creative Commons Zero" | No | SPARQL timeouts | Sparse; use for identifiers/linking |
| Crossref https://api.crossref.org | DOI metadata | ~160M | REST, public dump | Bibliographic metadata = "facts", no restrictions; abstracts copyrighted by publishers (do not republish) | No | Revised 1 Dec 2025 (X-Rate-Limit-* headers). Polite pool uses email: do NOT send mailto | Subject only |
| Google Patents Public Data (BigQuery) | patent publication | tens of millions | BigQuery (requires Google Cloud account: conflicts with no-accounts rule) | Credit line "'Google Patents Public Data' by IFI CLAIMS Patent Services and Google, CC BY 4.0" | No | BigQuery quota | CPC. Prefer PatentsView |

### AMBER (metadata/link-only, or licence uncertain/conditional)
| Source | Record | Size | Access | Licence | Notes | Sector |
|---|---|---|---|---|---|---|
| Europe PMC / PMC OA https://europepmc.org | full-text article | millions; CC BY subset commercial-OK | REST API, FTP | Per-article. PMC groups: "Commercial Use Allowed - CC0, CC BY, CC BY-SA, CC BY-ND" vs NC groups. Europe PMC own ToU UNVERIFIED | Only CC BY/CC0 full text; mostly biomedical | Subject only |
| Semantic Scholar | paper, abstracts | 200M+ | Dataset downloads need API key (account); REST | API licence separate from data licences "such as CC BY-NC or ODC-BY"; S2ORC "ODC-By 1.0"; abstracts only "where allowed by licensing" | Skip; OpenAlex covers same | Fields of study |
| EU Ecolabel catalogue https://environmental-data.ec.europa.eu/ecolabel/ | licensed product/service | >100,000 products, ~3,000 companies | CSV on EU Open Data Portal + API | Dataset licence UNVERIFIED (EU Commission data usually CC BY 4.0 under Decision 2011/833/EU); "non-exhaustive" | Product layer, not ideas; verify on data.europa.eu | Product group |
| Urban Nature Atlas (NATURVATION/EEA) | NbS case in a city | ~1,000 (2017 data) | Web map; data "upon request" | Oppla lists "Public/open source"; no formal licence | Request in writing | Yes: NbS type |
| Project Drawdown | solution | ~150 | Datahub CSV mirror | ToU bans "crawling, scraping, or spidering"; written permission needed | Facts-only or ask; tiny | Yes |
| WIPO GREEN | technology/need | ~3,600 (2019) | Web, partly registration-gated | Own T&Cs, owners keep rights | Link-only | Categories |
| PANORAMA Solutions https://panorama.solutions | solution case study | ~1,500+ (1,578 per IUCN ToR) | Web + "PANORAMA API" (access reviewed individually) | ToU summary: default noncommercial, CC BY-NC 4.0; approved access may be BY-NC-SA | NC incompatible with CC BY 4.0. Ask IUCN for CC BY grant, else link-only | Yes |
| WOCAT | SLM technology/approach | >2,000 practices | Web, PDF per record | Questionnaires CC BY-NC-SA 4.0 (inconsistent link); database data terms not found | NC: link-only unless clarified | Land use |
| OPPLA / NetworkNature | NbS case | hundreds | Web | No licence found | Link-only; contact | NbS category |
| Ellen MacArthur Foundation | case study | hundreds | Web | No licence found | Link-only | Topic/sector |
| Lens.org | patents + scholarly | very large | Bulk needs plans | Terms not found | Skip | CPC |
| EPO OPS/DOCDB | patents | huge | Registration needed | UNVERIFIED | Skip | CPC |

### RED (cannot use for a CC BY dataset)
| Source | Why |
|---|---|
| AskNature (Biomimicry Institute) | ToS https://biomimicry.org/terms/: 7(f) "You may not copy, reproduce, republish, download, upload, post, transmit, distribute, modify" Materials without authorization; section 6 bars "any robot, spider, site search/retrieval application" and "data mine" and reproducing the "taxonomy"; 13(a) protected by copyright; footer "All Rights Reserved". No API/dump found. An old paper's CC BY-NC 3.0 claim is superseded. Same failure mode as Agroforestree. |
| Drawdown (bulk) | scraping banned |
| Biomimicry 3.8 / BIOKON / BioM / DANE / IDEA-INSPIRE | No open dataset or licence found by search (not proven non-existent) |

## 3. Recommended harvest stack
Principle: each record is our own structured facts (title, short rewritten description, organism taxon, function, sector, source URL/DOI, source licence); no verbatim prose from AMBER/RED sources.

1. OpenAlex (CC0): 164,868 biomimetic works as base; dedupe by DOI, require abstract, quality filter. Usable est. 20k-40k. Add a tighter NbS/eco-innovation query (my test query was noisy, 203k): est. 10k-30k. Use S3 snapshot, not API, for bulk.
2. CORDIS (CC BY 4.0 / CC0 metadata) keyword-filtered: est. 3k-8k.
3. PatentsView (CC BY 4.0) with CPC filters (Y02, B82Y, A01N etc.) plus bio-inspired keywords: est. 5k-15k. CPC gives a defensible sector map.
4. GBIF Backbone (CC BY 4.0) to link organisms to taxon IDs.
5. Climate-ADAPT (CC-BY): ~130 cases plus options, polite sitemap harvest; skip items flagged third-party.
6. Link-only layer (facts + URL): PANORAMA, WOCAT, Oppla/NetworkNature, EMF, WIPO GREEN, Urban Nature Atlas, EU Ecolabel (after licence check). Request written CC BY grants from IUCN, WOCAT, NATURVATION.
7. Sector: no existing dataset classifies biomimicry/eco solutions by NACE. Closest: Aguilar-Planet & Peralta 2024 (sector review, not NACE); AskNature Biomimicry Taxonomy is function-based and RED. Build own concordance: OpenAlex field/subfield and CPC -> NACE Rev.2 section.

Estimated total: 35k-90k before dedupe; defensible target 25k-50k. GREEN-only core (OpenAlex + CORDIS + PatentsView) ~30k-60k.

## 4. Confidence and gaps
- High: OpenAlex CC0, CORDIS CC BY 4.0 (editorial only), GBIF CC BY 4.0, PatentsView CC BY 4.0, Climate-ADAPT CC-BY, Wikidata CC0, AskNature RED, Drawdown RED.
- Medium: PANORAMA (search summary only), Crossref rate limits, Google Patents.
- Unverified: Europe PMC ToU, EU Ecolabel dataset licence, WOCAT data terms, Urban Nature Atlas, Oppla/NetworkNature, EMF, Lens, EPO, WIPO GREEN reuse, Semantic Scholar abstracts. Not found: BioM, DANE, IDEA-INSPIRE.
- Not covered: ClimateLaunchpad, ZDHC, EIP/Eco-innovation Observatory, LIFE projects DB, Catalogue of Life, Conservation Evidence (403), Zenodo/Dryad bioinspired datasets, BIOKON, Eurostat NACE reuse terms.
- Caveats: OpenAlex CC0 covers metadata; abstract text is publisher-owned in principle, so rewrite instead of copying, or restrict to cc-by OA works (28,577 of the biomimetic set). CORDIS deliverables and personal data excluded. OpenAlex test queries ran keyless with no email.
