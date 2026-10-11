"""Pure sorting rules for the catalogue build, step 2 (plan S1-S5; concordance notes a-f are binding).

Per-sector score for one record:
    CPC            the longest-prefix concordance row gives its sector +1.0 (max per sector across codes)
    OpenAlex       subfield row: strong +1.0, medium +0.6; only the primary topic's subfield (the first
                   in the list) counts at full weight, the others x0.5 (max per sector across subfields)
    EuroSciVoc     mapped term +0.8 (max per sector)
    Climate-ADAPT  mapped sector term +0.8 (max per sector)
    keywords       each distinct strong hit +0.2, each weak hit +0.05 (rule d: 0.25 of a strong hit),
                   capped at +0.8 per sector
Concordance rows whose sector is 'other' contribute nothing (rule c; 'other' is never scored).

primary_sector is the argmax; on equal scores the earlier sector in sectors.json wins and the reason
carries '; tie' (rule e). A best score under 0.2 gives 'other' with reason 'no-signal'.
sort_confidence = min(1, best) * (1 - 0.5 * runner_up / best), capped at 0.6 when no code signal
contributed to the winning sector (rule d), rounded to 2 places.
sector_tags are up to 3 other sectors with score >= 0.4 * best and >= 0.2, by score.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from textmatch import FoldedText, fold, fold_term, longest_prefix

MIN_SCORE = 0.2
TAG_RATIO = 0.4
MAX_TAGS = 3
KEYWORD_ONLY_CAP = 0.6
CPC_WEIGHT = 1.0
SUBFIELD_WEIGHT = {"strong": 1.0, "medium": 0.6}
SECONDARY_SUBFIELD_FACTOR = 0.5
EUROSCIVOC_WEIGHT = 0.8
CLIMATE_ADAPT_WEIGHT = 0.8
STRONG_KW = 0.2
WEAK_KW = 0.05
KW_CAP = 0.8
MAX_FUNCTIONS = 5
OTHER = "other"
SCOPE_PREFIX = "scope:"  # harvest bookkeeping keywords, not record content

_EPS = 1e-9


def fmt(x: float) -> str:
    """1.0 -> '1.0', 0.4 -> '0.4', 0.45 -> '0.45'."""
    s = f"{x:.2f}"
    return s[:-1] if s.endswith("0") else s


@dataclass
class SectorScore:
    cpc: float = 0.0
    cpc_sig: str = ""
    subfield: float = 0.0
    subfield_sig: str = ""
    esv: float = 0.0
    esv_sig: str = ""
    ca: float = 0.0
    ca_sig: str = ""
    kw: float = 0.0
    kw_hits: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(self.cpc + self.subfield + self.esv + self.ca + self.kw, 6)

    @property
    def has_code(self) -> bool:
        return (self.cpc + self.subfield + self.esv + self.ca) > 0

    def reason(self) -> str:
        parts = []
        if self.cpc:
            parts.append(f"cpc:{self.cpc_sig}(+{fmt(self.cpc)})")
        if self.subfield:
            parts.append(f"subfield:{self.subfield_sig}(+{fmt(self.subfield)})")
        if self.esv:
            parts.append(f"esv:{self.esv_sig}(+{fmt(self.esv)})")
        if self.ca:
            parts.append(f"ca:{self.ca_sig}(+{fmt(self.ca)})")
        if self.kw:
            parts.append(f"kw:{','.join(self.kw_hits)}(+{fmt(self.kw)})")
        return "; ".join(parts)


@dataclass
class Decision:
    primary: str
    tags: list[str]
    confidence: float
    reason: str
    tie: bool = False
    keyword_only: bool = False
    best: float = 0.0


class Rules:
    """Sorting rules loaded from sectors.json, concordance.json, taxonomy.json and area_rules.json."""

    def __init__(self, sectors, concordance, taxonomy: dict, area_rules: dict,
                 weak_function_keywords: Iterable[str] = ()):
        self.order = [s.id for s in sectors.sectors]
        self.position = {sid: i for i, sid in enumerate(self.order)}
        self.candidates = {s.id: s.min_records for s in sectors.sectors if s.candidate}
        self.scored = [sid for sid in self.order if sid != OTHER]

        self.cpc = {r.prefix: r.sector for r in concordance.cpc if r.sector != OTHER}
        self.subfield = {r.name: (r.sector, SUBFIELD_WEIGHT[r.strength])
                         for r in concordance.openalex_subfield if r.sector != OTHER}
        self.esv = {fold(r.term): (r.sector, r.term) for r in concordance.euroscivoc if r.sector != OTHER}
        self.ca = {fold(r.term): (r.sector, r.term) for r in concordance.climate_adapt_sector if r.sector != OTHER}

        self.strong: dict[str, list[str]] = {}
        self.weak: dict[str, list[str]] = {}
        for s in sectors.sectors:
            strong = _dedupe_folded(s.keywords_en + s.keywords_es)
            seen = {fold_term(k) for k in strong}
            weak = [k for k in _dedupe_folded(s.keywords_weak_en + s.keywords_weak_es) if fold_term(k) not in seen]
            self.strong[s.id] = strong
            self.weak[s.id] = weak

        weak_fn = {fold_term(w) for w in weak_function_keywords}
        self.functions = []  # (id, group, keywords) in taxonomy order
        for fn in taxonomy["functions"]:
            kws = [k for k in _dedupe_folded(fn.get("keywords_en", []) + fn.get("keywords_es", []))
                   if fold_term(k) not in weak_fn]
            self.functions.append((fn["id"], fn["group"], kws))
        self.group_area = dict(area_rules["function_group_to_area"])
        self.area_order = [a["id"] for a in taxonomy["areas"]]
        self.area_keywords = {a: _dedupe_folded(area_rules["keywords"].get(a, [])) for a in self.area_order}


def _dedupe_folded(terms: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for t in terms:
        f = fold_term(t)
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def keyword_text(rec: dict) -> FoldedText:
    """fold(title + summary + keywords joined), without the harvesters' scope: bookkeeping keywords."""
    kws = [k for k in rec.get("keywords") or [] if not k.lower().startswith(SCOPE_PREFIX)]
    return FoldedText(" ".join([rec.get("title") or "", rec.get("summary") or "", " ".join(kws)]))


def score_record(rec: dict, ft: FoldedText, rules: Rules, active: Iterable[str]) -> dict[str, SectorScore]:
    """Per-sector scores for the active sectors (rec is a merged record dict)."""
    active = set(active)
    scores = {sid: SectorScore() for sid in rules.scored if sid in active}
    codes = rec.get("source_codes") or {}

    for code in codes.get("cpc") or []:
        prefix = longest_prefix(code, rules.cpc)
        if prefix is None:
            continue
        sc = scores.get(rules.cpc[prefix])
        if sc is not None and CPC_WEIGHT > sc.cpc:
            sc.cpc, sc.cpc_sig = CPC_WEIGHT, code

    for i, name in enumerate(codes.get("openalex_subfields") or []):
        row = rules.subfield.get(name)
        if row is None:
            continue
        sector, weight = row
        if i > 0:
            weight *= SECONDARY_SUBFIELD_FACTOR
        sc = scores.get(sector)
        if sc is not None and weight > sc.subfield + _EPS:
            sc.subfield, sc.subfield_sig = weight, name

    for table, field_name, weight, attr in ((rules.esv, "euroscivoc", EUROSCIVOC_WEIGHT, "esv"),
                                            (rules.ca, "climate_adapt_sectors", CLIMATE_ADAPT_WEIGHT, "ca")):
        for term in codes.get(field_name) or []:
            row = table.get(fold(term))
            if row is None:
                continue
            sc = scores.get(row[0])
            if sc is not None and getattr(sc, attr) == 0:
                setattr(sc, attr, weight)
                setattr(sc, attr + "_sig", term)

    for sid, sc in scores.items():
        strong = [k for k in rules.strong[sid] if ft.has_folded(k)]
        weak = [k for k in rules.weak[sid] if ft.has_folded(k)]
        if strong or weak:
            sc.kw = round(min(KW_CAP, STRONG_KW * len(strong) + WEAK_KW * len(weak)), 6)
            sc.kw_hits = strong + weak
    return scores


def decide(scores: dict[str, SectorScore], rules: Rules) -> Decision:
    """primary, tags, confidence and reason from per-sector scores (rules d and e)."""
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1].total, rules.position[kv[0]]))
    if not ranked or ranked[0][1].total < MIN_SCORE:
        return Decision(OTHER, [], 0.0, "no-signal", best=ranked[0][1].total if ranked else 0.0)
    best_id, best = ranked[0]
    b = best.total
    runner = ranked[1][1].total if len(ranked) > 1 else 0.0
    tie = len(ranked) > 1 and abs(runner - b) < _EPS
    conf = min(1.0, b) * (1 - 0.5 * runner / b)
    keyword_only = not best.has_code
    if keyword_only:
        conf = min(conf, KEYWORD_ONLY_CAP)
    tags = [sid for sid, sc in ranked[1:] if sc.total >= TAG_RATIO * b - _EPS and sc.total >= MIN_SCORE - _EPS]
    reason = best.reason() + ("; tie" if tie else "")
    return Decision(best_id, tags[:MAX_TAGS], round(conf, 2), reason, tie, keyword_only, b)


def functions_and_area(ft: FoldedText, rules: Rules) -> tuple[list[str], Optional[str]]:
    """Taxonomy functions hit (max 5, by distinct hit count, ties in taxonomy order) and the area."""
    hits = []
    for i, (fid, group, kws) in enumerate(rules.functions):
        n = sum(1 for k in kws if ft.has_folded(k))
        if n:
            hits.append((-n, i, fid, group))
    hits.sort()
    functions = [h[2] for h in hits[:MAX_FUNCTIONS]]
    if hits:
        area = rules.group_area.get(hits[0][3])
        if area:
            return functions, area
    best_area, best_n = None, 0
    for area in rules.area_order:
        n = sum(1 for k in rules.area_keywords[area] if ft.has_folded(k))
        if n > best_n:
            best_area, best_n = area, n
    return functions, best_area


def sort_record(rec: dict, rules: Rules, active: Iterable[str], ft: Optional[FoldedText] = None) -> Decision:
    ft = ft or keyword_text(rec)
    return decide(score_record(rec, ft, rules, active), rules)


def dropped_candidates(primary_counts: dict[str, int], rules: Rules) -> list[str]:
    """Candidate sectors with fewer primaries than their min_records, in sectors.json order."""
    return [sid for sid in rules.order
            if sid in rules.candidates and primary_counts.get(sid, 0) < rules.candidates[sid]]
