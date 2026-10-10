"""Harvest the industry R&D map (v0) from OpenAlex (CC0).

For each taxonomy sector, search works with a nature-inspired / bio-based term AND
sector keywords, restricted to Spanish and Portuguese institutions, then convert
each work to a MapRecord (type "paper") with deterministic keyword rules, and
aggregate one "company" record per distinct OpenAlex company institution.

Classification is rule based over the normalised (lowercase, accent-folded) title
plus OpenAlex topic display names. Abstracts are never requested or stored.

Function group -> area mapping (our own; documented here, used by classify()):
    manage-water -> process            manage-heat -> energy
    manage-air-and-gases -> process    resist-and-support-loads -> form
    protect-surfaces -> materials      attach-and-join -> form
    make-and-assemble -> materials     break-down-and-recycle -> circularity
    sense-and-respond -> systems       move-efficiently -> form
    sustain-ecosystems -> place        optimise-systems -> systems
plus nature_link: bio_based -> materials, circular -> circularity,
nature_based_solution -> place.

Usage (from repo root):
    python scripts/nature/harvest_openalex.py [--data-dir PATH] [--per-sector 60]
        [--max-calls 60] [--dry-run]
Optional env OPENALEX_API_KEY (free key; keyless budget is about 100 searches/day).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _files import write_json_atomic  # noqa: E402
from _http import fetch_json  # noqa: E402
from app.models.nature import MapRecord  # noqa: E402
from app.services.nature.store import DEFAULT_DIR  # noqa: E402

OPENALEX_URL = "https://api.openalex.org/works"
SELECT = "id,doi,title,publication_year,authorships,topics,type,cited_by_count"
COUNTRIES = {"ES", "PT"}
TOPICS_USED = 1  # only the best-scoring OpenAlex topic: lower-ranked topics were mostly noise
EXTRACTED_BY = "rules:harvest_openalex v0"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"

NATURE_TERMS = (
    'biomimetic OR bioinspired OR "bio-inspired" OR biomimicry OR "nature-inspired" OR "bio-based"'
)
# Sector keywords for the AND clause (2-4 per sector, from taxonomy keywords_en).
SECTOR_QUERY = {
    "steel-aluminium": ["steel", "aluminium", "metallurgy", "alloy"],
    "construction-materials": ["construction", "concrete", "cement", "building"],
    "packaging": ["packaging", "paper", "film", "container"],
    "cosmetics": ["cosmetic", "skincare", "pigment", "dye"],
    "textiles": ["textile", "fabric", "fibre", "leather"],
    "automotive": ["automotive", "vehicle", "tyre", "chassis"],
    "energy": ["energy", "solar", "battery", "hydrogen"],
    "agrifood": ["agriculture", "food", "crop", "olive"],
    "water-utilities": ["wastewater", "water treatment", "desalination", "sewage"],
    "chemicals": ["polymer", "coating", "adhesive", "catalyst"],
}

GROUP_AREA = {
    "manage-water": "process",
    "manage-heat": "energy",
    "manage-air-and-gases": "process",
    "resist-and-support-loads": "form",
    "protect-surfaces": "materials",
    "attach-and-join": "form",
    "make-and-assemble": "materials",
    "break-down-and-recycle": "circularity",
    "sense-and-respond": "systems",
    "move-efficiently": "form",
    "sustain-ecosystems": "place",
    "optimise-systems": "systems",
}
LINK_AREA = {"bio_based": "materials", "circular": "circularity", "nature_based_solution": "place"}

# Checked in order; the first group with a whole-word/phrase hit wins.
LINK_RULES = [
    ("biomimetic", ["biomimetic", "bioinspired", "bio-inspired", "biomimicry", "nature-inspired",
                    "biomimetico", "bioinspirado", "biomimetica"]),
    ("bio_based", ["bio-based", "biobased", "biopolymer", "natural fibre", "natural fiber",
                   "biomaterial", "bioplastic", "biocomposite", "biomasa", "biomass"]),
    ("circular", ["recycling", "recycled", "recycle", "recyclable", "circular", "waste",
                  "reciclaje", "reciclado", "residuo"]),
    ("nature_based_solution", ["nature-based", "green infrastructure", "wetland", "green roof",
                               "humedal", "infraestructura verde"]),
]

# Generic keywords that must never assign a function on their own (they were the main
# source of false labels in the v0 sample). A function therefore needs a non-weak
# keyword hit; weak keywords are ignored. Matched after accent folding.
WEAK_KEYWORDS = {
    "packaging", "package", "container", "embalaje", "envase", "wastewater", "aguas residuales",
    "network", "red", "joint", "joining", "union", "detergent", "detergente", "strength",
    "membrane", "membrana", "plantilla", "templating", "rigid", "rigidity", "sliding", "bearing",
    "lift", "wing", "ala", "motor", "cuenca", "seto", "mixing", "modular", "dirt", "residue",
    "wood", "cork", "mold", "mould", "oxidation", "cellular", "flight", "crack", "deposit", "scaling", "erosion", "lifetime", "monitoring", "reserve", "in water",
}
# Spanish/Portuguese keywords apply only when the title looks Spanish or Portuguese.
_ES_PT_WORDS = {"de", "la", "el", "los", "las", "del", "para", "con", "em", "uma", "dos", "das",
                "por", "una", "con", "sobre", "mediante"}
_ES_PT_CHARS = set("áéíóúñãõçàêô")

ORGANISM_WORDS = ["lotus", "gecko", "shark", "mussel", "spider", "termite", "cork", "bamboo", "nacre",
                  "bone", "leaf", "butterfly", "beetle", "silk", "shell", "mycelium",
                  "cactus", "bird", "fish", "whale", "sponge", "ant", "bee",
                  "seaweed", "algae", "coral", "pine cone", "dragonfly", "moth", "fungus", "fungi"]
_BINOMIAL = re.compile(r"\b([A-Z][a-z]{3,})\s([a-z]{4,})\b")
_EPITHET_END = ("us", "um", "is", "ii", "ae", "ata", "ensis", "ica", "ana", "alis", "osa", "iae", "orum")
_EPITHET_STOP = {"analysis", "synthesis", "basis", "thesis", "hypothesis", "diagnosis", "emphasis",
                 "genus", "species", "status", "focus", "bonus", "campus", "corpus", "versus"}

ORG_KIND = {"company": "company", "education": "university", "facility": "research_centre",
            "government": "public_body"}

FetchJson = Callable[[str, Optional[dict]], Optional[dict]]


# ── Text normalisation and classification (pure) ──────────────────────────────


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", folded).strip()


def _hit(norm_text: str, keyword: str) -> bool:
    """Whole-word match of a normalised keyword (trailing plural s/es allowed)."""
    return re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?:e?s)?(?![a-z0-9])", norm_text) is not None


def _keywords(item: dict, *fields: str) -> list[str]:
    out = []
    for field in fields:
        for kw in item.get(field, []):
            out.append(normalise(kw))
    return sorted(set(k for k in out if k))


def sector_hits(text: str, sector: dict) -> int:
    norm = normalise(text)
    return sum(1 for kw in _keywords(sector, "keywords_en", "keywords_es") if _hit(norm, kw))


def looks_spanish_pt(title: str) -> bool:
    """True when the title has Spanish/Portuguese accents or function words."""
    if any(c in _ES_PT_CHARS for c in title.lower()):
        return True
    return any(w in _ES_PT_WORDS for w in re.findall(r"[a-z]+", normalise(title)))


def classify(text: str, taxonomy: dict) -> dict:
    """Deterministic rules over title + topic names -> problem_functions, areas, nature_link."""
    norm = normalise(text)
    fields = ("keywords_en", "keywords_es") if looks_spanish_pt(text.split(" ; ")[0]) else ("keywords_en",)
    functions = []
    for fn in taxonomy["functions"]:
        if any(_hit(norm, kw) for kw in _keywords(fn, *fields) if kw not in WEAK_KEYWORDS):
            functions.append(fn)
    nature_link = "other"
    for link, words in LINK_RULES:
        if any(_hit(norm, w) for w in words):
            nature_link = link
            break
    areas = {GROUP_AREA[fn["group"]] for fn in functions if fn["group"] in GROUP_AREA}
    if nature_link in LINK_AREA:
        areas.add(LINK_AREA[nature_link])
    order = [a["id"] for a in taxonomy["areas"]]
    return {
        "problem_functions": [fn["id"] for fn in functions],
        "areas": sorted(areas, key=order.index),
        "nature_link": nature_link,
    }


def find_organism(title: str) -> str | None:
    """A common organism word or a Latin binomial from the title; None otherwise."""
    norm = normalise(title)
    for word in ORGANISM_WORDS:
        if _hit(norm, word):
            return word
    words = title.split()
    capitalised = sum(1 for w in words if w[:1].isupper())
    if words and capitalised / len(words) > 0.5:  # Title Case: capitals tell us nothing
        return None
    for m in _BINOMIAL.finditer(title):
        genus, epithet = m.groups()
        if epithet in _EPITHET_STOP or not epithet.endswith(_EPITHET_END):
            continue
        if title.startswith(genus):  # sentence-initial capital, not a genus
            continue
        return f"{genus} {epithet}"
    return None


# ── Work -> record (pure) ─────────────────────────────────────────────────────


def _short_id(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url else None


def _institutions(work: dict) -> list[dict]:
    seen, out = set(), []
    for auth in work.get("authorships") or []:
        for inst in auth.get("institutions") or []:
            key = inst.get("id") or inst.get("ror") or inst.get("display_name")
            if key and key not in seen:
                seen.add(key)
                out.append(inst)
    return out


def _organisation(inst: dict) -> dict:
    return {
        "name": inst.get("display_name") or "Unknown",
        "country": inst.get("country_code"),
        "kind": ORG_KIND.get(inst.get("type"), "other"),
        "ror": inst.get("ror"),
    }


def _text(work: dict) -> str:
    topics = " ; ".join(t.get("display_name", "") for t in (work.get("topics") or [])[:TOPICS_USED])
    return f"{work.get('title') or ''} ; {topics}"


def work_to_record(work: dict, sector: dict, taxonomy: dict, run_date: str) -> dict | None:
    """Convert an OpenAlex work to a map record dict (no id yet); None if unusable."""
    title = (work.get("title") or "").strip()
    if not title:
        return None
    # country: most frequent ES/PT country across every authorship institution occurrence
    counts = Counter(
        inst.get("country_code")
        for auth in work.get("authorships") or []
        for inst in auth.get("institutions") or []
        if inst.get("country_code") in COUNTRIES
    )
    if not counts:
        return None
    country = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    cls = classify(_text(work), taxonomy)
    organism = find_organism(title)
    doi = work.get("doi")
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return {
        "type": "paper",
        "title": title,
        "summary": None,
        "sector": sector["id"],
        "nace_divisions": list(sector.get("nace_rev21_divisions", [])),
        "problem_functions": cls["problem_functions"],
        "areas": cls["areas"],
        "nature_link": cls["nature_link"],
        "inspiration": {"organism": organism, "note": None} if organism else None,
        "country": country,
        "region": None,
        "organisations": [_organisation(i) for i in _institutions(work)],
        "year": work.get("publication_year"),
        "trl": None,
        "identifiers": {"doi": doi, "openalex_id": _short_id(work.get("id"))},
        "library_links": [],
        "source": {"name": "OpenAlex", "licence": "CC0", "retrieved_on": run_date},
        "provenance": {"status": "ai_extracted", "extracted_by": EXTRACTED_BY, "extracted_on": run_date},
    }


def aggregate_companies(papers: list[dict], taxonomy: dict, run_date: str) -> list[dict]:
    """One company record per distinct ES/PT company institution seen in the papers."""
    sectors = {s["id"]: s for s in taxonomy["sectors"]}
    by_key: dict[str, dict] = {}
    for paper in papers:
        for org in paper["organisations"]:
            if org["kind"] != "company" or org["country"] not in COUNTRIES:
                continue
            key = org["ror"] or org["name"]
            entry = by_key.setdefault(key, {"org": org, "papers": []})
            entry["papers"].append(paper)
    area_order = [a["id"] for a in taxonomy["areas"]]
    fn_order = [f["id"] for f in taxonomy["functions"]]
    out = []
    for key in sorted(by_key):
        org, ps = by_key[key]["org"], by_key[key]["papers"]
        sector_counts = Counter(p["sector"] for p in ps)
        sector = sorted(sector_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        links = Counter(p["nature_link"] for p in ps)
        link = sorted(links.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out.append({
            "type": "company",
            "title": org["name"],
            "summary": None,
            "sector": sector,
            "nace_divisions": list(sectors[sector].get("nace_rev21_divisions", [])),
            "problem_functions": sorted({f for p in ps for f in p["problem_functions"]}, key=fn_order.index),
            "areas": sorted({a for p in ps for a in p["areas"]}, key=area_order.index),
            "nature_link": link,
            "inspiration": None,
            "country": org["country"],
            "region": None,
            "organisations": [org],
            "year": None,
            "trl": None,
            "identifiers": {"url": org["ror"] or None},
            "library_links": [],
            "source": {"name": "OpenAlex", "licence": "CC0", "retrieved_on": run_date},
            "provenance": {"status": "ai_extracted", "extracted_by": EXTRACTED_BY, "extracted_on": run_date},
        })
    return out


def assign_ids(papers: list[dict], companies: list[dict], taxonomy: dict) -> list[dict]:
    """Deterministic ids: papers by (sector order, year desc, openalex id), then companies."""
    order = {s["id"]: i for i, s in enumerate(taxonomy["sectors"])}
    papers = sorted(
        papers,
        key=lambda r: (order[r["sector"]], -(r["year"] or 0), r["identifiers"].get("openalex_id") or ""),
    )
    companies = sorted(companies, key=lambda r: (order[r["sector"]], r["title"].lower()))
    out = []
    for n, rec in enumerate(papers + companies, start=1):
        out.append({"id": f"map-{n:04d}", **rec})
    return out


# ── OpenAlex querying ─────────────────────────────────────────────────────────


def build_query(sector_id: str) -> str:
    kws = " OR ".join(f'"{k}"' if " " in k else k for k in SECTOR_QUERY[sector_id])
    return f"({NATURE_TERMS}) AND ({kws})"


def build_params(sector_id: str, cursor: str, per_page: int, api_key: str | None) -> dict:
    params = {
        "filter": (
            f"title_and_abstract.search:{build_query(sector_id)},"
            "authorships.institutions.country_code:ES|PT,publication_year:2015-2026"
        ),
        "per_page": per_page,
        "cursor": cursor,
        "select": SELECT,
    }
    if api_key:
        params["api_key"] = api_key
    return params


def cached_fetch(fetch: FetchJson, cache_dir: Path | None) -> FetchJson:
    """Wrap fetch with an on-disk cache of raw responses (api_key excluded from the key)."""

    def inner(url: str, params: dict | None = None):
        if cache_dir is None:
            return fetch(url, params)
        key_params = {k: v for k, v in (params or {}).items() if k != "api_key"}
        digest = hashlib.sha1(json.dumps([url, key_params], sort_keys=True).encode()).hexdigest()
        path = cache_dir / f"{digest}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = fetch(url, params)
        if data is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    return inner


def harvest_sector(
    sector_id: str, fetch: FetchJson, per_sector: int, budget: dict, api_key: str | None
) -> list[dict]:
    """Page through results for one sector until per_sector works or the budget runs out."""
    works: list[dict] = []
    cursor: str | None = "*"
    per_page = min(100, per_sector)
    while cursor and len(works) < per_sector and budget["calls"] < budget["max"]:
        budget["calls"] += 1
        data = fetch(OPENALEX_URL, build_params(sector_id, cursor, per_page, api_key))
        results = (data or {}).get("results") or []
        works.extend(results)
        cursor = ((data or {}).get("meta") or {}).get("next_cursor") if results else None
    return works[:per_sector]


def build_map(
    taxonomy: dict,
    fetch: FetchJson,
    per_sector: int = 60,
    max_calls: int = 60,
    run_date: str | None = None,
    api_key: str | None = None,
) -> tuple[list[dict], dict]:
    """Run the harvest; return (map records with ids, run summary)."""
    run_date = run_date or date.today().isoformat()
    sectors = [s for s in taxonomy["sectors"] if s["id"] in SECTOR_QUERY]
    budget = {"calls": 0, "max": max_calls}
    best: dict[str, tuple[int, dict, dict]] = {}  # openalex id -> (hits, sector, work)
    fetched = {}
    for sector in sectors:
        works = harvest_sector(sector["id"], fetch, per_sector, budget, api_key)
        fetched[sector["id"]] = len(works)
        for work in works:
            hits = sector_hits(_text(work), sector)
            wid = work.get("id")
            if wid and (wid not in best or hits > best[wid][0]):  # ties keep the first sector
                best[wid] = (hits, sector, work)
    papers, unclassified = [], 0
    for _, sector, work in best.values():
        rec = work_to_record(work, sector, taxonomy, run_date)
        if rec is None:
            continue
        if not rec["problem_functions"]:
            unclassified += 1
        papers.append(rec)
    companies = aggregate_companies(papers, taxonomy, run_date)
    records = assign_ids(papers, companies, taxonomy)
    summary = {
        "calls": budget["calls"],
        "works_fetched_by_sector": fetched,
        "papers": len(papers),
        "papers_without_function": unclassified,
        "companies": len(companies),
        "by_sector": dict(Counter(r["sector"] for r in records if r["type"] == "paper")),
    }
    return records, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--per-sector", type=int, default=60)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", help="do not write industry_map.json")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    taxonomy = json.loads((args.data_dir / "taxonomy.json").read_text(encoding="utf-8"))
    fetch = cached_fetch(fetch_json, None if args.no_cache else CACHE_DIR)
    records, summary = build_map(
        taxonomy, fetch, args.per_sector, args.max_calls, api_key=os.environ.get("OPENALEX_API_KEY")
    )
    for rec in records:  # fail loudly rather than write an invalid file
        MapRecord.model_validate(rec)
    if not args.dry_run:
        path = args.data_dir / "industry_map.json"
        write_json_atomic(path, records)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
