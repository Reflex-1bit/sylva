"""Phase 4+5: text matching, dedupe, organisms, GBIF cache, sorting rules, determinism."""

import importlib.util
import json
import re
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


TEL_RE = re.compile(r"\b(tel|fax|phone)\b\.?\s*:?\s*\+?\d", re.I)
STUB_RE = re.compile(r"e-?mail\s*:", re.I)


@pytest.mark.parametrize("text,kept", [
    ("Cigli - Izmir - Turkey - E-mail: - Tel: +902323524040. PURPOSE: This study aimed", "PURPOSE: This study aimed"),
    ("Manchester M13 9PL, U.K. Fax: 0161-275 4939 Manuscript received 20 October 2000", "Manuscript received 20"),
    ("Visakhapatnam-530 045, India E-mail: Fax: 91-891-2790032 Manuscript received online", "Manuscript received"),
    ("Tamilnadu, India E-mail:, Sol-gel silica glass", "Sol-gel silica glass"),
    ("Maharashtra, IndiaEmail:", "Maharashtra, India"),
    ("Tel. (+34) 91 123 45 67; Telephone: 0034 91 1234567. Phone +1-555-0100. Results.", "Results."),
])
def test_scrub_phone_fax_and_email_stubs(text, kept):
    s = scrub.scrub_contacts(text)
    assert not TEL_RE.search(s) and not STUB_RE.search(s) and kept in s
    assert not re.search(r"\d{6,}", s)


def test_scrub_keeps_ordinary_words():
    for text in ("We tested 5 telephone poles.", "The phone is 3 years old.", "Leave a voicemail: ok."):
        assert scrub.scrub_contacts(text) == text


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
                   "habitat_id": None, "gbif_key": None, "method": "binomial"}
    hit = build.detect_organism("A new coating", "Tests used larvae. Wax from the bug Rhodnius prolixus was studied.", LEX)
    assert hit["name"] == "Rhodnius prolixus"
    assert build.detect_organism("Machine learning for robots", "Nothing alive here.", LEX) is None


def test_lexicon_taxon_null_word_feeds_habitat_only():
    hit = build.detect_organism("Wood-inspired lattices", None, LEX)
    assert hit["method"] == "habitat_only" and hit["query"] is None and hit["habitat_id"] == "forest"
    assert build.build_organism(hit, {}) is None  # wood is not an organism
    hit = build.detect_organism("Bone-like scaffolds for implants", None, LEX)
    assert hit["method"] == "habitat_only" and build.build_organism(hit, {}) is None


def test_lexicon_real_taxon_in_summary_beats_taxon_null_word_in_title():
    hit = build.detect_organism("Leaf-like veins in a cooling plate", "The design copies the gecko toe.", LEX)
    assert hit["name"] == "gecko" and hit["method"] == "lexicon"
    hit = build.detect_organism("Bone-like composites", "Wax from the bug Rhodnius prolixus was studied.", LEX)
    assert hit["name"] == "Rhodnius prolixus"


def test_fish_is_a_class_with_a_pinned_gbif_key():
    hit = build.detect_organism("Fish-inspired swimming robots", None, LEX)
    assert hit["name"] == "fish" and hit["query"] == "Actinopterygii" and hit["rank"] == "CLASS"
    org = build.build_organism(hit, {"Actinopterygii": None})  # /species/match gives NONE for the class
    assert org.model_dump() == {"name": "fish", "gbif_key": 204, "rank": "CLASS"}


def test_stoplisted_binomials_yield_no_organism():
    stop = build.Stoplist.load()
    assert "Staphylococcus aureus" in stop and "Escherichia coli" in stop and "Homo sapiens" in stop
    assert "Staphylococcus epidermidis" in stop and "Sporosarcina epidermidis" in stop  # "S. epidermidis"
    assert "Rhodnius prolixus" not in stop
    text = "Coatings were tested against the bacterium Staphylococcus aureus in vitro."
    assert build.detect_organism("A new coating", text, LEX, stop) is None
    both = text + " The texture copies the bug Rhodnius prolixus closely."
    assert build.detect_organism("A new coating", both, LEX, stop)["name"] == "Rhodnius prolixus"
    assert build.detect_organism("A new coating", text, LEX)["name"] == "Staphylococcus aureus"  # no stoplist


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
    logs = []
    assert build.gbif_exit_code(r, log=logs.append) == 1 and "FAIL" in logs[-1]


def test_gbif_exit_code_cache_answers_and_offline(tmp_path):
    cache = tmp_path / "g.json"
    cache.write_text(json.dumps({"Gekkonidae": {"usageKey": 5666, "matchType": "EXACT"}}), encoding="utf-8")

    def boom(url, params=None):
        raise RuntimeError("down")
    r = build.GbifResolver(cache, fetch=boom, sleep=lambda s: None)
    r.resolve(["Gekkonidae"])  # answered from the cache: no error
    assert build.gbif_exit_code(r, log=lambda *a: None) == 0

    off = build.GbifResolver(cache, offline=True)
    out = off.resolve(["Gekkonidae", "Apis mellifera", "Mytilus edulis"])
    assert out["Apis mellifera"] is None and off.stats["uncached_offline"] == 2  # a miss is "no match"
    logs = []
    assert build.gbif_exit_code(off, log=logs.append) == 0
    assert "2 GBIF names not in the cache" in logs[0]


def test_build_main_exits_non_zero_on_gbif_errors(raw_dir, tmp_path, monkeypatch):
    class Failing(build.GbifResolver):
        def __init__(self, offline=False):
            def boom(url, params=None):
                raise RuntimeError("down")
            super().__init__(tmp_path / "g.json", fetch=boom, sleep=lambda s: None, offline=offline)
    monkeypatch.setattr(build, "GbifResolver", Failing)
    monkeypatch.setattr(build, "library_doi_index", lambda: {})
    stage = tmp_path / "stage"
    assert build.main(["all", "--raw-dir", str(raw_dir), "--stage-dir", str(stage)]) == 1
    assert not (stage / "sorted.jsonl").exists()  # sort does not run on a broken merge


def test_habitat_fallback_title_summary_only_and_needs_a_strong_hit():
    habitats = build.load_habitats()
    rec_ = {"title": "Ice and leaf textures on a tree root", "summary": None, "keywords": ["marine", "ocean"]}
    assert build.habitat_from_keywords(build.habitat_text(rec_), habitats) is None  # weak only; keywords ignored
    rec_ = {"title": "Coral reef inspired breakwater", "summary": None, "keywords": []}
    assert build.habitat_from_keywords(build.habitat_text(rec_), habitats) == "marine"


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
    # 2 strong primary subfield, corroborated by a strong keyword of its sector
    (rec(title="A suture", subfields=["Biomedical Engineering"]), "med", 1.0,
     "subfield:Biomedical Engineering(+1.0); kw:suture(+0.2)", []),
    # 3 medium subfield, corroborated
    (rec(title="An implant", subfields=["Dermatology"]), "med", 0.8, "subfield:Dermatology(+0.6); kw:implant(+0.2)", []),
    # 4 secondary subfield counts x0.5; the primary subfield (Catalysis) wins
    (rec(title="A catalyst and a suture", subfields=["Catalysis", "Biomedical Engineering"]), "chem", 0.71,
     "subfield:Catalysis(+1.0); kw:catalyst(+0.2)", ["med"]),  # chem 1.2, med 0.5 + 0.2
    # 5 keyword-only: 4 strong hits = 0.8, confidence capped at 0.6 (rule d)
    (rec(title="Implant scaffold prosthesis suture"), "med", 0.6, "kw:implant,scaffold,prosthesis,suture(+0.8)", []),
    # 6 keyword cap 0.8 per sector (5 strong + 1 weak)
    (rec(title="implant scaffold prosthesis suture catheter bone"), "med", 0.6,
     "kw:implant,scaffold,prosthesis,suture,catheter,bone(+0.8)", []),
    # 7 tie at 0.4 (two strong keywords each): rule (e) still applies -> earlier sector (med) wins, flagged
    (rec(title="An implant scaffold with a catalyst in a solvent"), "med", 0.2, "kw:implant,scaffold(+0.4); tie",
     ["chem"]),
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
    # ── TUNE-1 rule 1: a subfield that is its sector's only code signal needs a strong keyword ──
    # 14 lone strong subfield, no keyword of its sector: x0.5
    (rec(title="Beetle horn micromechanics", subfields=["Mechanical Engineering"]), "robo", 0.5,
     "subfield:Mechanical Engineering[uncorroborated](+0.5)", []),
    # 15 lone medium subfield: 0.6 x 0.5
    (rec(subfields=["Dermatology"]), "med", 0.3, "subfield:Dermatology[uncorroborated](+0.3)", []),
    # 16 a weak keyword does not corroborate (polymer is weak for chem)
    (rec(title="A polymer", subfields=["Catalysis"]), "chem", 0.55,
     "subfield:Catalysis[uncorroborated](+0.5); kw:polymer(+0.05)", []),
    # 17 a CPC code of the same sector corroborates; CPC itself is never halved
    (rec(cpc=["C08L 1/02"], subfields=["Catalysis"]), "chem", 1.0, "cpc:C08L 1/02(+1.0); subfield:Catalysis(+1.0)", []),
    # 18 a EuroSciVoc term corroborates; EuroSciVoc itself is never halved
    (rec(esv=["medical engineering"], subfields=["Dermatology"]), "med", 1.0,
     "subfield:Dermatology(+0.6); esv:medical engineering(+0.8)", []),
    # 19 a Climate-ADAPT term is never halved, even alone
    (rec(ca=["Buildings"]), "build", 0.8, "ca:Buildings(+0.8)", []),
    # 20 halving flips the winner: chem 1.0 -> 0.5 uncorroborated; robo secondary 0.5 + gripper 0.2 = 0.7
    (rec(title="A gripper", subfields=["Catalysis", "Mechanical Engineering"]), "robo", 0.45,
     "subfield:Mechanical Engineering(+0.5); kw:gripper(+0.2)", ["chem"]),
    # 21 a second subfield of the same sector does not corroborate (subfields are one signal type)
    (rec(subfields=["Biomedical Engineering", "Dermatology"]), "med", 0.5,
     "subfield:Biomedical Engineering[uncorroborated](+0.5)", []),
    # ── TUNE-1 rule 5: a tie below 0.4 goes to other / weak-tie ──
    # 22 one strong keyword each (0.2 = 0.2)
    (rec(title="An implant with a catalyst"), "other", 0.0, "weak-tie", []),
    # 23 two secondary subfields, both uncorroborated: 0.5 x 0.5 = 0.25 each
    (rec(subfields=["Unmapped Subfield", "Catalysis", "Mechanical Engineering"]), "other", 0.0, "weak-tie", []),
    # 24 just below the bar: med 0.3 + 0.05 = 0.35, chem 0.25 + 0.05 + 0.05 = 0.35
    (rec(title="bone polymer coating", subfields=["Dermatology", "Catalysis"]), "other", 0.0, "weak-tie", []),
    # 25 a weak score that is NOT a tie still wins (rule 5 only touches ties)
    (rec(title="An implant with a solvent and a polymer"), "chem", 0.15, "kw:solvent,polymer(+0.25)", ["med"]),
]


@pytest.mark.parametrize("r,primary,conf,reason,tags", TABLE)
def test_score_table(r, primary, conf, reason, tags):
    d = decide(r)
    assert (d.primary, d.confidence, d.reason, d.tags) == (primary, conf, reason, tags)
    assert d.primary not in d.tags


def test_confidence_formula_with_runner_up():
    # med 1.0 (cpc) vs chem 0.5 (subfield secondary, corroborated by 'catalyst') + 0.2 = 0.7
    # -> 1.0 * (1 - 0.5 * 0.7) = 0.65
    d = decide(rec(title="A catalyst", cpc=["A61F 2/00"], subfields=["Unmapped Subfield", "Catalysis"]))
    assert d.primary == "med" and d.confidence == 0.65 and d.tags == ["chem"]


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


REAL_RULES = build.load_rules()


@pytest.mark.parametrize("r,weight,sig", [
    # Biomaterials is medium (0.6); alone and without a clinical strong keyword it counts x0.5 (rule 1)
    # and x0.5 again (FX-1 kept on top, TUNE-1 variant A): 0.15
    (rec(title="Nacre-like ceramic composites with high toughness", subfields=["Biomaterials"]),
     0.15, "Biomaterials[uncorroborated]"),
    (rec(title="Porous scaffold for bone regeneration", subfields=["Biomaterials"]), 0.6, "Biomaterials"),
    (rec(title="Antibacterial surfaces for patients", subfields=["Biomedical Engineering"]),
     0.6, "Biomedical Engineering"),
    # secondary position: 0.6 x 0.5 = 0.3, then uncorroborated x0.25 = 0.075
    (rec(title="A gripper", subfields=["Mechanical Engineering", "Biomedical Engineering"]),
     0.075, "Biomedical Engineering[uncorroborated]"),
    # another health-medical code signal (CPC A61F) corroborates the subfield
    (rec(title="A device", subfields=["Biomaterials"], cpc=["A61F 2/00"]), 0.6, "Biomaterials"),
    # TUNE-1: a second health-medical subfield (Surgery) no longer corroborates; subfields are one
    # signal type, so only a CPC/EuroSciVoc/Climate-ADAPT signal or a strong keyword does
    # (the larger subfield signal, Biomaterials 0.6 > Surgery 0.5, is the one halved, here x0.25)
    (rec(title="A device", subfields=["Biomaterials", "Surgery"]), 0.15, "Biomaterials[uncorroborated]"),
    # TUNE-1: every subfield is covered now, not only the two broad ones (Surgery is strong, 1.0);
    # a non-broad subfield is halved once only
    (rec(title="A device", subfields=["Surgery"]), 0.5, "Surgery[uncorroborated]"),
])
def test_health_medical_corroboration(r, weight, sig):
    sc = srt.score_record(r, srt.keyword_text(r), REAL_RULES, REAL_RULES.scored)["health-medical"]
    assert (sc.subfield, sc.subfield_sig) == (weight, sig)


@pytest.mark.parametrize("r,sector,weight,sig", [
    # the round-1 confusions with the real sectors.json / concordance.json
    # basic biomechanics led by Mechanical Engineering, no machinery strong keyword
    (rec(title="Beetle horn shell micromechanics", subfields=["Mechanical Engineering"]),
     "machinery-robotics", 0.5, "Mechanical Engineering[uncorroborated]"),
    # a robot fish led by Aerospace Engineering: no aerospace strong keyword -> halved
    (rec(title="A robot fish with an undulating tail", subfields=["Aerospace Engineering"]),
     "aerospace-transport", 0.5, "Aerospace Engineering[uncorroborated]"),
    # ... while flight corroborates it
    (rec(title="Flapping wing flight of a hoverfly", subfields=["Aerospace Engineering"]),
     "aerospace-transport", 1.0, "Aerospace Engineering"),
    # a weak Environmental Engineering secondary (0.6 x 0.5 = 0.3) with no water keyword -> 0.15
    (rec(title="A lotus leaf coating", subfields=["Unmapped Subfield", "Environmental Engineering"]),
     "water-utilities", 0.15, "Environmental Engineering[uncorroborated]"),
])
def test_corroboration_all_sectors_real_rules(r, sector, weight, sig):
    sc = srt.score_record(r, srt.keyword_text(r), REAL_RULES, REAL_RULES.scored)[sector]
    assert (sc.subfield, sc.subfield_sig) == (weight, sig)


@pytest.mark.parametrize("title,sector", [
    ("A soft robot that crawls", "machinery-robotics"),
    ("Legged locomotion of a gecko-inspired climber", "machinery-robotics"),
    ("Underwater robot inspired by the manta ray", "machinery-robotics"),
    ("A swimming robot with fins", "machinery-robotics"),
    ("Robotic arms and robots", "machinery-robotics"),
    ("Insect-scale drones and MAV design", "aerospace-transport"),
    ("A UAV wing with an aerofoil profile", "aerospace-transport"),
    ("Hydrodynamic drag of a ship hull", "aerospace-transport"),
    ("Aerodynamics of bird wings", "aerospace-transport"),
    ("Tidal turbine blades inspired by whale flippers", "energy"),
    ("An energy harvester for vibration energy harvesting", "energy"),
    ("A supercapacitor and a fuel cell", "energy"),
    ("Power extraction by a flapping foil", "energy"),
])
def test_tune1_strong_keywords(title, sector):
    r = rec(title=title)
    sc = srt.score_record(r, srt.keyword_text(r), REAL_RULES, REAL_RULES.scored)[sector]
    assert sc.kw >= srt.STRONG_KW and set(sc.kw_hits) & set(REAL_RULES.strong[sector])


def test_variant_a_broad_subfield_does_not_beat_a_halved_secondary():
    # The round-1 regression: primary topic Biomaterials (0.6 -> x0.25 = 0.15) vs a secondary chemicals
    # subfield (1.0 x 0.5 -> x0.5 = 0.25). With FX-1 kept on top, chemicals wins, as before TUNE-1.
    r = rec(title="Collagen mineralization with a peptide", subfields=["Biomaterials", "Materials Chemistry"])
    d = srt.sort_record(r, REAL_RULES, REAL_RULES.scored)
    assert d.primary == "chemicals"
    assert d.reason == "subfield:Materials Chemistry[uncorroborated](+0.25)"


def test_tune1_followup_vessel_and_spanish():
    aero_strong, aero_weak = REAL_RULES.strong["aerospace-transport"], REAL_RULES.weak["aerospace-transport"]
    assert "vessel" in aero_weak and "vessel" not in aero_strong  # blood vessel
    assert "marine vessel" in aero_strong
    blood = rec(title="Blood vessel scaffolds")
    sc = srt.score_record(blood, srt.keyword_text(blood), REAL_RULES, REAL_RULES.scored)["aerospace-transport"]
    assert sc.kw == srt.WEAK_KW
    assert {"dron", "drones", "barco", "buque"} <= set(aero_strong)
    assert not {"dron", "barco", "buque"} & set(aero_weak)
    assert {"robot", "robotico", "robotica"} <= set(REAL_RULES.strong["machinery-robotics"])  # folded forms


def test_drone_only_in_aerospace():
    for sid in REAL_RULES.scored:
        terms = set(REAL_RULES.strong[sid]) | set(REAL_RULES.weak[sid])
        assert bool({"drone", "drones"} & terms) == (sid == "aerospace-transport"), sid


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


def test_failed_merge_leaves_no_merged_jsonl(raw_dir, tmp_path, monkeypatch):
    """A merge that fails (GBIF errors, or an exception part-way) must not leave a merged.jsonl."""
    def boom(url, params=None):
        raise RuntimeError("down")
    stage = tmp_path / "stage"
    resolver = build.GbifResolver(tmp_path / "g.json", fetch=boom, sleep=lambda s: None)
    build.merge(raw_dir, stage, resolver=resolver, library_index={}, log=lambda *a: None)
    assert resolver.stats["errors"] and build.gbif_exit_code(resolver, log=lambda *a: None) == 1
    assert not (stage / "merged.jsonl").exists() and not (stage / "merged.jsonl.tmp").exists()
    assert not (stage / "merge_report.json").exists()

    stage2 = tmp_path / "stage2"
    ok = build.GbifResolver(tmp_path / "g2.json", fetch=lambda u, p=None: None, sleep=lambda s: None)
    real = build.MergedRecord.model_validate
    calls = []

    def flaky(d):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("bad record")
        return real(d)
    monkeypatch.setattr(build.MergedRecord, "model_validate", staticmethod(flaky))
    with pytest.raises(ValueError):
        build.merge(raw_dir, stage2, resolver=ok, library_index={}, log=lambda *a: None)
    assert not (stage2 / "merged.jsonl").exists()
