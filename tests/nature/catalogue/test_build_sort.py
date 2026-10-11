"""Phase 4+5: text matching, dedupe, organisms, GBIF cache, sorting rules, determinism."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.models.catalogue import ConcordanceFile, SectorsFile

CAT = Path(__file__).resolve().parents[3] / "scripts" / "nature" / "catalogue"
sys.path.insert(0, str(CAT))


def _load(name, alias=None):
    spec = importlib.util.spec_from_file_location(alias or name, CAT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias or name] = mod
    spec.loader.exec_module(mod)
    return mod


tm = _load("textmatch")
srt = _load("sort")
scrub = _load("scrub")
build = _load("build", "catalogue_build")


# ── textmatch ─────────────────────────────────────────────────────────────────


def test_fold():
    assert tm.fold("  Bio-Inspired  FIBRA ÓPTICA!! ") == "bio inspired fibra optica"
    assert tm.fold(None) == ""
    assert tm.fold("Ação—Nature_based") == "acao nature based"


@pytest.mark.parametrize("text,term,hit", [
    ("A bionic hand", "bionic", True),
    ("The symbionic relationship", "bionic", False),
    ("In this paper we show a device", "paper towel", False),
    ("A paper towel dispenser", "paper towel", True),
    ("Sensores de FIBRA ÓPTICA distribuidos", "fibra óptica", True),
    ("Sensores de fibra optica", "fibra óptica", True),
    ("Self-cleaning glass", "self cleaning", True),
    ("Self-cleaning glass", "self-cleaning", True),
    ("selfcleaning glass", "self cleaning", False),
    ("Termites build mounds", "termite", False),
])
def test_has_term_whole_word(text, term, hit):
    folded = tm.fold(text)
    assert tm.has_term(folded, term) is hit
    assert tm.FoldedText(text).has(term) is hit  # the fast path agrees


def test_count_terms_distinct_folded():
    assert tm.count_terms(tm.fold("Óptica and optica, sensor sensor"), ["óptica", "optica", "sensor", "laser"]) == 2


def test_compact_cpc_and_longest_prefix():
    assert tm.compact_cpc("a61f 2/00") == "A61F200"
    assert tm.compact_cpc(" B29B 17/04 ") == "B29B1704"
    prefixes = ["A61K", "A61K8", "B29B17", "B29"]
    assert tm.longest_prefix("A61K 8/02", prefixes) == "A61K8"
    assert tm.longest_prefix("A61K 31/00", prefixes) == "A61K"
    assert tm.longest_prefix("B29B 17/04", prefixes) == "B29B17"
    assert tm.longest_prefix("B29C 64/00", prefixes) == "B29"
    assert tm.longest_prefix("H04W 4/00", prefixes) is None


# ── scrub ─────────────────────────────────────────────────────────────────────


def test_scrub_correspondence_clauses():
    s = scrub.scrub_contacts(
        "We made a gecko tape. Correspondence to: Dr A. Smith, Dept of Biology\nIt sticks well.")
    assert "Correspondence" not in s and "Dept" not in s and "gecko tape" in s and "sticks well" in s
    s = scrub.scrub_contacts("Lotus coatings shed water. Corresponding author(s): J Doe (jdoe@uni.edu). Results follow.")
    assert "Corresponding" not in s and "jdoe" not in s and "Results follow." in s
    s = scrub.scrub_contacts("A shark skin film. *Corresponding author at Univ X, Spain\nMethods.")
    assert "Corresponding" not in s and "Univ X" not in s and "Methods." in s
    s = scrub.scrub_contacts("Contact [email protected] for data.")
    assert "email" not in s and "protected" not in s


# ── dedupe ────────────────────────────────────────────────────────────────────


def key(id, source="openalex", kind="paper", doi=None, title="A unique long title number one", year=2020,
        summary=False, countries=(), orgs=()):
    return build.Key(id, source, kind, build.doi_key(doi, kind), build.title_key(title, year, kind), summary,
                     list(countries), list(orgs))


def test_dedupe_doi_keeps_summary_then_priority_then_id():
    keys = [
        key("oa-W2", doi="10.1/abc", title="t one alpha beta gamma delta"),
        key("oa-W1", doi="10.1/ABC", title="t two alpha beta gamma delta", countries=["ES"]),
        key("cd-9", source="cordis", kind="project", doi="10.1/abc", title="t three alpha beta gamma",
            countries=["PT"], orgs=["Org A"]),
    ]
    kept, removed = build.dedupe(keys)
    assert [k.id for k in kept] == ["cd-9"]  # no summaries: cordis beats openalex
    assert removed["doi"] == 2
    assert kept[0].countries == ["PT", "ES"]

    keys = [key("oa-W2", doi="10.1/x", title="first title alpha beta gamma"),
            key("oa-W1", doi="10.1/x", title="second title alpha beta gamma"),
            key("cd-1", source="cordis", kind="project", doi="10.1/x", title="third title alpha beta gamma")]
    keys[0].has_summary = True
    kept, _ = build.dedupe(keys)
    assert [k.id for k in kept] == ["oa-W2"]  # a summary beats source priority

    kept, _ = build.dedupe([key("oa-W9", doi="10.1/y", title="aaa alpha beta gamma delta"),
                            key("oa-W10", doi="10.1/y", title="bbb alpha beta gamma delta")])
    assert [k.id for k in kept] == ["oa-W10"]  # then the smallest id (string order)


def test_dedupe_grant_doi_only_within_kind():
    keys = [key("cd-1", source="cordis", kind="project", doi="10.3030/123456", title="Project alpha beta gamma"),
            key("oa-W1", doi="10.3030/123456", title="Paper alpha beta gamma delta")]
    kept, removed = build.dedupe(keys)
    assert len(kept) == 2 and removed["doi"] == 0


def test_dedupe_title_year_kind():
    title = "Bio-inspired adhesives from gecko feet"
    keys = [key("oa-W1", title=title, year=2020),
            key("oa-W2", title="BIO INSPIRED adhesives from Gecko feet!", year=2020, orgs=[f"Org {i}" for i in range(12)]),
            key("oa-W3", title=title, year=2021),
            key("cd-1", source="cordis", kind="project", title=title, year=2020),
            key("oa-W4", title="Editorial", year=2020),
            key("oa-W5", title="Editorial", year=2020)]
    kept, removed = build.dedupe(keys)
    ids = [k.id for k in kept]
    assert "oa-W2" not in ids and {"oa-W1", "oa-W3", "cd-1", "oa-W4", "oa-W5"} <= set(ids)
    assert removed["title_year_kind"] == 1
    w1 = next(k for k in kept if k.id == "oa-W1")
    assert len(w1.organisations) == 10  # union capped at 10


def test_dedupe_same_id():
    kept, removed = build.dedupe([key("oa-W1"), key("oa-W1", countries=["FR"])])
    assert len(kept) == 1 and removed["same_id"] == 1 and kept[0].countries == ["FR"]


# ── organisms ─────────────────────────────────────────────────────────────────


LEX = build.Lexicon.load()


def test_lexicon_longest_phrase_and_plurals():
    hit = build.detect_organism("Namib desert beetle inspired fog collectors", None, LEX)
    assert hit["name"] == "namib desert beetle" and hit["query"] == "Stenocara" and hit["habitat_id"] == "arid"
    hit = build.detect_organism("Ventilation of termite mounds", None, LEX)
    assert hit["name"] == "termite mound" and hit["query"] == "Macrotermes"
    hit = build.detect_organism("Gecko-inspired dry adhesives", None, LEX)
    assert hit["name"] == "gecko" and hit["query"] == "Gekkonidae" and hit["rank"] == "FAMILY"
    hit = build.detect_organism("Butterflies and colour", None, LEX)
    assert hit["name"] == "butterfly"
    hit = build.detect_organism("Wetting of lotus leaves", None, LEX)
    assert hit["name"] == "lotus leaf"  # irregular plural, longest phrase
    assert build.detect_organism("Cacti spines", None, LEX)["name"] == "cactus"


def test_lexicon_title_before_summary_and_binomial_fallback():
    hit = build.detect_organism("A lotus coating", "Inspired by the shark skin of fast swimmers.", LEX)
    assert hit["name"] == "lotus"
    hit = build.detect_organism("A new coating", "We copied the shark skin of fast swimmers.", LEX)
    assert hit["name"] == "shark skin"
    hit = build.detect_organism("Surface wax of the bug Rhodnius prolixus", None, LEX)
    assert hit == {"name": "Rhodnius prolixus", "query": "Rhodnius prolixus", "rank": None,
                   "habitat_id": None, "method": "binomial"}
    hit = build.detect_organism("A new coating", "Tests used larvae. Wax from the bug Rhodnius prolixus was studied.", LEX)
    assert hit["name"] == "Rhodnius prolixus"
    assert build.detect_organism("Machine learning for robots", "Nothing alive here.", LEX) is None


def test_lexicon_generic_tissue_word_has_no_taxon():
    hit = build.detect_organism("Wood-inspired lattices", None, LEX)
    assert hit["query"] is None and hit["habitat_id"] == "forest"
    org = build.build_organism(hit, {})
    assert org.name == "wood" and org.gbif_key is None


@pytest.mark.parametrize("match,ok", [
    ({"usageKey": 1, "matchType": "EXACT", "confidence": 90}, True),
    ({"usageKey": 1, "matchType": "FUZZY", "confidence": 95}, True),
    ({"usageKey": 1, "matchType": "FUZZY", "confidence": 94}, False),
    ({"usageKey": 6, "matchType": "HIGHERRANK", "confidence": 99}, False),
    ({"matchType": "NONE", "confidence": 100}, False),
    ({"matchType": "EXACT", "confidence": 99}, False),  # no usage key
    (None, False),
])
def test_accept_gbif(match, ok):
    assert build.accept_gbif(match) is ok


def _fake_gbif(answers, calls):
    def fetch(url, params=None):
        assert url == build.GBIF_URL
        assert set(params) == {"name"}  # no email, no key
        calls.append(params["name"])
        return answers.get(params["name"])
    return fetch


def test_gbif_resolver_accept_reject_and_cache(tmp_path):
    answers = {
        "Gekkonidae": {"usageKey": 5666, "matchType": "EXACT", "confidence": 94, "rank": "FAMILY", "extra": "x"},
        "Rhodnius prolixus": {"usageKey": 42, "matchType": "FUZZY", "confidence": 97, "rank": "SPECIES"},
        "Herein various": {"usageKey": 7, "matchType": "FUZZY", "confidence": 80, "rank": "SPECIES"},
    }
    calls, sleeps = [], []
    cache = tmp_path / ".cache" / "gbif.json"
    r1 = build.GbifResolver(cache, fetch=_fake_gbif(answers, calls), sleep=sleeps.append)
    out = r1.resolve(["Gekkonidae", "Rhodnius prolixus", "Herein various", "Nothing here", "Gekkonidae"])
    assert sorted(calls) == ["Gekkonidae", "Herein various", "Nothing here", "Rhodnius prolixus"]  # unique names
    assert sleeps and all(s >= 0.2 for s in sleeps)  # at most 5 requests per second
    assert out["Gekkonidae"]["usageKey"] == 5666 and out["Rhodnius prolixus"]["usageKey"] == 42
    assert out["Herein various"] is None and out["Nothing here"] is None
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert "extra" not in saved["Gekkonidae"] and saved["Nothing here"] is None

    def offline(url, params=None):
        raise AssertionError("network used on a cached rerun")

    r2 = build.GbifResolver(cache, fetch=offline, sleep=lambda s: None)
    assert r2.resolve(["Gekkonidae", "Rhodnius prolixus", "Herein various", "Nothing here"]) == out
    assert r2.stats["cached"] == 4 and r2.stats["fetched"] == 0

    org = build.build_organism({"name": "Herein various", "query": "Herein various", "rank": None,
                                "habitat_id": None, "method": "binomial"}, out)
    assert org is None  # a rejected binomial is dropped


def test_gbif_errors_are_not_cached(tmp_path):
    def boom(url, params=None):
        raise RuntimeError("down")
    r = build.GbifResolver(tmp_path / "g.json", fetch=boom, sleep=lambda s: None)
    assert r.resolve(["Gekkonidae"]) == {"Gekkonidae": None}
    assert r.stats["errors"] == 1 and not (tmp_path / "g.json").exists()


# ── sorting rules (hand-made score table) ─────────────────────────────────────


def _sector(id, candidate=False, min_records=0, **kw):
    base = dict(id=id, label_en=id, label_es=id, label_pt=id, candidate=candidate, min_records=min_records)
    base.update(kw)
    return base


SECTORS = SectorsFile.model_validate({"version": "t", "nace_source": "https://example.org/nace", "sectors": [
    _sector("med", keywords_en=["implant", "scaffold", "prosthesis", "suture", "catheter"], keywords_weak_en=["bone"],
            cpc_prefixes=["A61F"], openalex_subfields=["Biomedical Engineering", "Dermatology"]),
    _sector("chem", keywords_en=["catalyst", "solvent"], keywords_weak_en=["polymer", "coating"],
            cpc_prefixes=["C08", "C08L"], openalex_subfields=["Catalysis"]),
    _sector("robo", candidate=True, min_records=2, keywords_en=["gripper", "actuator"],
            cpc_prefixes=["B25J"], openalex_subfields=["Mechanical Engineering"]),
    _sector("build", keywords_en=["facade", "green roof"], keywords_weak_en=["ventilation"]),
    _sector("other"),
]})
CONC = ConcordanceFile.model_validate({"version": "t", "notes": "test", "cpc": [
    {"prefix": "A61F", "sector": "med", "note": "n"}, {"prefix": "C08", "sector": "chem", "note": "n"},
    {"prefix": "C08L", "sector": "chem", "note": "n"}, {"prefix": "B25J", "sector": "robo", "note": "n"}],
    "openalex_subfield": [
        {"name": "Biomedical Engineering", "sector": "med", "strength": "strong", "note": "n"},
        {"name": "Dermatology", "sector": "med", "strength": "medium", "note": "n"},
        {"name": "Catalysis", "sector": "chem", "strength": "strong", "note": "n"},
        {"name": "Mechanical Engineering", "sector": "robo", "strength": "strong", "note": "n"}],
    "euroscivoc": [{"term": "medical engineering", "sector": "med", "note": "n"},
                   {"term": "natural sciences", "sector": "other", "note": "n"}],
    "climate_adapt_sector": [{"term": "Buildings", "sector": "build", "note": "n"},
                             {"term": "Coastal areas", "sector": "other", "note": "n"}],
})
TAXONOMY = {
    "areas": [{"id": a} for a in ("form", "process", "materials", "energy", "circularity", "systems", "place")],
    "functions": [
        {"id": "shed-water", "group": "manage-water", "keywords_en": ["hydrophobic", "water repellent"], "keywords_es": []},
        {"id": "self-clean", "group": "protect-surfaces", "keywords_en": ["self-cleaning", "lotus"], "keywords_es": []},
        {"id": "adhere-reversibly", "group": "attach-and-join", "keywords_en": ["dry adhesive", "gecko"],
         "keywords_es": ["adhesivo seco"]},
    ],
}
AREA_RULES = {"function_group_to_area": {"manage-water": "process", "protect-surfaces": "materials",
                                         "attach-and-join": "form"},
              "keywords": {"energy": ["solar", "battery"], "place": ["urban", "wetland"]}}
RULES = srt.Rules(SECTORS, CONC, TAXONOMY, AREA_RULES)
ALL = RULES.scored


def rec(title="A study", summary=None, keywords=(), cpc=(), subfields=(), esv=(), ca=()):
    return {"title": title, "summary": summary, "keywords": list(keywords),
            "source_codes": {"cpc": list(cpc), "openalex_subfields": list(subfields), "euroscivoc": list(esv),
                             "climate_adapt_sectors": list(ca)}}


def decide(r, active=ALL):
    return srt.sort_record(r, RULES, active)


# (record, primary, confidence, reason, tags)
TABLE = [
    # 1 CPC-only patent: longest prefix C08L -> chem, +1.0
    (rec(title="A widget", cpc=["C08L 1/02"]), "chem", 1.0, "cpc:C08L 1/02(+1.0)", []),
    # 2 strong primary subfield
    (rec(subfields=["Biomedical Engineering"]), "med", 1.0, "subfield:Biomedical Engineering(+1.0)", []),
    # 3 medium subfield
    (rec(subfields=["Dermatology"]), "med", 0.6, "subfield:Dermatology(+0.6)", []),
    # 4 secondary subfield counts x0.5; the primary subfield (Catalysis) wins
    (rec(subfields=["Catalysis", "Biomedical Engineering"]), "chem", 0.75,
     "subfield:Catalysis(+1.0)", ["med"]),
    # 5 keyword-only: 4 strong hits = 0.8, confidence capped at 0.6 (rule d)
    (rec(title="Implant scaffold prosthesis suture"), "med", 0.6, "kw:implant,scaffold,prosthesis,suture(+0.8)", []),
    # 6 keyword cap 0.8 per sector (5 strong + 1 weak)
    (rec(title="implant scaffold prosthesis suture catheter bone"), "med", 0.6,
     "kw:implant,scaffold,prosthesis,suture,catheter,bone(+0.8)", []),
    # 7 tie: one strong keyword each -> earlier sector (med) wins, flagged
    (rec(title="An implant with a catalyst"), "med", 0.1, "kw:implant(+0.2); tie", ["chem"]),
    # 8 below threshold -> other / no-signal (one weak keyword = 0.05)
    (rec(title="A polymer"), "other", 0.0, "no-signal", []),
    # 9 EuroSciVoc term +0.8; the 'other' row adds nothing
    (rec(esv=["natural sciences", "medical engineering"]), "med", 0.8, "esv:medical engineering(+0.8)", []),
    # 10 Climate-ADAPT term + keyword; the 'other' row adds nothing
    (rec(title="A green roof", ca=["Coastal areas", "Buildings"]), "build", 1.0,
     "ca:Buildings(+0.8); kw:green roof(+0.2)", []),
    # 11 tags exclude the primary and need >= 0.4 x best: chem 0.4 (boundary) is in, robo 0.2 < 0.4 is out
    (rec(title="actuator catalyst solvent", cpc=["A61F 2/00"]), "med", 0.8,
     "cpc:A61F 2/00(+1.0)", ["chem"]),
    # 12 code + keywords on the same sector, not capped
    (rec(title="gripper actuator", subfields=["Mechanical Engineering"]), "robo", 1.0,
     "subfield:Mechanical Engineering(+1.0); kw:gripper,actuator(+0.4)", []),
    # 13 one distinct weak keyword (0.05), however often repeated, stays below the threshold
    (rec(title="ventilation", summary="ventilation"), "other", 0.0, "no-signal", []),
]


@pytest.mark.parametrize("r,primary,conf,reason,tags", TABLE)
def test_score_table(r, primary, conf, reason, tags):
    d = decide(r)
    assert (d.primary, d.confidence, d.reason, d.tags) == (primary, conf, reason, tags)
    assert d.primary not in d.tags


def test_confidence_formula_with_runner_up():
    # med 1.0 (cpc) vs chem 0.5 (subfield secondary) -> 1.0 * (1 - 0.5 * 0.5) = 0.75
    d = decide(rec(cpc=["A61F 2/00"], subfields=["Unmapped Subfield", "Catalysis"]))
    assert d.primary == "med" and d.confidence == 0.75 and d.tags == ["chem"]


def test_candidate_collapse_resorts_without_sector():
    records = [rec(title="gripper actuator implant"), rec(title="implant scaffold"), rec(title="a catalyst")]
    first = {}
    for r in records:
        p = decide(r).primary
        first[p] = first.get(p, 0) + 1
    assert first == {"robo": 1, "med": 1, "chem": 1}
    dropped = srt.dropped_candidates(first, RULES)
    assert dropped == ["robo"]  # 1 primary < min_records 2
    active = [s for s in ALL if s not in dropped]
    again = decide(records[0], active)
    assert again.primary == "med" and again.reason == "kw:implant(+0.2)"
    assert "robo" not in again.tags


def test_functions_then_area():
    ft = srt.keyword_text(rec(title="Gecko dry adhesive that is hydrophobic", keywords=["self-cleaning"]))
    functions, area = srt.functions_and_area(ft, RULES)
    assert functions == ["adhere-reversibly", "shed-water", "self-clean"]  # by hit count, then taxonomy order
    assert area == "form"  # attach-and-join -> form
    functions, area = srt.functions_and_area(srt.keyword_text(rec(title="Urban wetland battery")), RULES)
    assert functions == [] and area == "place"  # area keywords: place 2 > energy 1
    assert srt.functions_and_area(srt.keyword_text(rec(title="nothing")), RULES) == ([], None)


def test_scope_keywords_ignored():
    d = decide(rec(title="A thing", keywords=["scope:implant", "scope:green roof"]))
    assert d.primary == "other"


# ── end to end: merge + sort on a tiny raw dir; determinism ──────────────────


def _raw_line(**kw):
    base = dict(source="openalex", kind="paper", summary=None, summary_licence=None, source_licence="CC0-1.0",
                doi=None, year=2024, countries=[], organisations=[], keywords=[], harvested_on="2026-10-11",
                source_codes={"cpc": [], "openalex_subfields": [], "openalex_topics": [], "euroscivoc": [],
                              "climate_adapt_sectors": []})
    base.update(kw)
    base.setdefault("source_id", base["id"].split("-", 1)[1])
    base.setdefault("url", f"https://openalex.org/{base['source_id']}")
    return json.dumps(base)


@pytest.fixture
def raw_dir(tmp_path):
    oa = tmp_path / "raw" / "openalex"
    oa.mkdir(parents=True)
    lines = [
        _raw_line(id="oa-W1", title="Gecko-inspired dry adhesive gripper for robots", doi="10.1/a",
                  source_codes={"cpc": [], "openalex_subfields": ["Mechanical Engineering"], "openalex_topics": [],
                                "euroscivoc": [], "climate_adapt_sectors": []}),
        _raw_line(id="oa-W2", title="Gecko-inspired dry adhesive gripper for robots", doi="10.1/A"),
        _raw_line(id="oa-W3", title="Enzyme cascade in a wetland soil study", summary_licence="CC-BY-4.0",
                  summary="Wax of the bug Rhodnius prolixus was studied. Corresponding author: A B, Uni X."),
        _raw_line(id="oa-W4", title="Untitled thing about nothing at all"),
    ]
    (oa / "records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ca = tmp_path / "raw" / "climate_adapt"
    ca.mkdir()
    (ca / "records.jsonl").write_text(_raw_line(
        id="ca-green-roofs", source="climate_adapt", kind="case_study", source_licence="CC-BY-4.0",
        title="Green roofs in a city", url="https://climate-adapt.eea.europa.eu/x",
        source_codes={"cpc": [], "openalex_subfields": [], "openalex_topics": [], "euroscivoc": [],
                      "climate_adapt_sectors": ["Buildings", "Land use planning"]}) + "\n", encoding="utf-8")
    return tmp_path / "raw"


def test_merge_then_sort_end_to_end_and_deterministic(raw_dir, tmp_path):
    stage = tmp_path / "stage"
    answers = {"Gekkonidae": {"usageKey": 5666, "matchType": "EXACT", "confidence": 94, "rank": "FAMILY"},
               "Rhodnius prolixus": {"usageKey": 42, "matchType": "EXACT", "confidence": 99, "rank": "SPECIES"}}
    calls = []
    resolver = build.GbifResolver(tmp_path / "gbif.json", fetch=_fake_gbif(answers, calls), sleep=lambda s: None)
    rep = build.merge(raw_dir, stage, resolver=resolver, library_index={"10.1/a": "lib-0001"}, log=lambda *a: None)
    assert rep["sources_present"] == ["climate_adapt", "openalex"] and "cordis" in rep["sources_missing"]
    assert rep["duplicates_removed"]["doi"] == 1 and rep["records_after_dedupe"] == 4
    merged = {json.loads(l)["id"]: json.loads(l) for l in (stage / "merged.jsonl").read_text(encoding="utf-8").splitlines()}
    assert set(merged) == {"oa-W1", "oa-W3", "oa-W4", "ca-green-roofs"}
    assert merged["oa-W1"]["organism"] == {"name": "gecko", "gbif_key": 5666, "rank": "FAMILY"}
    assert merged["oa-W1"]["library_id"] == "lib-0001" and merged["oa-W1"]["habitat_id"] == "forest"
    assert merged["oa-W3"]["organism"]["name"] == "Rhodnius prolixus"
    assert merged["oa-W3"]["habitat_id"] == "wetland" and merged["oa-W3"]["genetic_resource_hint"] is True
    assert "Corresponding" not in merged["oa-W3"]["summary"]
    assert merged["oa-W4"]["organism"] is None

    rules = build.load_rules()
    code1, report = build.sort_step(stage, rules=rules, log=lambda *a: None)
    first = (stage / "sorted.jsonl").read_bytes()
    code2, _ = build.sort_step(stage, rules=rules, log=lambda *a: None)
    assert (stage / "sorted.jsonl").read_bytes() == first  # byte-identical
    assert code1 == code2
    rows = {json.loads(l)["id"]: json.loads(l) for l in first.decode("utf-8").splitlines()}
    assert rows["oa-W4"]["primary_sector"] == "other" and rows["oa-W4"]["sort_reason"] == "no-signal"
    assert rows["oa-W1"]["group_ids"] == [] and rows["oa-W1"]["provenance"] == "machine_sorted"
    assert rows["oa-W1"]["area"] == "form"  # adhere-reversibly -> attach-and-join -> form
    # All candidate sectors collapse on 4 records, so Buildings/Land use planning fall back to other.
    assert rows["ca-green-roofs"]["primary_sector"] == "other"
    assert {d["id"] for d in report["dropped_candidate_sectors"]} >= {"buildings-architecture", "machinery-robotics"}
    assert report["other_share"] > 0.25 and code1 == 1  # the gate fails on this tiny set

    # GBIF cache: a rerun of merge works offline.
    offline = build.GbifResolver(tmp_path / "gbif.json", fetch=None, offline=True)
    build.merge(raw_dir, stage, resolver=offline, library_index={}, log=lambda *a: None)
    assert offline.stats["uncached_offline"] == 0 and offline.stats["cached"] == 2
