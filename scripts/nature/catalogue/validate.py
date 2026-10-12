"""Validate the Open Nature Catalogue reference files (and optionally a build). Exit 1 on any error.

Usage (from repo root):
    python scripts/nature/catalogue/validate.py [--data-dir PATH] [--build DIR]

--data-dir  catalogue reference dir (default data/nature/catalogue)
--build     directory holding catalogue.json (the export wrapper
            {licence, licence_url, attribution, version, db, records}), or, when that is
            absent, grouped.jsonl (one record per line, as build.py groups writes it).
            Every record group_ids entry must exist in groups.json.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CATALOGUE_DIR,
    load_concordance,
    load_groups,
    load_habitats,
    load_sectors,
    load_taxonomy,
)

from app.models.catalogue import CatalogueRecord  # noqa: E402


MIN_GROUPS_PER_HABITAT = 2


def check_reference(data_dir: Path) -> tuple[list[str], dict]:
    """Return (problems, loaded) for the four reference files."""
    problems: list[str] = []
    loaded: dict = {}
    for name, loader in (("sectors", load_sectors), ("habitats", load_habitats),
                         ("concordance", load_concordance), ("groups", load_groups)):
        try:
            loaded[name] = loader(data_dir)
        except (OSError, ValueError) as exc:
            problems.append(f"{name}.json: {exc}")
    if problems:
        return problems, loaded

    tax_sectors = [s["id"] for s in load_taxonomy()["sectors"]]
    sector_ids = [s.id for s in loaded["sectors"].sectors]
    if len(set(sector_ids)) != len(sector_ids):
        problems.append("sectors.json: duplicate sector id")
    for sid in tax_sectors:
        if sid not in sector_ids:
            problems.append(f"sectors.json: taxonomy sector '{sid}' is missing")
    if "other" not in sector_ids:
        problems.append("sectors.json: sector 'other' is missing")
    for s in loaded["sectors"].sectors:
        if s.candidate and s.min_records <= 0:
            problems.append(f"sectors.json: candidate '{s.id}' needs min_records > 0")
        if not (s.description or "").strip():
            problems.append(f"sectors.json: sector '{s.id}' needs a description")

    conc = loaded["concordance"]
    known = set(sector_ids)
    for table in ("cpc", "openalex_subfield", "euroscivoc", "climate_adapt_sector"):
        for row in getattr(conc, table):
            if row.sector not in known:
                label = getattr(row, "prefix", None) or getattr(row, "name", None) or row.term
                problems.append(f"concordance.json {table} '{label}': unknown sector '{row.sector}'")

    # Concordance rows must mirror the sectors' own lists, with unique keys, no key in two sectors.
    by_id = {s.id: s for s in loaded["sectors"].sectors}
    tables = (("cpc", "prefix", "cpc_prefixes"), ("openalex_subfield", "name", "openalex_subfields"))
    for table, key, field in tables:
        rows = getattr(conc, table)
        keys = [getattr(r, key) for r in rows]
        for k in sorted({k for k in keys if keys.count(k) > 1}):
            problems.append(f"concordance.json {table}: duplicate key '{k}'")
        owners: dict[str, list[str]] = {}
        for s in loaded["sectors"].sectors:
            for k in getattr(s, field):
                owners.setdefault(k, []).append(s.id)
        for k, ids in owners.items():
            if len(ids) > 1:
                problems.append(f"sectors.json {field}: '{k}' is in several sectors {ids}")
        for r in rows:
            sec = by_id.get(r.sector)
            if sec is not None and getattr(r, key) not in getattr(sec, field):
                problems.append(f"concordance.json {table} '{getattr(r, key)}': not in sector '{r.sector}' {field}")
        listed = set(keys)
        for k, ids in owners.items():
            if k not in listed:
                problems.append(f"concordance.json {table}: '{k}' of sector '{ids[0]}' has no row")
    for table in ("euroscivoc", "climate_adapt_sector"):
        terms = [r.term for r in getattr(conc, table)]
        for k in sorted({k for k in terms if terms.count(k) > 1}):
            problems.append(f"concordance.json {table}: duplicate term '{k}'")

    # EuroSciVoc terms must be real titles/path segments from the CORDIS data (committed list).
    terms_file = Path(__file__).resolve().parent / "euroscivoc_terms.txt"
    if terms_file.exists():
        real = set(terms_file.read_text(encoding="utf-8").splitlines())
        for r in conc.euroscivoc:
            if r.term not in real:
                problems.append(f"concordance.json euroscivoc '{r.term}': not a EuroSciVoc term in euroscivoc_terms.txt")
    else:
        problems.append(f"missing {terms_file.name}")

    # Climate-ADAPT sector terms must be spelled as in the harvested records (committed distinct list).
    ca_file = Path(__file__).resolve().parent / "climate_adapt_sectors.txt"
    if ca_file.exists():
        real = set(ca_file.read_text(encoding="utf-8").splitlines())
        for r in conc.climate_adapt_sector:
            if r.term not in real:
                problems.append(f"concordance.json climate_adapt_sector '{r.term}': not a Climate-ADAPT sector in {ca_file.name}")
    else:
        problems.append(f"missing {ca_file.name}")

    # OpenAlex subfield names must exist in the checked-in snapshot of the live /subfields listing.
    snapshot = Path(__file__).resolve().parent / "openalex_subfields.txt"
    if snapshot.exists():
        valid = set(snapshot.read_text(encoding="utf-8").splitlines())
        for s in loaded["sectors"].sectors:
            for n in s.openalex_subfields:
                if n not in valid:
                    problems.append(f"sectors.json '{s.id}': unknown OpenAlex subfield '{n}'")
    else:
        problems.append(f"missing {snapshot.name}")

    hab_ids = [h.id for h in loaded["habitats"].habitats]
    if len(set(hab_ids)) != len(hab_ids):
        problems.append("habitats.json: duplicate habitat id")

    group_ids = [g.id for g in loaded["groups"].groups]
    if len(set(group_ids)) != len(group_ids):
        problems.append("groups.json: duplicate group id")
    for g in loaded["groups"].groups:
        for h in g.habitats:
            if h not in hab_ids:
                problems.append(f"groups.json '{g.id}': unknown habitat '{h}'")
        for field in ("donate_url", "source_url"):
            if not getattr(g, field).startswith("https://"):
                problems.append(f"groups.json '{g.id}': {field} must be https")
        if not isinstance(g.checked_on, date):
            problems.append(f"groups.json '{g.id}': checked_on must be a date")
    for h in hab_ids:
        n = sum(1 for g in loaded["groups"].groups if h in g.habitats)
        if n < MIN_GROUPS_PER_HABITAT:
            problems.append(f"groups.json: habitat '{h}' has {n} group(s), needs at least {MIN_GROUPS_PER_HABITAT}")
    return problems, loaded


def check_build(build_dir: Path, loaded: dict) -> list[str]:
    """Validate build_dir/catalogue.json records against the reference files and taxonomy."""
    path = build_dir / "catalogue.json"
    try:
        if not path.exists() and (build_dir / "grouped.jsonl").exists():
            path = build_dir / "grouped.jsonl"
            with path.open(encoding="utf-8") as fh:
                records = [json.loads(line) for line in fh if line.strip()]
        else:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            records = wrapper["records"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"{path}: {exc}"]
    if not isinstance(records, list):
        return [f"{path}: 'records' must be a list"]

    tax = load_taxonomy()
    areas = {a["id"] for a in tax["areas"]}
    functions = {f["id"] for f in tax["functions"]}
    sectors = {s.id for s in loaded["sectors"].sectors}
    habitats = {h.id for h in loaded["habitats"].habitats}
    groups = {g.id for g in loaded["groups"].groups}

    problems: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(records):
        where = f"records[{i}]"
        try:
            rec = CatalogueRecord.model_validate(raw)
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
            continue
        where = f"{rec.id}"
        if rec.id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(rec.id)
        for sid in [rec.primary_sector, *rec.sector_tags]:
            if sid not in sectors:
                problems.append(f"{where}: unknown sector '{sid}'")
        if rec.habitat_id is not None and rec.habitat_id not in habitats:
            problems.append(f"{where}: unknown habitat '{rec.habitat_id}'")
        if rec.area is not None and rec.area not in areas:
            problems.append(f"{where}: unknown area '{rec.area}'")
        for fn in rec.functions:
            if fn not in functions:
                problems.append(f"{where}: unknown function '{fn}'")
        for gid in rec.group_ids:
            if gid not in groups:
                problems.append(f"{where}: unknown group '{gid}'")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=CATALOGUE_DIR)
    parser.add_argument("--build", type=Path, default=None)
    args = parser.parse_args(argv)

    problems, loaded = check_reference(args.data_dir)
    if args.build is not None and not problems:
        problems += check_build(args.build, loaded)

    if problems:
        for p in problems:
            print(f"INVALID: {p}", file=sys.stderr)
        return 1
    if loaded:
        print(f"sectors: {len(loaded['sectors'].sectors)}")
        print(f"habitats: {len(loaded['habitats'].habitats)}")
        print(f"groups: {len(loaded['groups'].groups)}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
