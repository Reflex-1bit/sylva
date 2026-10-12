"""Build step 4, publish: grouped.jsonl -> gzipped JSON chunks, manifest.json, and the local full files.

Written (all deterministic: no clock, fixed key order, gzip mtime 0, no gzip filename):
  frontend/public/catalogue/<sector_id>/chunk-<NNNN>.json.gz   committed, at most CHUNK_SIZE records each
  frontend/public/catalogue/manifest.json                      committed
  data/nature/catalogue/build/manifest.json                    committed, byte-identical copy
  data/nature/catalogue/build/catalogue.json, catalogue.csv    local only (untracked, too big for the repo)

Order inside a sector (S3): area in taxonomy order (null last), kind project > case_study > patent > paper,
year descending (null last), then id. Before writing, only *.json.gz and manifest.json under the public
catalogue directory are deleted (and sector directories left empty), so stale chunks never linger.
The step fails (exit 1) when the public catalogue directory exceeds SIZE_BUDGET_BYTES, and when
validate.py --build fails on the full catalogue.json.

The compilation (selection, sorting, grouping) is CC-BY-4.0 by Sylva; each record keeps its own
source_licence and summary_licence.
"""

import csv
import gzip
import hashlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BUILD_DIR,
    CATALOGUE_DIR,
    REPO,
    load_groups,
    load_habitats,
    load_sectors,
    load_taxonomy,
)

from app.models.catalogue import CatalogueRecord  # noqa: E402

PUBLIC_DIR = REPO / "frontend" / "public" / "catalogue"
STAGE_DIR = BUILD_DIR / "stage"
SPOTCHECK_DIR = CATALOGUE_DIR / "spotcheck"
OPENALEX_STATE = CATALOGUE_DIR / "raw" / "openalex" / "state.json"
OPENALEX_TERMS = Path(__file__).resolve().parent / "openalex_terms.json"

CHUNK_SIZE = 2000
MB = 1024 * 1024
SIZE_BUDGET_BYTES = 60 * MB
SIZE_WARN_BYTES = 40 * MB
LOW_SAMPLE_N = 10
LICENCE = "CC-BY-4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
KIND_ORDER = {"project": 0, "case_study": 1, "patent": 2, "paper": 3}
DOWNLOAD_NOTE = "CSV files must keep the attribution line with them."

# Attribution lines per source (see docs/plans/research/sources.md); ASCII "-" for the dash.
SOURCE_INFO = {
    "openalex": ("OpenAlex", "CC0", "OpenAlex (CC0)", "https://openalex.org"),
    "cordis": ("CORDIS", "CC BY 4.0", "CORDIS (© European Union, CC BY 4.0)", "https://cordis.europa.eu"),
    "climate_adapt": ("Climate-ADAPT", "CC BY 4.0", "Climate-ADAPT (© EEA, CC BY 4.0)",
                      "https://climate-adapt.eea.europa.eu"),
    "patentsview": ("PatentsView", "CC BY 4.0", "PatentsView (USPTO, CC BY 4.0)", "https://patentsview.org"),
    "gbif": ("GBIF Backbone Taxonomy", "CC BY 4.0", "GBIF Backbone Taxonomy (CC BY 4.0)",
             "https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"),
}
SOURCE_ORDER = ("openalex", "cordis", "climate_adapt", "patentsview", "gbif")

# Copied from app/routers/nature.py:54 and :341-352 (_CSV_FORMULA_START, _csv_cell): importing that module
# pulls in FastAPI and the nature store, which a build script should not need.
_CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return "; ".join(_csv_cell(v) for v in value)
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_START):
        return "'" + value  # stop spreadsheets reading the cell as a formula
    return str(value)


def attribution_for(source_ids: list[str]) -> str:
    """Sylva plus each source present in the build, in SOURCE_ORDER."""
    lines = [SOURCE_INFO[s][2] for s in SOURCE_ORDER if s in source_ids]
    return "Sylva - Open Nature Catalogue, CC BY 4.0. Sources: " + "; ".join(lines)


def sort_key(area_order: dict[str, int], rec: CatalogueRecord) -> tuple:
    """S3 order inside a sector."""
    area = area_order.get(rec.area, len(area_order)) if rec.area else len(area_order)
    return (area, KIND_ORDER[rec.kind], rec.year is None, -(rec.year or 0), rec.id)


def gzip_bytes(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(data)
    return buf.getvalue()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def read_records(grouped: Path) -> list[CatalogueRecord]:
    """Validate every line as a CatalogueRecord; abort on the first invalid one, naming its id."""
    out = []
    with grouped.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                out.append(CatalogueRecord.model_validate_json(line))
            except ValueError as exc:
                try:
                    rid = json.loads(line).get("id", f"line {n}")
                except ValueError:
                    rid = f"line {n}"
                raise SystemExit(f"publish: invalid record {rid}: {exc}") from None
    return out


def clean_public_dir(public_dir: Path) -> None:
    """Delete only *.json.gz and manifest.json (and sector dirs left empty)."""
    if not public_dir.exists():
        return
    for p in sorted(public_dir.rglob("*.json.gz")):
        p.unlink()
    manifest = public_dir / "manifest.json"
    if manifest.exists():
        manifest.unlink()
    for d in sorted((p for p in public_dir.rglob("*") if p.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def spotcheck_block(spot_dir: Path) -> tuple[Optional[dict], dict]:
    """(manifest 'spotcheck' block or None, per-sector results dict). results.json is the published round."""
    main = _load_json(spot_dir / "results.json")
    if main is None:
        return None, {}
    rounds = []
    notes = {1: "before tuning", 2: "fresh sample after tuning; published figure"}
    for n in (1, 2):
        r = _load_json(spot_dir / f"results-round{n}.json")
        if r is not None:
            o = r["overall"]
            rounds.append({"round": n, "strict": o["precision"], "lenient": o["lenient_precision"],
                           "relevance": o["relevance"], "note": notes[n]})
    block = {"checked_by": main["checked_by"], "sample_size": main["sample_size"], "overall": main["overall"],
             "rounds": rounds}
    return block, main


def pending_gaps(state_path: Path = OPENALEX_STATE, terms_path: Path = OPENALEX_TERMS,
                 present_sources: tuple = ()) -> list[str]:
    """Plain-English known gaps; the OpenAlex line is derived from the harvest state, not hard-coded."""
    gaps = []
    terms = _load_json(terms_path)
    state = _load_json(state_path)
    if terms is not None and state is not None:
        included = [k for k in terms["keywords"] if k.get("include")]
        done = sum(1 for j in state.get("jobs", {}).values() if j.get("status") == "done")
        left = max(len(included) - done, 0)
        if left:
            gaps.append(f"OpenAlex nature-based-solution keywords not yet fully harvested: {done} of "
                        f"{len(included)} keyword jobs done, {left} pending (keyless daily budget)")
    if "patentsview" not in present_sources:
        gaps.append("PatentsView patents deferred (needs USPTO API key)")
    return gaps


def build_manifest(records: list[CatalogueRecord], by_sector: dict[str, list[CatalogueRecord]],
                   chunk_info: dict[str, list[dict]], spot_dir: Path, sectors, habitats, groups,
                   taxonomy: dict, attribution: str, source_ids: list[str], pending: list[str],
                   version: str, generated_on: str) -> dict:
    spot, main = spotcheck_block(spot_dir)
    per_sector_spot = (main or {}).get("sectors", {})
    below = set((main or {}).get("below_70", []))
    counts = Counter(r.source for r in records)
    counts_by_id = dict(counts)
    counts_by_id["gbif"] = sum(1 for r in records if r.organism and r.organism.gbif_key is not None)
    sec_entries = []
    for s in sectors:
        recs = by_sector.get(s.id, [])
        if not recs:
            continue
        sp = per_sector_spot.get(s.id)
        entry = {
            "id": s.id, "label_en": s.label_en, "label_es": s.label_es, "description": s.description,
            "count": len(recs), "chunks": chunk_info[s.id],
            "precision": sp["precision"] if sp else None,
            "lenient_precision": sp["lenient_precision"] if sp else None,
            "relevance": sp["relevance"] if sp else None,
            "n": sp["n"] if sp else None,
            "precision_warning": s.id in below,
            "low_sample": bool(sp and sp["n"] < LOW_SAMPLE_N),
        }
        sec_entries.append(entry)
    return {
        "version": version,
        "generated_on": generated_on,
        "licence": LICENCE,
        "licence_url": LICENCE_URL,
        "attribution": attribution,
        "sources": [{"id": sid, "name": SOURCE_INFO[sid][0], "count": counts_by_id.get(sid, 0),
                     "licence": SOURCE_INFO[sid][1], "attribution_line": SOURCE_INFO[sid][2],
                     "url": SOURCE_INFO[sid][3]} for sid in SOURCE_ORDER if sid in source_ids],
        "totals": {"records": len(records),
                   "with_summary": sum(1 for r in records if r.summary),
                   "with_organism": sum(1 for r in records if r.organism),
                   "with_group": sum(1 for r in records if r.group_ids)},
        "sectors": sec_entries,
        "spotcheck": spot,
        "areas": [{"id": a["id"], "label": a["label"]} for a in taxonomy["areas"]],
        "habitats": [{"id": h.id, "label": h.label_en} for h in habitats],
        "groups": [{"id": g.id, "name": g.name, "country": g.country, "donate_url": g.donate_url,
                    "every_org_slug": g.every_org_slug, "habitats": g.habitats,
                    "flagship_taxa": g.flagship_taxa} for g in groups],
        "pending": pending,
        "download_note": DOWNLOAD_NOTE,
    }


def iter_records_json(records: list[CatalogueRecord]) -> Iterator[str]:
    for r in records:
        yield dumps(r.model_dump(mode="json", exclude_none=True))


def write_catalogue_files(build_dir: Path, header: dict, records: list[CatalogueRecord]) -> None:
    """Local full files: catalogue.json (wrapper with all records) and catalogue.csv."""
    build_dir.mkdir(parents=True, exist_ok=True)
    head = dumps(header)[:-1]  # drop the closing brace
    with (build_dir / "catalogue.json").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(head + ',"records":[')
        for i, line in enumerate(iter_records_json(records)):
            fh.write(("," if i else "") + line)
        fh.write("]}\n")
    columns = list(CatalogueRecord.model_fields)
    with (build_dir / "catalogue.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for r in records:
            d = r.model_dump(mode="json")
            w.writerow([_csv_cell(d.get(c)) for c in columns])


_HARVESTED_RE = re.compile(r'"harvested_on":\s*"(\d{4}-\d{2}-\d{2})"')


def max_harvested_on(merged: Path) -> str:
    """The newest harvested_on in the merged stage file (CatalogueRecord has no such field). Not the clock,
    so the manifest stays deterministic."""
    if not merged.exists():
        raise SystemExit(f"{merged} is missing: publish needs it for generated_on")
    best = ""
    with merged.open(encoding="utf-8") as fh:
        for line in fh:
            m = _HARVESTED_RE.search(line)
            if m and m.group(1) > best:
                best = m.group(1)
    if not best:
        raise SystemExit(f"{merged}: no harvested_on found")
    return best


def dir_gz_bytes(public_dir: Path) -> int:
    return sum(p.stat().st_size for p in public_dir.rglob("*.json.gz"))


def publish_step(stage_dir: Path = STAGE_DIR, public_dir: Path = PUBLIC_DIR, build_dir: Path = BUILD_DIR,
                 spot_dir: Path = SPOTCHECK_DIR, data_dir: Path = CATALOGUE_DIR, validate: bool = True,
                 budget: int = SIZE_BUDGET_BYTES, chunk_size: int = CHUNK_SIZE,
                 openalex_state: Path = OPENALEX_STATE, log=print) -> tuple[int, dict]:
    """Return (exit code, summary). Writes chunks, manifests and the local full files."""
    grouped = stage_dir / "grouped.jsonl"
    if not grouped.exists():
        raise SystemExit(f"{grouped} is missing: run the groups step first")
    records = read_records(grouped)
    if not records:
        raise SystemExit("publish: no records")
    sectors = load_sectors(data_dir).sectors
    habitats = load_habitats(data_dir).habitats
    groups = load_groups(data_dir).groups
    taxonomy = load_taxonomy()
    area_order = {a["id"]: i for i, a in enumerate(taxonomy["areas"])}

    source_ids = [s for s in SOURCE_ORDER if s != "gbif" and any(r.source == s for r in records)]
    if any(r.organism and r.organism.gbif_key is not None for r in records):
        source_ids.append("gbif")
    attribution = attribution_for(source_ids)
    generated_on = version = max_harvested_on(stage_dir / "merged.jsonl")

    by_sector: dict[str, list[CatalogueRecord]] = {}
    for r in records:
        by_sector.setdefault(r.primary_sector, []).append(r)
    ordered: list[CatalogueRecord] = []
    for s in sectors:
        recs = sorted(by_sector.get(s.id, []), key=lambda r: sort_key(area_order, r))
        by_sector[s.id] = recs
        ordered += recs
    unknown = set(by_sector) - {s.id for s in sectors}
    if unknown:
        raise SystemExit(f"publish: records in unknown sectors {sorted(unknown)}")

    base = {"licence": LICENCE, "licence_url": LICENCE_URL, "attribution": attribution, "version": version,
            "db": "catalogue", "generated_on": generated_on}
    clean_public_dir(public_dir)
    chunk_info: dict[str, list[dict]] = {}
    largest = (0, "")
    for s in sectors:
        recs = by_sector[s.id]
        chunk_info[s.id] = []
        for n, start in enumerate(range(0, len(recs), chunk_size), 1):
            part = recs[start:start + chunk_size]
            head = dumps({**base, "sector": s.id, "chunk": n})[:-1]
            body = head + ',"records":[' + ",".join(iter_records_json(part)) + "]}"
            data = gzip_bytes(body.encode("utf-8"))
            rel = f"{s.id}/chunk-{n:04d}.json.gz"
            path = public_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            chunk_info[s.id].append({"path": rel, "count": len(part), "bytes": len(data),
                                     "sha256": hashlib.sha256(data).hexdigest()})
            if len(data) > largest[0]:
                largest = (len(data), rel)

    pending = pending_gaps(openalex_state, OPENALEX_TERMS, tuple(source_ids))
    manifest = build_manifest(records, by_sector, chunk_info, spot_dir, sectors, habitats, groups, taxonomy,
                              attribution, source_ids, pending, version, generated_on)
    text = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    public_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    (public_dir / "manifest.json").write_bytes(text.encode("utf-8"))
    (build_dir / "manifest.json").write_bytes(text.encode("utf-8"))

    write_catalogue_files(build_dir, {**base, "count": len(ordered)}, ordered)

    total = dir_gz_bytes(public_dir)
    n_chunks = {s: len(c) for s, c in chunk_info.items() if c}
    summary = {"total_gz_bytes": total, "total_gz_mb": round(total / MB, 2), "chunks_per_sector": n_chunks,
               "largest_chunk": {"path": largest[1], "bytes": largest[0]}, "totals": manifest["totals"],
               "size_budget_bytes": budget}
    log(f"publish: {sum(n_chunks.values())} chunks, {total / MB:.1f} MB gz; largest {largest[1]} "
        f"({largest[0] / MB:.2f} MB)")
    report_path = stage_dir / "report.json"
    if report_path.exists():
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        rep["publish"] = summary
        report_path.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if total > budget:
        log(f"FAIL: {total / MB:.1f} MB of chunks exceeds the {budget / MB:.0f} MB budget")
        return 1, summary
    if total > SIZE_WARN_BYTES:
        log(f"WARNING: {total / MB:.1f} MB of chunks is above {SIZE_WARN_BYTES / MB:.0f} MB")
    if validate:
        import validate as validate_mod

        code = validate_mod.main(["--data-dir", str(data_dir), "--build", str(build_dir)])
        if code:
            log("FAIL: validate.py --build failed")
            return code, summary
    return 0, summary
