"""
Open Nature Catalogue - CORDIS harvester (H2020, FP7, Horizon Europe bulk CSV zips).

Subcommands:
  download   fetch the three project zips into data/nature/catalogue/raw/cordis/ (skip if present by size)
  normalise  parse the zips offline -> raw/cordis/records.jsonl (+ euroscivoc_terms.txt when all zips parsed)
  harvest    download, then normalise
  status     zips present, records written

Columns are mapped by header NAME (FP7 orders them differently and has no `keywords`).
Only organisation `name`, `country` and `role` are read from organization.csv: contact,
address and URL columns are never read. Records are CC BY 4.0 (CORDIS open data).
"""

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RAW_DIR, today, write_jsonl  # noqa: E402
from scrub import scrub_contacts  # noqa: E402
from scope import ScopeMatcher, cut_summary, load_scope_terms  # noqa: E402

from app.models.catalogue import RawRecord, SourceCodes  # noqa: E402

HERE = Path(__file__).resolve().parent
CORDIS_DIR = RAW_DIR / "cordis"
RECORDS_PATH = CORDIS_DIR / "records.jsonl"
TERMS_PATH = HERE / "euroscivoc_terms.txt"

USER_AGENT = "SylvaNatureCatalogue/0.1"
BASE = "https://cordis.europa.eu/data/"
PROGRAMMES = {
    "h2020": "cordis-h2020projects-csv.zip",
    "fp7": "cordis-fp7projects-csv.zip",
    "horizon": "cordis-HORIZONprojects-csv.zip",
}
LICENCE = "CC-BY-4.0"

# The only organisation columns ever read (legal-entity data; no contact columns).
ORG_COLUMNS = ("projectID", "name", "country", "role")
COUNTRY_FIX = {"EL": "GR", "UK": "GB"}

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


# ── download ──────────────────────────────────────────────────────────────────


def download(dest_dir: Path = CORDIS_DIR, programmes: Optional[list[str]] = None, http=None) -> dict[str, str]:
    """Download missing zips; return {programme: 'downloaded'|'present'}.

    `http` is an httpx-like module (head, stream, TransportError); injected in tests.
    """
    if http is None:
        import httpx as http
    httpx = http

    dest_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    headers = {"User-Agent": USER_AGENT}
    for prog in programmes or list(PROGRAMMES):
        name = PROGRAMMES[prog]
        url = BASE + name
        path = dest_dir / name
        remote = None
        try:
            head = httpx.head(url, headers=headers, timeout=30.0, follow_redirects=True)
            if head.status_code == 200 and head.headers.get("content-length", "").isdigit():
                remote = int(head.headers["content-length"])
        except httpx.TransportError:
            pass
        if path.exists() and (remote is None or path.stat().st_size == remote):
            out[prog] = "present"
            continue
        part = path.with_suffix(".part")
        with httpx.stream("GET", url, headers=headers, timeout=120.0, follow_redirects=True) as resp:
            resp.raise_for_status()
            with part.open("wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
        part.replace(path)
        out[prog] = "downloaded"
    return out


# ── parsing ───────────────────────────────────────────────────────────────────


def read_csv(zf: zipfile.ZipFile, member: str, wanted: Optional[Iterable[str]] = None,
             required: Iterable[str] = ()) -> Iterator[dict]:
    """Stream a `;`-separated, `"`-quoted CSV member as dicts keyed by header name.

    If `wanted` is given only those columns are materialised; every other column is
    skipped without being read into the row. A missing `required` column raises ValueError.
    """
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.reader(text, delimiter=";", quotechar='"')
        header = next(reader, None)
        if header is None:
            return
        header = [h.lstrip("﻿").strip() for h in header]
        names = list(wanted) if wanted is not None else header
        idx = {n: header.index(n) for n in names if n in header}
        missing = [n for n in required if n not in idx]
        if missing:
            raise ValueError(f"{member}: missing required column(s) {missing}; header is {header}")
        for row in reader:
            if not row:
                continue
            yield {n: (row[i] if i < len(row) else "") for n, i in idx.items()}


def split_keywords(value: str) -> list[str]:
    out = []
    for part in (value or "").replace(";", ",").split(","):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out


def bare_doi(value: str) -> Optional[str]:
    v = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if v.lower().startswith(prefix):
            v = v[len(prefix):]
    return v if v.startswith("10.") and " " not in v else None


def fix_country(code: str) -> Optional[str]:
    c = (code or "").strip().upper()
    c = COUNTRY_FIX.get(c, c)
    return c if len(c) == 2 and c.isalpha() else None


def scan_projects(zf: zipfile.ZipFile, matcher: ScopeMatcher) -> tuple[dict[str, dict], int]:
    """Return ({project id: row + 'scope' list} for in-scope projects, projects scanned)."""
    kept: dict[str, dict] = {}
    scanned = 0
    cols = ("id", "title", "startDate", "objective", "grantDoi", "keywords")
    for row in read_csv(zf, "project.csv", cols, required=("id", "title", "objective")):
        scanned += 1
        pid = (row.get("id") or "").strip()
        if not pid.isdigit() or not (row.get("title") or "").strip():
            continue
        hits = in_scope(matcher, row.get("title"), row.get("objective"), row.get("keywords"))
        if hits:
            row["scope"] = hits
            kept[pid] = row
    return kept, scanned


COMPUTATIONAL_RE = re.compile(
    r"\b(algorithms?|optimi[sz]ation|metaheuristics?|swarm intelligence|evolutionary computation|neural networks?)\b", re.I)
PHYSICAL_RE = re.compile(
    r"\b(material|surface|structure|coating|membrane|tissue|device|building|ecosystem|wetland|robot)", re.I)


def in_scope(matcher: ScopeMatcher, title, objective, keywords) -> list[str]:
    """Scope terms that justify keeping a project, or [] (rulings S4 and fix round 1).

    Keep when a term is in the title or keywords, or the objective has at least 2 term
    occurrences. Drop the computational sense (algorithm/optimisation words with none of the
    physical words) even then.
    """
    strong = matcher.matches(title, keywords)
    obj_counts = matcher.counts(objective)
    if not strong and sum(obj_counts.values()) < 2:
        return []
    text = f"{title or ''} {objective or ''}"
    if COMPUTATIONAL_RE.search(text) and not PHYSICAL_RE.search(text):
        return []
    return list(dict.fromkeys(strong + list(obj_counts)))


def load_euroscivoc(zf: zipfile.ZipFile, kept: set[str]) -> tuple[dict[str, list[str]], set[str]]:
    """Return (kept project -> codes, every distinct title and path segment in the file)."""
    per_project: dict[str, list[str]] = {}
    distinct: set[str] = set()
    for row in read_csv(zf, "euroSciVoc.csv", ("projectID", "euroSciVocPath", "euroSciVocTitle"),
                       required=("projectID", "euroSciVocTitle")):
        title = (row.get("euroSciVocTitle") or "").strip()
        segments = [s.strip() for s in (row.get("euroSciVocPath") or "").split("/") if s.strip()]
        terms = ([title] if title else []) + segments
        distinct.update(terms)
        pid = (row.get("projectID") or "").strip()
        if pid in kept:
            bucket = per_project.setdefault(pid, [])
            for t in terms:
                if t not in bucket:
                    bucket.append(t)
    return per_project, distinct


def load_organisations(zf: zipfile.ZipFile, kept: set[str]) -> dict[str, dict]:
    """Return {project: {'orgs': [names], 'countries': [ISO2]}} with the coordinator first."""
    rows: dict[str, list[tuple[int, str, Optional[str]]]] = {}
    for n, row in enumerate(read_csv(zf, "organization.csv", ORG_COLUMNS, required=ORG_COLUMNS)):
        pid = (row.get("projectID") or "").strip()
        if pid not in kept:
            continue
        coordinator = (row.get("role") or "").strip().lower() == "coordinator"
        rows.setdefault(pid, []).append(
            (0 if coordinator else 1, (row.get("name") or "").strip(), fix_country(row.get("country") or ""))
        )
    out = {}
    for pid, items in rows.items():
        items.sort(key=lambda t: t[0])  # stable: coordinator first, file order otherwise
        orgs: list[str] = []
        countries: list[str] = []
        for _, name, country in items:
            if name and name not in orgs:
                orgs.append(name)
            if country and country not in countries:
                countries.append(country)
        out[pid] = {"orgs": orgs[:10], "countries": countries}
    return out


def build_record(row: dict, euroscivoc: list[str], org: Optional[dict], harvested_on: str) -> RawRecord:
    pid = row["id"].strip()
    objective = cut_summary(scrub_contacts(row.get("objective") or ""))
    year = None
    start = (row.get("startDate") or "")[:4]
    if start.isdigit():
        year = int(start)
    keywords = split_keywords(row.get("keywords") or "") + [f"scope:{t}" for t in row["scope"]]
    return RawRecord(
        id=f"cd-{pid}",
        source="cordis",
        source_id=pid,
        kind="project",
        title=" ".join(row["title"].split()),
        summary=objective or None,
        summary_licence=LICENCE if objective else None,
        source_licence=LICENCE,
        url=f"https://cordis.europa.eu/project/id/{pid}",
        doi=bare_doi(row.get("grantDoi") or ""),
        year=year,
        countries=(org or {}).get("countries", []),
        organisations=(org or {}).get("orgs", []),
        source_codes=SourceCodes(euroscivoc=euroscivoc),
        keywords=keywords,
        harvested_on=harvested_on,
    )


def process_zip(path: Path, matcher: ScopeMatcher, harvested_on: str) -> tuple[list[RawRecord], int, set[str]]:
    with zipfile.ZipFile(path) as zf:
        kept, scanned = scan_projects(zf, matcher)
        ids = set(kept)
        codes, distinct = load_euroscivoc(zf, ids)
        orgs = load_organisations(zf, ids)
    records = [build_record(kept[p], codes.get(p, []), orgs.get(p), harvested_on) for p in kept]
    return records, scanned, distinct


def normalise(src_dir: Path = CORDIS_DIR, out_path: Path = RECORDS_PATH, terms_path: Optional[Path] = TERMS_PATH) -> dict:
    matcher = ScopeMatcher(load_scope_terms())
    stamp = today()
    all_records: list[RawRecord] = []
    stats: dict = {"scanned": {}, "kept": {}, "with_summary": 0, "euroscivoc": {}}
    distinct: set[str] = set()
    parsed_all = True
    for prog, name in PROGRAMMES.items():
        path = src_dir / name
        if not path.exists():
            parsed_all = False
            continue
        recs, scanned, terms = process_zip(path, matcher, stamp)
        stats["scanned"][prog] = scanned
        stats["kept"][prog] = len(recs)
        all_records += recs
        distinct |= terms
    seen: set[str] = set()
    unique = []
    for r in all_records:
        if r.id not in seen:
            seen.add(r.id)
            unique.append(r)
    stats["total"] = write_jsonl(out_path, unique)
    stats["with_summary"] = sum(1 for r in unique if r.summary)
    counter: dict[str, int] = {}
    for r in unique:
        for t in r.source_codes.euroscivoc:
            counter[t] = counter.get(t, 0) + 1
    stats["euroscivoc"] = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    if parsed_all and terms_path is not None and distinct:
        terms_path.write_text("\n".join(sorted(distinct, key=str.casefold)) + "\n", encoding="utf-8", newline="\n")
    stats["distinct_terms"] = len(distinct)
    return stats


def status() -> None:
    for prog, name in PROGRAMMES.items():
        p = CORDIS_DIR / name
        print(f"{prog}: {'%d bytes' % p.stat().st_size if p.exists() else 'missing'}")
    if RECORDS_PATH.exists():
        n = sum(1 for _ in RECORDS_PATH.open(encoding="utf-8"))
        print(f"records.jsonl: {n}")
    else:
        print("records.jsonl: not written")


def print_stats(stats: dict) -> None:
    for prog in stats["scanned"]:
        print(f"{prog}: scanned {stats['scanned'][prog]}, kept {stats['kept'][prog]}")
    print(f"total kept: {stats['total']} (with summary: {stats['with_summary']})")
    print(f"distinct EuroSciVoc terms in the data: {stats['distinct_terms']}")
    for term, n in stats["euroscivoc"][:15]:
        print(f"  {n:5d}  {term}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["download", "harvest", "normalise", "status"])
    args = parser.parse_args(argv)
    if args.command in ("download", "harvest"):
        for prog, state in download().items():
            print(f"{prog}: {state}")
    if args.command in ("normalise", "harvest"):
        print_stats(normalise())
    if args.command == "status":
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
