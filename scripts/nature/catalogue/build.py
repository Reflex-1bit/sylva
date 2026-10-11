"""Build the Open Nature Catalogue: step 1 (merge) and step 2 (sort). Publishing is a later phase.

Step 1, merge (writes build/stage/merged.jsonl and build/stage/merge_report.json):
  - load every present raw/<source>/records.jsonl and validate each line as a RawRecord;
  - scrub contact clauses from every summary (scrub.scrub_contacts);
  - dedupe: same id; then (1) same bare DOI (CORDIS grant DOIs 10.3030/... match only within the
    same kind); then (2) same fold(title) + year + kind (titles of 3+ words and 20+ characters only,
    so generic titles such as "Editorial" never merge). Keep the record that has a summary, then
    source priority cordis > climate_adapt > openalex > patentsview, then the smallest id; union
    countries and organisations (organisations capped at 10);
  - organism: the longest organisms.json common-name phrase in the folded title, then the summary
    (with simple plural forms); else a Latin binomial found by find_organism() from
    scripts/nature/harvest_openalex.py, run on the title and then on each summary sentence;
    taxa are confirmed on the GBIF species match API (EXACT, or FUZZY with confidence >= 95),
    one call per unique name, cached in scripts/nature/catalogue/.cache/gbif.json, max 5 calls/s;
  - habitat: the lexicon habitat_id, else the best habitats.json keyword score (strong 1, weak 0.25,
    ties to the earlier habitat), else null;
  - genetic_resource_hint: whole-word hit on GENETIC_TERMS;
  - library_id: a servable data/nature/library.json record citing the same DOI.

Step 2, sort (writes build/stage/sorted.jsonl and build/stage/report.json): see sort.py. Candidate
sectors with fewer primaries than min_records are dropped after a first pass and their records are
re-sorted without them. Exits 1 when 'other' holds more than 25% of the records.

Usage (from repo root):
    python scripts/nature/catalogue/build.py merge|sort|all [--offline]
No LLM and no embeddings; the output is deterministic for the same inputs and GBIF cache.
"""

import argparse
import importlib.util
import json
import os
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BUILD_DIR,
    RAW_DIR,
    REPO,
    load_concordance,
    load_habitats,
    load_sectors,
    load_taxonomy,
)
from scrub import scrub_contacts  # noqa: E402
from sort import (  # noqa: E402
    OTHER,
    Rules,
    decide,
    dropped_candidates,
    functions_and_area,
    keyword_text,
    score_record,
)
from textmatch import FoldedText, fold  # noqa: E402

from app.models.catalogue import CatalogueRecord, Organism, RawRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STAGE_DIR = BUILD_DIR / "stage"
ORGANISMS_PATH = HERE / "organisms.json"
AREA_RULES_PATH = HERE / "area_rules.json"
GBIF_CACHE_PATH = HERE / ".cache" / "gbif.json"
GBIF_URL = "https://api.gbif.org/v1/species/match"  # pattern from scripts/nature/verify_sources.py
GBIF_MIN_FUZZY_CONFIDENCE = 95
GBIF_DELAY = 0.2  # 5 requests per second at most
GBIF_KEEP = ("usageKey", "matchType", "confidence", "rank", "status", "scientificName", "kingdom", "class")

SOURCES = ("cordis", "climate_adapt", "openalex", "patentsview")  # also the keep priority
PRIORITY = {s: i for i, s in enumerate(SOURCES)}
GRANT_DOI_PREFIX = "10.3030/"
MAX_ORGANISATIONS = 10
TITLE_MIN_WORDS = 3
TITLE_MIN_CHARS = 20
OTHER_SHARE_MAX = 0.25
SAMPLES_PER_SECTOR = 10
SAMPLE_SEED = 42
GENETIC_TERMS = ("gene", "genes", "genetic", "genome", "dna", "rna", "peptide", "enzyme", "enzymes",
                 "protein sequence", "biosynthesis", "metabolite", "extract", "extracts", "recombinant")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Necessary condition for find_organism's binomial branch: a capitalised word that does not start
# the text, then a lower-case word (its own regex and epithet rules then decide).
_MAYBE_BINOMIAL = re.compile(r"\s[A-Z][a-z]{3,}\s[a-z]{4,}")

FetchJson = Callable[[str, Optional[dict]], Optional[dict]]


class MergedRecord(RawRecord):
    """Step 1 output: a deduped raw record plus organism, habitat, genetic hint and library link."""

    organism: Optional[Organism] = None
    habitat_id: Optional[str] = None
    genetic_resource_hint: bool = False
    library_id: Optional[str] = None


# ── Shared loading ────────────────────────────────────────────────────────────


def _load_v0_find_organism():
    """find_organism() from scripts/nature/harvest_openalex.py, loaded by path (the catalogue
    folder has its own harvest_openalex.py, so a plain import would be ambiguous)."""
    path = REPO / "scripts" / "nature" / "harvest_openalex.py"
    spec = importlib.util.spec_from_file_location("nature_harvest_openalex_v0", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_organism


find_organism = _load_v0_find_organism()


def raw_paths(raw_dir: Path) -> list[tuple[str, Path]]:
    """Present raw sources, in keep-priority order (any subset may be missing)."""
    return [(s, raw_dir / s / "records.jsonl") for s in SOURCES if (raw_dir / s / "records.jsonl").exists()]


def _iter_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                yield n, line


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(tmp, path)


# ── Dedupe ────────────────────────────────────────────────────────────────────


@dataclass
class Key:
    id: str
    source: str
    kind: str
    doi_key: Optional[tuple]
    title_key: Optional[tuple]
    has_summary: bool
    countries: list[str] = field(default_factory=list)
    organisations: list[str] = field(default_factory=list)

    @property
    def order(self) -> tuple:
        return (0 if self.has_summary else 1, PRIORITY.get(self.source, 99), self.id)


def doi_key(doi: Optional[str], kind: str) -> Optional[tuple]:
    """Bare lower-case DOI; CORDIS grant DOIs only match within the same kind."""
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return (d, kind) if d.startswith(GRANT_DOI_PREFIX) else (d,)


def title_key(title: str, year: Optional[int], kind: str) -> Optional[tuple]:
    t = fold(title)
    if len(t) < TITLE_MIN_CHARS or len(t.split()) < TITLE_MIN_WORDS:
        return None
    return (t, year, kind)


def _clean_summary(summary: Optional[str]) -> Optional[str]:
    if summary is None:
        return None
    s = scrub_contacts(summary)
    return s or None


def make_key(rec: RawRecord) -> Key:
    return Key(rec.id, rec.source, rec.kind, doi_key(rec.doi, rec.kind), title_key(rec.title, rec.year, rec.kind),
               _clean_summary(rec.summary) is not None, list(rec.countries), list(rec.organisations))


def _union(lists: list[list[str]], cap: Optional[int] = None, casefold: bool = False) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for v in lst:
            k = v.casefold() if casefold else v
            if k not in seen:
                seen.add(k)
                out.append(v)
    return out[:cap] if cap else out


def dedupe(keys: list[Key]) -> tuple[list[Key], dict[str, int]]:
    """Return (kept keys in input order, with unioned countries/organisations; removed per rule)."""
    removed = {"same_id": 0, "doi": 0, "title_year_kind": 0}
    first: dict[str, Key] = {}
    alive: list[Key] = []
    for k in keys:
        if k.id in first:
            removed["same_id"] += 1
            _absorb(first[k.id], [k])
            continue
        first[k.id] = k
        alive.append(k)

    for rule, getter in (("doi", lambda k: k.doi_key), ("title_year_kind", lambda k: k.title_key)):
        groups: dict[tuple, list[Key]] = {}
        for k in alive:
            g = getter(k)
            if g is not None:
                groups.setdefault(g, []).append(k)
        gone: set[str] = set()
        for members in groups.values():
            if len(members) < 2:
                continue
            members = sorted(members, key=lambda k: k.order)
            keeper, others = members[0], members[1:]
            _absorb(keeper, others)
            gone.update(o.id for o in others)
            removed[rule] += len(others)
        alive = [k for k in alive if k.id not in gone]
    return alive, removed


def _absorb(keeper: Key, others: list[Key]) -> None:
    others = sorted(others, key=lambda k: k.order)
    keeper.countries = _union([keeper.countries] + [o.countries for o in others])
    keeper.organisations = _union([keeper.organisations] + [o.organisations for o in others],
                                  cap=MAX_ORGANISATIONS, casefold=True)


# ── Organisms ─────────────────────────────────────────────────────────────────


# Other forms of a lexicon name that the regular plural rules miss (irregular plurals, singular algae).
IRREGULAR_FORMS = {"leaf": ["leaves"], "cactus": ["cacti"], "mycelium": ["mycelia"], "fungus": ["fungi"],
                   "algae": ["alga"]}


def _plurals(name: str) -> list[str]:
    head, _, last = name.rpartition(" ")
    prefix = head + " " if head else ""
    forms = list(IRREGULAR_FORMS.get(last, []))
    if last.endswith("y") and len(last) > 1 and last[-2] not in "aeiou":
        forms.append(last[:-1] + "ies")
    elif last.endswith(("s", "x", "ch", "sh", "o")):
        forms.append(last + "es")
    if not last.endswith("s"):
        forms.append(last + "s")
    return [prefix + f for f in forms]


class Lexicon:
    """organisms.json: common name -> {taxon, rank, habitat_id}; longest phrase wins."""

    def __init__(self, entries: dict):
        self.entries = {fold(k): dict(v, name=k) for k, v in entries.items()}
        variants = []
        for key in self.entries:
            for form in [key] + _plurals(key):
                variants.append((form, key))
        # longest first (words, then characters), then alphabetical for a stable order
        variants.sort(key=lambda fv: (-len(fv[0].split()), -len(fv[0]), fv[0]))
        seen: set[str] = set()
        self.variants = []
        for form, key in variants:
            if form not in seen:
                seen.add(form)
                self.variants.append((form, key))
        # Fast look-up tables: one-word forms by set intersection, phrases by a scan.
        self._rank = {form: i for i, (form, _) in enumerate(self.variants)}
        self._single = {form: key for form, key in self.variants if " " not in form}
        self._phrases = [(i, form, key) for i, (form, key) in enumerate(self.variants) if " " in form]

    @classmethod
    def load(cls, path: Path = ORGANISMS_PATH) -> "Lexicon":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def longest(self, ft: FoldedText) -> Optional[dict]:
        """The entry whose form is the longest hit (same result as scanning self.variants in order)."""
        for i, form, key in self._phrases:  # phrases rank before every one-word form
            if ft.has_folded(form):
                return self.entries[key]
        singles = ft.tokens & self._single.keys()
        if not singles:
            return None
        best = min(singles, key=self._rank.__getitem__)
        return self.entries[self._single[best]]

    def get(self, word: str) -> Optional[dict]:
        return self.entries.get(fold(word))


def detect_organism(title: str, summary: Optional[str], lex: Lexicon) -> Optional[dict]:
    """{'name', 'query', 'rank', 'habitat_id', 'method'} or None. Lexicon first, then a binomial."""
    texts = [t for t in (title, summary) if t]
    for text in texts:
        hit = lex.longest(FoldedText(text))
        if hit:
            return {"name": hit["name"], "query": hit["taxon"], "rank": hit["rank"],
                    "habitat_id": hit["habitat_id"], "method": "lexicon"}
    chunks = [title] + (_SENTENCE_SPLIT.split(summary) if summary else [])
    for chunk in chunks:
        if not _MAYBE_BINOMIAL.search(chunk):  # cheap pre-check; find_organism decides
            continue
        found = find_organism(chunk)
        if not found:
            continue
        if " " in found and found[:1].isupper():
            return {"name": found, "query": found, "rank": None, "habitat_id": None, "method": "binomial"}
        hit = lex.get(found)
        if hit:
            return {"name": hit["name"], "query": hit["taxon"], "rank": hit["rank"],
                    "habitat_id": hit["habitat_id"], "method": "lexicon"}
    return None


def accept_gbif(match: Optional[dict]) -> bool:
    """EXACT, or FUZZY with confidence >= 95, and a usage key."""
    if not match or match.get("usageKey") is None:
        return False
    if match.get("matchType") == "EXACT":
        return True
    return match.get("matchType") == "FUZZY" and (match.get("confidence") or 0) >= GBIF_MIN_FUZZY_CONFIDENCE


class GbifResolver:
    """GBIF species match with an on-disk cache keyed by the query name (no email, no key)."""

    def __init__(self, cache_path: Path = GBIF_CACHE_PATH, fetch: Optional[FetchJson] = None,
                 sleep: Callable[[float], None] = time.sleep, offline: bool = False):
        self.cache_path = cache_path
        self.cache: dict = {}
        if cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if fetch is None and not offline:
            sys.path.insert(0, str(REPO / "scripts" / "nature"))
            from _http import fetch_json
            fetch = fetch_json
        self.fetch = fetch
        self.sleep = sleep
        self.offline = offline
        self.stats = Counter()
        self._dirty = 0

    def lookup(self, name: str) -> Optional[dict]:
        if name in self.cache:
            self.stats["cached"] += 1
            return self.cache[name]
        if self.offline or self.fetch is None:
            self.stats["uncached_offline"] += 1
            return None
        try:
            data = self.fetch(GBIF_URL, {"name": name})
        except Exception:  # network errors are counted and not cached
            self.stats["errors"] += 1
            self.sleep(GBIF_DELAY)
            return None
        self.stats["fetched"] += 1
        self.sleep(GBIF_DELAY)
        kept = {k: data.get(k) for k in GBIF_KEEP if data and data.get(k) is not None} if data else None
        self.cache[name] = kept
        self._dirty += 1
        if self._dirty >= 200:
            self.save()
        return kept

    def resolve(self, names) -> dict[str, Optional[dict]]:
        out = {}
        for name in sorted(set(n for n in names if n)):
            match = self.lookup(name)
            out[name] = match if accept_gbif(match) else None
            self.stats["accepted" if out[name] else "rejected"] += 1
        self.save()
        return out

    def save(self) -> None:
        if self._dirty:
            _write_json(self.cache_path, dict(sorted(self.cache.items())))
            self._dirty = 0


def build_organism(cand: Optional[dict], resolved: dict[str, Optional[dict]]) -> Optional[Organism]:
    if not cand:
        return None
    match = resolved.get(cand["query"]) if cand["query"] else None
    if cand["method"] == "binomial":
        if not match:
            return None  # an unconfirmed binomial is not an organism
        return Organism(name=cand["name"], gbif_key=match["usageKey"], rank=match.get("rank"))
    if match:
        return Organism(name=cand["name"], gbif_key=match["usageKey"], rank=match.get("rank") or cand["rank"])
    return Organism(name=cand["name"], gbif_key=None, rank=cand["rank"])


# ── Habitat, genetic hint, library ────────────────────────────────────────────


def habitat_from_keywords(ft: FoldedText, habitats) -> Optional[str]:
    best, best_score = None, 0.0
    for h in habitats.habitats:
        score = sum(1.0 for k in h.keywords_en if ft.has(k)) + sum(0.25 for k in h.keywords_weak_en if ft.has(k))
        if score > best_score:
            best, best_score = h.id, score
    return best


def genetic_hint(ft: FoldedText) -> bool:
    return any(ft.has(t) for t in GENETIC_TERMS)


def library_doi_index() -> dict[str, str]:
    """lower-case DOI -> id of a servable library record that cites it."""
    from app.services.nature.store import NatureStore

    index: dict[str, str] = {}
    for rec in NatureStore().library(servable_only=True):
        for ev in rec.evidence:
            if ev.doi:
                index.setdefault(ev.doi.strip().lower(), rec.id)
    return index


# ── Step 1: merge ─────────────────────────────────────────────────────────────


def merge(raw_dir: Path = RAW_DIR, stage_dir: Path = STAGE_DIR, resolver: Optional[GbifResolver] = None,
          lexicon: Optional[Lexicon] = None, library_index: Optional[dict] = None, log=print) -> dict:
    sources = raw_paths(raw_dir)
    if not sources:
        raise SystemExit(f"no raw sources under {raw_dir}")
    lex = lexicon or Lexicon.load()
    habitats = load_habitats()
    lib = library_doi_index() if library_index is None else library_index
    resolver = resolver or GbifResolver()

    # Pass A: validate every line, keep only the small dedupe keys.
    keys: list[Key] = []
    per_source_in = Counter()
    for source, path in sources:
        for n, line in _iter_lines(path):
            try:
                rec = RawRecord.model_validate_json(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{n}: {exc}") from exc
            keys.append(make_key(rec))
            per_source_in[source] += 1
    kept, removed = dedupe(keys)
    kept_by_id = {k.id: k for k in kept}
    del keys
    log(f"merge: {sum(per_source_in.values())} in, {len(kept)} kept, removed {removed}")

    # Pass B: build each kept record once, detect its organism candidate, write a temp file.
    stage_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = stage_dir / "merged.pre.jsonl"
    candidates: dict[str, dict] = {}
    written: set[str] = set()
    with tmp_path.open("w", encoding="utf-8", newline="\n") as out:
        for source, path in sources:
            for _, line in _iter_lines(path):
                d = json.loads(line)
                k = kept_by_id.get(d["id"])
                if k is None or d["id"] in written:
                    continue
                written.add(d["id"])
                d["summary"] = _clean_summary(d.get("summary"))
                d["countries"] = k.countries
                d["organisations"] = k.organisations
                cand = detect_organism(d["title"], d["summary"], lex)
                if cand:
                    candidates[d["id"]] = cand
                ft = keyword_text(d)
                d["habitat_id"] = (cand or {}).get("habitat_id") or habitat_from_keywords(ft, habitats)
                d["genetic_resource_hint"] = genetic_hint(ft)
                d["library_id"] = lib.get(d["doi"].lower()) if d.get("doi") else None
                out.write(json.dumps(d, ensure_ascii=False) + "\n")

    # GBIF: one lookup per unique name, cached.
    queries = sorted({c["query"] for c in candidates.values() if c["query"]})
    log(f"merge: {len(candidates)} organism candidates, {len(queries)} unique GBIF names")
    resolved = resolver.resolve(queries)

    # Pass C: attach organisms, validate, write merged.jsonl.
    stats = Counter()
    by_habitat = Counter()
    top_organisms = Counter()
    per_source_out = Counter()
    final = stage_dir / "merged.jsonl"
    with tmp_path.open(encoding="utf-8") as fh, final.open("w", encoding="utf-8", newline="\n") as out:
        for line in fh:
            d = json.loads(line)
            cand = candidates.get(d["id"])
            org = build_organism(cand, resolved)
            d["organism"] = org.model_dump() if org else None
            if cand and not org and cand["method"] == "binomial":
                stats["binomial_rejected"] += 1
            rec = MergedRecord.model_validate(d)
            out.write(rec.model_dump_json() + "\n")
            per_source_out[rec.source] += 1
            if org:
                stats["with_organism"] += 1
                stats[f"organism_by_{cand['method']}"] += 1
                top_organisms[org.name] += 1
                if org.gbif_key is not None:
                    stats["with_gbif_key"] += 1
            by_habitat[rec.habitat_id or "none"] += 1
            stats["genetic_hint"] += rec.genetic_resource_hint
            stats["library_linked"] += rec.library_id is not None
    tmp_path.unlink()

    report = {
        "sources_present": [s for s, _ in sources],
        "sources_missing": [s for s in SOURCES if s not in {x for x, _ in sources}],
        "records_in": sum(per_source_in.values()),
        "records_after_dedupe": sum(per_source_out.values()),
        "per_source_in": dict(per_source_in),
        "per_source_after_dedupe": dict(per_source_out),
        "duplicates_removed": removed,
        "with_organism": stats["with_organism"],
        "with_gbif_key": stats["with_gbif_key"],
        "organism_by_method": {"lexicon": stats["organism_by_lexicon"], "binomial": stats["organism_by_binomial"]},
        "binomials_rejected_by_gbif": stats["binomial_rejected"],
        "gbif": {"unique_names": len(queries), **dict(sorted(resolver.stats.items()))},
        "top_organisms": dict(top_organisms.most_common(20)),
        "per_habitat": dict(sorted(by_habitat.items(), key=lambda kv: (-kv[1], kv[0]))),
        "with_genetic_hint": stats["genetic_hint"],
        "library_linked": stats["library_linked"],
    }
    _write_json(stage_dir / "merge_report.json", report)
    log(f"merge: wrote {final} ({report['records_after_dedupe']} records)")
    return report


# ── Step 2: sort ──────────────────────────────────────────────────────────────


def load_rules() -> Rules:
    from app.services.nature.keywords import WEAK_KEYWORDS

    return Rules(load_sectors(), load_concordance(), load_taxonomy(),
                 json.loads(AREA_RULES_PATH.read_text(encoding="utf-8")), WEAK_KEYWORDS)


def to_catalogue(d: dict, decision, functions: list[str], area: Optional[str]) -> CatalogueRecord:
    core = {k: d.get(k) for k in ("id", "source", "source_id", "kind", "title", "summary", "summary_licence",
                                  "source_licence", "url", "doi", "year", "countries", "organisations",
                                  "organism", "habitat_id", "library_id", "genetic_resource_hint")}
    return CatalogueRecord(**core, primary_sector=decision.primary, sector_tags=decision.tags, area=area,
                           functions=functions, sort_confidence=decision.confidence,
                           sort_reason=decision.reason, group_ids=[], provenance="machine_sorted",
                           licence="CC-BY-4.0")


def _iter_merged(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def sort_step(stage_dir: Path = STAGE_DIR, rules: Optional[Rules] = None, log=print) -> tuple[int, dict]:
    """Return (exit code, report). Writes sorted.jsonl and report.json into stage_dir."""
    rules = rules or load_rules()
    merged = stage_dir / "merged.jsonl"
    if not merged.exists():
        raise SystemExit(f"{merged} is missing: run the merge step first")

    # Pass 1: all sectors active, count primaries.
    first_counts = Counter()
    for d in _iter_merged(merged):
        first_counts[decide(score_record(d, keyword_text(d), rules, rules.scored), rules).primary] += 1
    dropped = dropped_candidates(first_counts, rules)
    active = [s for s in rules.scored if s not in dropped]
    log(f"sort: first pass {dict(first_counts)}; dropped candidates {dropped}")

    # Pass 2: re-sort without the dropped sectors and write.
    per_sector = Counter()
    per_area = Counter()
    per_function = Counter()
    per_source_sector: dict[str, Counter] = {}
    histogram = [0] * 10
    flags = Counter()
    samples: dict[str, list[tuple[str, str, str]]] = {}
    other_terms = Counter()
    total = 0
    out_path = stage_dir / "sorted.jsonl"
    with out_path.open("w", encoding="utf-8", newline="\n") as out:
        for d in _iter_merged(merged):
            ft = keyword_text(d)
            decision = decide(score_record(d, ft, rules, active), rules)
            functions, area = functions_and_area(ft, rules)
            rec = to_catalogue(d, decision, functions, area)
            out.write(rec.model_dump_json() + "\n")
            total += 1
            per_sector[rec.primary_sector] += 1
            per_source_sector.setdefault(rec.source, Counter())[rec.primary_sector] += 1
            per_area[rec.area or "none"] += 1
            per_function.update(rec.functions)
            histogram[min(9, int(rec.sort_confidence * 10 + 1e-9))] += 1
            flags["tie"] += decision.tie
            flags["keyword_only"] += decision.keyword_only and decision.primary != OTHER
            flags["no_signal"] += decision.reason == "no-signal"
            flags["with_tags"] += bool(decision.tags)
            samples.setdefault(rec.primary_sector, []).append((rec.id, rec.title, rec.sort_reason))
            if rec.primary_sector == OTHER:
                codes = d.get("source_codes") or {}
                other_terms.update(f"subfield:{s}" for s in (codes.get("openalex_subfields") or [])[:1])
                other_terms.update(f"esv:{t}" for t in codes.get("euroscivoc") or [])
                other_terms.update(f"ca:{t}" for t in codes.get("climate_adapt_sectors") or [])

    other_share = per_sector[OTHER] / total if total else 0.0
    rng = random.Random(SAMPLE_SEED)
    sample_rows = {}
    for sid in rules.order:
        rows = samples.get(sid, [])
        picked = rng.sample(rows, min(SAMPLES_PER_SECTOR, len(rows)))
        sample_rows[sid] = [{"id": i, "title": t, "sort_reason": r} for i, t, r in picked]

    merge_report_path = stage_dir / "merge_report.json"
    merge_report = json.loads(merge_report_path.read_text(encoding="utf-8")) if merge_report_path.exists() else {}
    report = {
        **merge_report,
        "records_sorted": total,
        "first_pass_primary": dict(sorted(first_counts.items(), key=lambda kv: rules.position.get(kv[0], 99))),
        "dropped_candidate_sectors": [{"id": s, "first_pass_primaries": first_counts.get(s, 0),
                                       "min_records": rules.candidates[s]} for s in dropped],
        "per_primary_sector": {s: per_sector.get(s, 0) for s in rules.order if s not in dropped},
        "other_share": round(other_share, 4),
        "other_share_max": OTHER_SHARE_MAX,
        "per_source_primary_sector": {src: dict(c.most_common()) for src, c in sorted(per_source_sector.items())},
        "per_area": dict(per_area.most_common()),
        "per_function_top20": dict(per_function.most_common(20)),
        "confidence_histogram": {f"{i / 10:.1f}-{(i + 1) / 10:.1f}": histogram[i] for i in range(10)},
        "sort_flags": dict(flags),
        "top_other_terms": dict(other_terms.most_common(30)),
        "samples": sample_rows,
    }
    _write_json(stage_dir / "report.json", report)
    log(f"sort: wrote {out_path} ({total} records); other share {other_share:.1%}")
    if other_share > OTHER_SHARE_MAX:
        log(f"FAIL: 'other' holds {other_share:.1%} of records (max {OTHER_SHARE_MAX:.0%}). Top terms among 'other':")
        for term, n in other_terms.most_common(30):
            log(f"  {n:6d}  {term}")
        return 1, report
    return 0, report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("merge", "sort", "all"))
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--stage-dir", type=Path, default=STAGE_DIR)
    parser.add_argument("--offline", action="store_true", help="use the GBIF cache only, no network")
    args = parser.parse_args(argv)
    if args.step in ("merge", "all"):
        merge(args.raw_dir, args.stage_dir, resolver=GbifResolver(offline=args.offline))
    if args.step in ("sort", "all"):
        code, _ = sort_step(args.stage_dir)
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
