"""
Sylva - Nature arm matcher: function parsing and deterministic scoring.

score = evidence (0-30) + provenance (0-25) + fit (0-20)
        + manufacturability (0-15) + regional (0-10)

Ranking is published and never touched by an LLM.
"""

from app.models.nature import LibraryHit, LibraryRecord, MapRecord
from app.services.nature.store import NatureStore
from app.services.nature.text import normalise, tokenize

EVIDENCE_POINTS = {"strong": 30, "moderate": 20, "weak": 10, "contested": 0}
PROVENANCE_POINTS = {"expert_validated": 25, "ai_extracted": 10, "disputed": 0}
FIT_MAX = 20.0
MANUFACTURABILITY_POINTS = 15
RESERVE_POINTS = 10
REGION_POINTS = 5


# Generic keywords that never assign a function on their own (mirrors Ruling 3-1 in the
# OpenAlex harvester). "in water" is one: tokenising drops "in", leaving the bare word
# "water", which made every water-related challenge parse make-at-ambient-conditions.
WEAK_KEYWORDS = frozenset(
    """
    packaging package container embalaje envase wastewater network red joint joining union
    detergent detergente strength membrane membrana plantilla templating rigid rigidity sliding
    bearing lift wing ala motor cuenca seto mixing modular dirt residue wood cork mold mould
    oxidation cellular flight crack deposit scaling erosion lifetime monitoring reserve
    """.split()
) | {"aguas residuales", "in water"}


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def parse_functions(text: str, taxonomy: dict) -> list[str]:
    """Function ids whose EN or ES keywords occur in the text (accent-folded,
    stopword-free, plural-folded token phrases). Returned in taxonomy order."""
    tokens = tokenize(text)
    found = []
    for fn in taxonomy.get("functions", []):
        keywords = [*fn.get("keywords_en", []), *fn.get("keywords_es", [])]
        strong = [k for k in keywords if normalise(k).strip() not in WEAK_KEYWORDS]
        if any(_contains(tokens, tokenize(k)) for k in strong):
            found.append(fn["id"])
    return found


def _regional_points(rec: LibraryRecord) -> int:
    if rec.source_region is None:
        return 0
    return RESERVE_POINTS if rec.source_region.reserve_id else REGION_POINTS


def score_library(
    hits: list[tuple[LibraryRecord, float]],
    parsed_functions: list[str],
    store: NatureStore,
    map_records: list[MapRecord],
    strict_functions: bool = False,
) -> list[LibraryHit]:
    """Score retrieved library records. Non-servable records are dropped.

    With strict_functions and at least one parsed function, records with no
    function overlap are removed before the retrieval score is min-max
    normalised over the remaining hit list (top = 1.0, bottom = 0.0, a single
    hit = 1.0). Ruling 5-1: when functions were parsed, hits with function overlap
    (tier 1) sort before those without (tier 2); within a tier by score descending,
    then id. Scores are unchanged; `breakdown["tier"]` publishes the tier.
    """
    wanted = set(parsed_functions)
    kept = [(r, s) for r, s in hits if store.is_servable(r)]
    if strict_functions and wanted:
        kept = [(r, s) for r, s in kept if wanted & set(r.functions)]
    if not kept:
        return []

    linked = {link for m in map_records for link in m.library_links}
    raws = [s for _, s in kept]
    lo, hi = min(raws), max(raws)

    out = []
    for rec, raw in kept:
        norm = (raw - lo) / (hi - lo) if hi > lo else 1.0
        ratio = len(wanted & set(rec.functions)) / len(wanted) if wanted else 1.0
        grade = store.evidence_grade(rec)
        parts = {
            "evidence": float(EVIDENCE_POINTS[grade]),
            "provenance": float(PROVENANCE_POINTS[rec.provenance.status]),
            "fit": FIT_MAX * norm * (0.5 + 0.5 * ratio),
            "manufacturability": float(
                MANUFACTURABILITY_POINTS if (rec.known_products or rec.id in linked) else 0
            ),
            "regional": float(_regional_points(rec)),
        }
        breakdown = {
            **{k: round(v, 4) for k, v in parts.items()},
            "tier": float(1 if (not wanted or ratio > 0) else 2),
            "retrieval_raw": round(raw, 6),
            "retrieval_normalised": round(norm, 6),
            "function_overlap_ratio": round(ratio, 6),
        }
        out.append(
            LibraryHit(
                record=rec,
                score=round(sum(parts.values()), 4),
                breakdown=breakdown,
                evidence_grade=grade,
            )
        )
    out.sort(key=lambda h: (h.breakdown["tier"], -h.score, h.record.id))
    return out
