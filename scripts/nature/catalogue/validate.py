"""Validate the Open Nature Catalogue reference files (and optionally a build). Exit 1 on any error.

Usage (from repo root):
    python scripts/nature/catalogue/validate.py [--data-dir PATH] [--build DIR]

--data-dir  catalogue reference dir (default data/nature/catalogue)
--build     directory holding catalogue.json (the export wrapper
            {licence, licence_url, attribution, version, db, records})
"""

import argparse
import json
import sys
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

    conc = loaded["concordance"]
    known = set(sector_ids)
    for table in ("cpc", "openalex_subfield", "euroscivoc", "climate_adapt_sector"):
        for row in getattr(conc, table):
            if row.sector not in known:
                label = getattr(row, "prefix", None) or getattr(row, "name", None) or row.term
                problems.append(f"concordance.json {table} '{label}': unknown sector '{row.sector}'")

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
    return problems, loaded


def check_build(build_dir: Path, loaded: dict) -> list[str]:
    """Validate build_dir/catalogue.json records against the reference files and taxonomy."""
    path = build_dir / "catalogue.json"
    try:
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
