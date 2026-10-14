# Sylva-wild search index

A local, key-free search index over every record of the Open Nature Catalogue
(`data/nature/catalogue/`), for the Sylva-wild page: a user describes their sector and
what they want to build, and gets matching studies with links and, where the record
names a habitat or flagship organism, donation links to groups that protect it.

This build covers **99,309 of 99,309 records** (catalogue of 2026-10-11, built 2026-10-14).

## How it works

- **Keyword search (BM25)** over title (counted twice), organism, abstract, function
  and design-area words. Stored as a sparse matrix of precomputed weights
  (`bm25.npz`, 83,380 terms).
- **Meaning search (dense vectors)** from `minishlab/potion-retrieval-32M`, a static
  embedding model run locally with fastembed (no API key). It reads the title, the
  organism and the first 1,000 characters of the abstract. Vectors are stored as int8
  with one global scale (`vectors.npy`, 512 dimensions).
- **Fusion:** reciprocal-rank fusion (k=60) of the top 200 of each list, as in the
  nature library search (`app/services/nature/search.py`).
- **Sector** is a soft boost (x1.15 for the primary sector, x1.05 for a tagged one),
  never a filter, because the catalogue's sector labels are about 63% precise.

`BAAI/bge-small-en-v1.5` is the stronger model and can be chosen with `--model`, but
on the build laptop's CPU it ran at 5 to 35 records a second (about 5 hours for the
catalogue); potion ran at about 1,600 a second (2 minutes).

## Build and query

```
pip install -r requirements-wild.txt
python -m scripts.nature.wild.build_index            # needs data/nature/catalogue/build/catalogue.json
python -m scripts.nature.wild.query "reduce drag on a ship hull" --sector aerospace-transport
```

The build writes vectors in parts of 5,000 records, so an interrupted run resumes.
`--limit N` builds a trial index of the first N records. The model downloads once into
`data/nature/wild/.model_cache/`; the index and the cache are gitignored.

| File | Size | Content |
|---|---|---|
| `index/vectors.npy` | 48.5 MB | int8 dense vectors, one row per record |
| `index/bm25.npz` | 10.8 MB | BM25 weights, records x terms |
| `index/vocab.json` | 1.0 MB | the terms, in column order |
| `index/docs.json.gz` | 14.2 MB | per record: id, title, url, doi, year, kind, source, sectors, area, functions, organism, habitat, group ids, summary and its licence |
| `index/meta.json` | | model, dimensions, count, scale, text hash, catalogue date, build date |

## Measured on this build

- Query time: about 0.3 s on the laptop, after loading. Loading takes about 2 s plus the
  fastembed import, which took 21 s on the build laptop (onnxruntime's native module).
- int8 against float32 vectors: 98.7% of the dense top 20 is the same (10,000-record sample,
  12 queries; worst query 95%).
- 12 test problems, one per sector: most of the top 5 results were on topic by eye. A
  short, specific query works best ("anti-icing coating for wind turbine blades" finds
  the icing project first; "coating that stops ice forming on wind turbine blades" drifts
  to wind-turbine papers in general), so the page should turn the user's text into a
  short problem statement before searching.

## Known limits

- Only 23% of the top results in the test carried an abstract; the rest are a title and
  facts, so an answer built on them must stay close to the title.
- Only 22% of the top results had a donation group, and the groups are matched to the
  record's habitat by rules, so some look loose (for example soil groups for an ant study).
- English model: Spanish or Portuguese text should be translated to English first.
- The owner skim of the catalogue's sector labels is still pending.
