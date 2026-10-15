"""
Sylva - Nature arm links: which sectors use a library record, and sector gaps.

Only servable library records are ever surfaced. Map `library_links` can point
at quarantined records; those are ignored here.
"""

import re

from app.models.nature import LibraryRecord, MapRecord
from app.services.nature.store import NatureStore
from app.services.nature.text import normalise

_GRADE_ORDER = {"strong": 0, "moderate": 1, "weak": 2, "contested": 3}
_MIN_GENUS_LEN = 4


def _name_patterns(rec: LibraryRecord) -> list[re.Pattern]:
    """Word-boundary patterns for the organism's canonical name and genus."""
    if not rec.organism:
        return []
    canonical = normalise(rec.organism.scientific_name).strip()
    if not canonical:
        return []
    names = {canonical}
    genus = canonical.split()[0]
    if len(genus) >= _MIN_GENUS_LEN:
        names.add(genus)
    return [re.compile(r"\b" + re.escape(n) + r"\b") for n in sorted(names)]


def _uses(rec: LibraryRecord, m: MapRecord, patterns: list[re.Pattern]) -> bool:
    if rec.id in m.library_links:
        return True
    title = normalise(m.title)
    return any(p.search(title) for p in patterns)


def sectors_for_record(rec: LibraryRecord, store: NatureStore) -> dict[str, list[str]]:
    """{using, candidate} sector ids for a record. Empty for non-servable records."""
    if not store.is_servable(rec):
        return {"using": [], "candidate": []}
    patterns = _name_patterns(rec)
    funcs = set(rec.functions)
    using: set[str] = set()
    overlapping: set[str] = set()
    for m in store.industry_map():
        if _uses(rec, m, patterns):
            using.add(m.sector)
        if funcs & set(m.problem_functions):
            overlapping.add(m.sector)
    return {"using": sorted(using), "candidate": sorted(overlapping - using)}


def sector_gaps(sector_id: str, store: NatureStore, limit: int = 10) -> dict:
    """Library records a sector's classified papers ask for but the sector does not use.

    Computed from papers with non-empty problem_functions only; the number of
    unclassified papers is returned so callers can label the result.
    """
    sector_map = [m for m in store.industry_map() if m.sector == sector_id]
    papers = [m for m in sector_map if m.type == "paper"]
    classified = [m for m in papers if m.problem_functions]
    demand: dict[str, int] = {}
    for m in classified:
        for f in m.problem_functions:
            demand[f] = demand.get(f, 0) + 1

    gaps = []
    for rec in store.library(servable_only=True):
        overlap = sorted(set(rec.functions) & set(demand))
        if not overlap:
            continue
        patterns = _name_patterns(rec)
        if any(_uses(rec, m, patterns) for m in sector_map):
            continue
        gaps.append(
            {
                "record_id": rec.id,
                "title": rec.title,
                "functions_overlap": overlap,
                "weight": sum(demand[f] for f in overlap),
                "evidence_grade": store.evidence_grade(rec),
            }
        )
    gaps.sort(key=lambda g: (_GRADE_ORDER[g["evidence_grade"]], -g["weight"], g["record_id"]))
    return {
        "sector_id": sector_id,
        "classified_papers": len(classified),
        "unclassified_papers": len(papers) - len(classified),
        "gaps": gaps[:limit],
    }
