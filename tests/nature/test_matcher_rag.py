import copy
import json

import pytest

from app.models.nature import AskRequest, AskResponse, MapRecord
from app.services import rag_service
from app.services.nature import rag
from app.services.nature.links import sector_gaps, sectors_for_record
from app.services.nature.matcher import parse_functions, score_library
from app.services.nature.rag import ask, citation_guard
from app.services.nature.search import NatureSearch
from app.services.nature.store import DEFAULT_DIR, NatureStore

TAXONOMY = {
    "version": "0.1.0",
    "licence": "CC-BY-4.0",
    "areas": [{"id": "form", "label": "Form", "question": "q"}],
    "functions": [
        {"id": "shed-water", "group": "g", "label": "Shed water",
         "keywords_en": ["water repellent", "hydrophobic"], "keywords_es": ["repeler agua", "hidrofóbico"]},
        {"id": "self-clean", "group": "g", "label": "Self clean",
         "keywords_en": ["self-cleaning", "dirt"], "keywords_es": ["suciedad"]},
        {"id": "cool-passively", "group": "g", "label": "Cool passively",
         "keywords_en": ["passive cooling"], "keywords_es": ["enfriamiento pasivo"]},
    ],
    "sectors": [
        {"id": "packaging", "label_en": "P", "label_es": "E", "nace_rev21_divisions": ["17"],
         "keywords_en": [], "keywords_es": []},
        {"id": "textiles", "label_en": "T", "label_es": "T", "nace_rev21_divisions": ["13"],
         "keywords_en": [], "keywords_es": []},
    ],
}

PROV = {"status": "ai_extracted", "extracted_by": "t", "extracted_on": "2026-01-01"}

LIB = {
    "id": "lib-0001", "kind": "mechanism", "title": "Lotus leaf surface",
    "summary": "Micro-textured leaves shed water and dirt.",
    "areas": ["form"], "functions": ["shed-water", "self-clean"], "sector_tags": [],
    "organism": {"scientific_name": "Nelumbo nucifera", "common_names": ["lotus"]},
    "mechanism": "Roughness traps air so droplets roll off.",
    "trait_type": "morphological", "legal_review": "not_required",
    "knowledge_source": "peer_reviewed", "consent": "not_applicable",
    "evidence": [{"citation": "A", "doi": "10.1/a"}, {"citation": "B", "doi": "10.1/b"}],
    "performance": [{"metric": "contact angle", "value": 160.0, "units": "deg"}],
    "provenance": PROV, "confidence": "medium", "caveat": "Lab data only.",
}

MAP = {
    "id": "map-0001", "type": "paper", "title": "Water repellent coatings for cartons",
    "sector": "packaging", "problem_functions": ["shed-water"], "areas": ["form"],
    "nature_link": "biomimetic", "country": "ES",
    "source": {"name": "OpenAlex", "licence": "CC0", "retrieved_on": "2026-01-01"},
    "provenance": PROV,
}


def lib(**changes):
    rec = copy.deepcopy(LIB)
    rec.update(changes)
    return rec


def mp(**changes):
    rec = copy.deepcopy(MAP)
    rec.update(changes)
    return rec


def make_store(tmp_path, library, industry=()):
    (tmp_path / "taxonomy.json").write_text(json.dumps(TAXONOMY), encoding="utf-8")
    (tmp_path / "library.json").write_text(json.dumps(library), encoding="utf-8")
    (tmp_path / "industry_map.json").write_text(json.dumps(list(industry)), encoding="utf-8")
    return NatureStore(tmp_path)


# ── parse_functions ───────────────────────────────────────────────────────────


def test_parse_functions_english_spanish_and_accents():
    assert parse_functions("We need a water-repellent, self-cleaning box", TAXONOMY) == [
        "shed-water", "self-clean"]
    assert parse_functions("Necesitamos un recubrimiento hidrofobico", TAXONOMY) == ["shed-water"]
    assert parse_functions("quitar la suciedad", TAXONOMY) == ["self-clean"]
    assert parse_functions("Need PASSIVE COOLING for a roof", TAXONOMY) == ["cool-passively"]
    assert parse_functions("something unrelated", TAXONOMY) == []


def test_parse_functions_real_taxonomy():
    tax = NatureStore(DEFAULT_DIR).taxonomy()
    assert "shed-water" in parse_functions("a hydrophobic surface", tax)


# ── scoring ───────────────────────────────────────────────────────────────────


def test_score_breakdown_arithmetic(tmp_path):
    a = lib(id="lib-0001", known_products=["Lotusan"],
            source_region={"region": "Valencia", "reserve_id": "R1"},
            provenance={**PROV, "status": "expert_validated",
                        "validated_by": "Dr X", "validated_on": "2026-02-01"})
    b = lib(id="lib-0002", functions=["shed-water"], evidence=[{"citation": "A"}], performance=[],
            source_region={"region": "Murcia"})
    c = lib(id="lib-0003", functions=["cool-passively"], evidence=[{"citation": "A"}], performance=[],
            popular_claim_note="myth")
    store = make_store(tmp_path, [a, b, c])
    recs = {r.id: r for r in store.library()}
    hits = [(recs["lib-0001"], 1.0), (recs["lib-0002"], 0.6), (recs["lib-0003"], 0.2)]
    out = {h.record.id: h for h in score_library(hits, ["shed-water", "self-clean"], store, [])}

    ha = out["lib-0001"]
    assert ha.breakdown["evidence"] == 30 and ha.evidence_grade == "strong"
    assert ha.breakdown["provenance"] == 25
    assert ha.breakdown["fit"] == pytest.approx(20.0)  # norm 1.0 x (0.5 + 0.5 x 1.0)
    assert ha.breakdown["manufacturability"] == 15
    assert ha.breakdown["regional"] == 10
    assert ha.score == pytest.approx(100.0)

    hb = out["lib-0002"]  # raw 0.6 -> norm (0.6-0.2)/(1.0-0.2) = 0.5; overlap 1/2
    assert hb.breakdown["retrieval_raw"] == 0.6
    assert hb.breakdown["retrieval_normalised"] == pytest.approx(0.5)
    assert hb.breakdown["function_overlap_ratio"] == pytest.approx(0.5)
    assert hb.breakdown["fit"] == pytest.approx(20 * 0.5 * 0.75)
    assert hb.breakdown["evidence"] == 10 and hb.breakdown["provenance"] == 10
    assert hb.breakdown["manufacturability"] == 0 and hb.breakdown["regional"] == 5

    hc = out["lib-0003"]  # bottom hit -> fit 0; contested -> evidence 0
    assert hc.breakdown["fit"] == 0.0 and hc.breakdown["evidence"] == 0
    assert hc.evidence_grade == "contested"
    assert [h.record.id for h in score_library(hits, [], store, [])][0] == "lib-0001"


def test_single_hit_fit_is_full_and_no_functions_means_ratio_one(tmp_path):
    store = make_store(tmp_path, [lib()])
    (hit,) = score_library([(store.library()[0], 0.3)], [], store, [])
    assert hit.breakdown["retrieval_normalised"] == 1.0
    assert hit.breakdown["fit"] == 20.0


def test_manufacturability_from_map_link(tmp_path):
    store = make_store(tmp_path, [lib()], [mp(library_links=["lib-0001"])])
    (hit,) = score_library([(store.library()[0], 1.0)], [], store, store.industry_map())
    assert hit.breakdown["manufacturability"] == 15


def test_strict_functions_only_when_set_and_parsed(tmp_path):
    store = make_store(tmp_path, [lib(id="lib-0001"), lib(id="lib-0002", functions=["cool-passively"])])
    hits = [(r, 1.0) for r in store.library()]
    ids = lambda **kw: [h.record.id for h in score_library(hits, ["shed-water"], store, [], **kw)]
    assert set(ids()) == {"lib-0001", "lib-0002"}
    assert ids(strict_functions=True) == ["lib-0001"]
    # nothing parsed: strict is a no-op
    assert len(score_library(hits, [], store, [], strict_functions=True)) == 2


def test_score_library_drops_non_servable(tmp_path):
    store = make_store(tmp_path, [lib(id="lib-0002", trait_type="genetic", legal_review="pending")])
    rec = store.library(servable_only=False)[0]
    assert score_library([(rec, 1.0)], [], store, []) == []


# ── links and gaps ────────────────────────────────────────────────────────────


def gap_store(tmp_path):
    library = [
        lib(id="lib-0001"),  # used by packaging via link; strong
        lib(id="lib-0002", functions=["shed-water"], organism=None,
            evidence=[{"citation": "A"}], performance=[]),  # weak, unused
        lib(id="lib-0003", functions=["shed-water", "self-clean"], organism=None,
            evidence=[{"citation": "A", "doi": "10.1/a"}, {"citation": "B"}], performance=[]),  # moderate
        lib(id="lib-0004", functions=["cool-passively"], organism=None),  # no overlap
        lib(id="lib-0005", functions=["shed-water"], organism=None, trait_type="genetic",
            legal_review="pending"),  # quarantined
    ]
    industry = [
        mp(id="map-0001", library_links=["lib-0001", "lib-0005"], problem_functions=["shed-water"]),
        mp(id="map-0002", title="Dirt study", problem_functions=["shed-water", "self-clean"]),
        mp(id="map-0003", title="Unclassified paper", problem_functions=[]),
        mp(id="map-0004", type="company", title="Firm", problem_functions=["shed-water"]),
        mp(id="map-0005", sector="textiles", title="Nelumbo coatings for fabric",
           problem_functions=["cool-passively"]),
    ]
    return make_store(tmp_path, library, industry)


def test_sector_gaps_fixture(tmp_path):
    store = gap_store(tmp_path)
    res = sector_gaps("packaging", store)
    assert res["sector_id"] == "packaging"
    assert res["classified_papers"] == 2 and res["unclassified_papers"] == 1
    gaps = res["gaps"]
    # demand: shed-water 2, self-clean 1 (papers only). Moderate before weak.
    assert [g["record_id"] for g in gaps] == ["lib-0003", "lib-0002"]
    assert gaps[0] == {"record_id": "lib-0003", "title": "Lotus leaf surface",
                       "functions_overlap": ["self-clean", "shed-water"], "weight": 3,
                       "evidence_grade": "moderate"}
    assert gaps[1]["weight"] == 2 and gaps[1]["evidence_grade"] == "weak"
    assert sector_gaps("packaging", store, limit=1)["gaps"][0]["record_id"] == "lib-0003"


def test_gaps_never_surface_quarantined_records(tmp_path):
    store = gap_store(tmp_path)
    surfaced = {g["record_id"] for g in sector_gaps("textiles", store)["gaps"]}
    surfaced |= {g["record_id"] for g in sector_gaps("packaging", store)["gaps"]}
    assert "lib-0005" not in surfaced
    quarantined = store.library(servable_only=False)[4]
    assert sectors_for_record(quarantined, store) == {"using": [], "candidate": []}


def test_sectors_for_record_using_and_candidate(tmp_path):
    store = gap_store(tmp_path)
    r1 = store.get_library("lib-0001")
    # packaging links it; textiles title mentions the genus Nelumbo
    assert sectors_for_record(r1, store) == {"using": ["packaging", "textiles"], "candidate": []}
    r3 = store.get_library("lib-0003")
    assert sectors_for_record(r3, store) == {"using": [], "candidate": ["packaging"]}


# ── citation guard ────────────────────────────────────────────────────────────


def test_citation_guard_pure_function():
    raw = {
        "summary": "Use the lotus surface [lib-0001] or [lib-9999, map-0001]; also lib-8888 works.",
        "options": [
            {"record_id": "lib-0001", "why": "Good [lib-0001][map-7777]", "caveat": "Lab only"},
            {"record_id": "lib-4242", "why": "invented", "caveat": "x"},
            "garbage",
        ],
        "open_questions": ["Ok? [lib-5555]", 3],
        "next_steps": "not a list",
        "verdict": "promising",
    }
    out = citation_guard(raw, {"lib-0001", "map-0001"})
    assert out["summary"] == "Use the lotus surface [lib-0001] or [map-0001]; also works."
    assert [o["record_id"] for o in out["options"]] == ["lib-0001"]
    assert out["options"][0]["why"] == "Good [lib-0001]"
    assert out["open_questions"] == ["Ok?"]
    assert out["next_steps"] == []
    assert "verdict" not in out
    assert out["_guard"]["dropped_ids"] == [
        "lib-4242", "lib-5555", "lib-8888", "lib-9999", "map-7777"]


# ── ask ───────────────────────────────────────────────────────────────────────


def ask_store(tmp_path):
    weak = lib(id="lib-0002", title="Cactus spine fog capture", summary="Spines collect fog droplets.",
               functions=["cool-passively"], organism=None, evidence=[{"citation": "A"}],
               performance=[], mechanism="Conical spines drive droplets along a gradient.")
    return make_store(tmp_path, [lib(), weak], [mp()])


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(rag_service, "_api_key", lambda: None)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(rag_service, "_api_key", lambda: "test-key")


async def run_ask(store, **kw):
    kw.setdefault("challenge", "We need a hydrophobic self-cleaning surface")
    return await ask(AskRequest(**kw), store, NatureSearch(store))


@pytest.mark.asyncio
async def test_ask_fallback_without_key(tmp_path, no_key):
    store = ask_store(tmp_path)
    res = await run_ask(store, sector="packaging", challenge="Water repellent self-cleaning cartons")
    assert isinstance(res, AskResponse)
    assert res.model == "fallback (no API key)"
    assert res.parsed_functions == ["shed-water", "self-clean"]
    assert res.library_hits[0].record.id == "lib-0001"
    opt = res.answer["options"][0]
    assert opt["record_id"] == "lib-0001"
    assert opt["caveat"] == "Lab data only."
    assert "Micro-textured" in opt["why"]
    assert res.answer["_guard"] == {"dropped_ids": []}
    assert res.answer["sector_gaps"]["sector_id"] == "packaging"
    assert res.licence == "CC-BY-4.0"
    assert res.map_hits and res.map_hits[0].record.id == "map-0001"


@pytest.mark.asyncio
async def test_verdict_rules(tmp_path, no_key):
    # strong + ai_extracted: 30 + 10 + fit 20 = 60 -> promising
    store = ask_store(tmp_path)
    res = await run_ask(store, challenge="hydrophobic lotus surface")
    top = res.library_hits[0]
    assert top.score >= 60 and top.evidence_grade == "strong"
    assert res.verdict == "promising"
    # weak evidence only: below threshold -> weak
    res = await run_ask(store, challenge="fog droplets collected by cactus spines")
    assert res.library_hits[0].score < 60
    assert res.verdict == "weak"
    # nothing retrieved -> no_strong_option, still a deterministic answer
    res = await run_ask(store, challenge="zzzz qqqq xxxx yyyy")
    assert res.library_hits == [] and res.verdict == "no_strong_option"
    assert res.answer["options"] == []
    assert "conventional engineering" in res.answer["summary"].lower()
    assert res.model == "fallback (no matching records)"


@pytest.mark.asyncio
async def test_strict_functions_through_ask(tmp_path, no_key):
    store = ask_store(tmp_path)
    q = "hydrophobic surface with fog droplets and cactus spines"
    loose = await run_ask(store, challenge=q)
    assert {h.record.id for h in loose.library_hits} == {"lib-0001", "lib-0002"}
    strict = await run_ask(store, challenge=q, strict_functions=True)
    assert [h.record.id for h in strict.library_hits] == ["lib-0001"]


@pytest.mark.asyncio
async def test_llm_path_guard_and_llm_cannot_change_ranking_or_verdict(tmp_path, with_key, monkeypatch):
    store = ask_store(tmp_path)
    seen = {}

    async def fake(api_key, prompt):
        seen["prompt"] = prompt
        return {
            "summary": "Lotus [lib-0001] and a made-up one [lib-9999].",
            "options": [
                {"record_id": "lib-9999", "why": "invented", "caveat": "none"},
                {"record_id": "lib-0001", "why": "Water rolls off [lib-0001]", "caveat": "Lab only"},
            ],
            "open_questions": [], "next_steps": [],
            "verdict": "promising", "library_hits": ["lib-9999"],
        }, "gemini-test"

    monkeypatch.setattr(rag_service, "_call_gemini", fake)
    res = await run_ask(store, challenge="fog droplets collected by cactus spines")
    assert res.model == "gemini-test"
    assert res.answer["summary"] == "Lotus [lib-0001] and a made-up one ."
    assert [o["record_id"] for o in res.answer["options"]] == ["lib-0001"]
    assert res.answer["_guard"]["dropped_ids"] == ["lib-9999"]
    assert res.verdict == "weak"  # deterministic, not the LLM's claim
    assert {h.record.id for h in res.library_hits} <= {"lib-0001", "lib-0002"}
    scores = [(-h.score, h.record.id) for h in res.library_hits]
    assert scores == sorted(scores)
    assert "lib-0002" in seen["prompt"] and "nature is the first place to look" in seen["prompt"]


@pytest.mark.asyncio
async def test_llm_error_falls_back(tmp_path, with_key, monkeypatch):
    async def boom(api_key, prompt):
        raise RuntimeError("quota")

    monkeypatch.setattr(rag_service, "_call_gemini", boom)
    res = await run_ask(ask_store(tmp_path))
    assert res.model == "fallback (LLM error: quota)"
    assert res.answer["options"][0]["record_id"] == "lib-0001"


@pytest.mark.asyncio
async def test_ask_never_surfaces_quarantined_link(tmp_path, no_key):
    quarantined = lib(id="lib-0009", trait_type="genetic", legal_review="pending",
                      title="Hydrophobic gene", organism=None)
    store = make_store(tmp_path, [lib(), quarantined], [mp(library_links=["lib-0001", "lib-0009"])])
    res = await run_ask(store, sector="packaging", challenge="Water repellent self-cleaning cartons")
    assert "lib-0009" not in res.model_dump_json()
    assert res.map_hits[0].record.library_links == ["lib-0001"]


# ── Ruling 5-1: function-overlap tiers ────────────────────────────────────────


def tier_store(tmp_path):
    strong_off = lib(id="lib-0001", functions=["self-clean"], known_products=["X"],
                     provenance={**PROV, "status": "expert_validated",
                                 "validated_by": "Dr X", "validated_on": "2026-02-01"})
    weak_on = lib(id="lib-0002", functions=["shed-water"], organism=None,
                  evidence=[{"citation": "A"}], performance=[])
    return make_store(tmp_path, [strong_off, weak_on])


def test_overlapping_low_evidence_outranks_non_overlapping_high_evidence(tmp_path):
    store = tier_store(tmp_path)
    recs = {r.id: r for r in store.library()}
    hits = [(recs["lib-0001"], 1.0), (recs["lib-0002"], 0.9)]
    out = score_library(hits, ["shed-water"], store, [])
    assert [h.record.id for h in out] == ["lib-0002", "lib-0001"]
    assert out[0].breakdown["tier"] == 1 and out[1].breakdown["tier"] == 2
    assert out[1].score > out[0].score  # published scores are unchanged
    # no parsed functions: single tier, ordered by score
    out = score_library(hits, [], store, [])
    assert [h.record.id for h in out] == ["lib-0001", "lib-0002"]
    assert {h.breakdown["tier"] for h in out} == {1}


@pytest.mark.asyncio
async def test_tier_two_only_verdict_is_weak(tmp_path, no_key):
    store = tier_store(tmp_path)
    # request.functions asks for cool-passively; neither record has it, so all hits are tier 2
    res = await run_ask(store, challenge="roughness traps air", functions=["cool-passively"])
    top = res.library_hits[0]
    assert top.breakdown["tier"] == 2
    assert top.score >= 60 and top.evidence_grade in ("strong", "moderate")
    assert res.verdict == "weak"


def test_weak_keyword_alone_does_not_assign_function():
    tax = {"functions": [{"id": "amb", "keywords_en": ["in water", "ambient"], "keywords_es": []},
                         {"id": "cap", "keywords_en": ["capture water"], "keywords_es": []}]}
    assert parse_functions("capture water from air", tax) == ["cap"]
    assert parse_functions("ambient conditions", tax) == ["amb"]
    real = NatureStore(DEFAULT_DIR).taxonomy()
    assert "make-at-ambient-conditions" not in parse_functions("capture water from air", real)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "challenge, function, wrong_first",
    [
        ("capture water from air", "capture-water", "lib-0001"),
        ("lighter structural component for cars", "lighten-structure", "lib-0037"),
    ],
)
async def test_real_data_top_hits_carry_expected_function(no_key, challenge, function, wrong_first):
    store = NatureStore(DEFAULT_DIR)
    res = await ask(AskRequest(challenge=challenge), store, NatureSearch(store))
    assert function in res.parsed_functions
    top3 = res.library_hits[:3]
    assert all(function in h.record.functions for h in top3)
    assert res.library_hits[0].record.id != wrong_first


# ── Ruling 5-2: function-only candidates (Spanish/Portuguese recall) ──────────


def test_function_only_candidate_gets_fit_zero_and_respects_filters(tmp_path):
    store = tier_store(tmp_path)
    from app.services.nature.matcher import with_function_candidates

    recs = {r.id: r for r in store.library()}
    out = with_function_candidates([(recs["lib-0001"], 1.0)], ["shed-water"], store)
    assert [(r.id, s) for r, s in out] == [("lib-0001", 1.0), ("lib-0002", 0.0)]
    assert with_function_candidates([], [], store) == []  # nothing parsed: no-op
    assert with_function_candidates([], ["shed-water"], store, kinds=["material"]) == []
    scored = score_library(out, ["shed-water"], store, [])
    extra = next(h for h in scored if h.record.id == "lib-0002")
    assert extra.breakdown["retrieval_raw"] == 0.0
    assert extra.breakdown["retrieval_normalised"] == 0.0
    assert extra.breakdown["fit"] == 0.0
    # only function-only candidates: no retrieval signal at all, fit stays 0
    (only,) = score_library([(recs["lib-0002"], 0.0)], ["shed-water"], store, [])
    assert only.breakdown["fit"] == 0.0


@pytest.mark.asyncio
async def test_spanish_challenge_finds_english_records_real_data(no_key):
    store = NatureStore(DEFAULT_DIR)
    res = await ask(AskRequest(challenge="superficie que repele la suciedad"), store, NatureSearch(store))
    assert "self-clean" in res.parsed_functions
    assert len(res.library_hits) >= 3
    assert all("self-clean" in h.record.functions for h in res.library_hits)
