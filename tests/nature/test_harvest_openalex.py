import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("harvest_openalex", ROOT / "scripts" / "nature" / "harvest_openalex.py")
ho = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ho)

TAX = json.loads((ROOT / "data" / "nature" / "taxonomy.json").read_text(encoding="utf-8"))
SECTORS = {s["id"]: s for s in TAX["sectors"]}


def _inst(name, cc, typ, ror=None, iid=None):
    return {"id": iid or f"https://openalex.org/I{name}", "display_name": name, "country_code": cc,
            "type": typ, "ror": ror}


def _work(wid="https://openalex.org/W1", title="Lotus-inspired self-cleaning coating for steel", **kw):
    work = {
        "id": wid, "doi": "https://doi.org/10.1/abc", "title": title, "publication_year": 2021,
        "topics": [{"display_name": "Corrosion and recycling"}],
        "authorships": [
            {"institutions": [_inst("Uni A", "ES", "education"), _inst("Acme SA", "PT", "company", "https://ror.org/x")]},
            {"institutions": [_inst("Uni A", "ES", "education")]},
            {"institutions": [_inst("Foreign Ltd", "DE", "company")]},
        ],
        "abstract_inverted_index": {"secret": [0]},
    }
    work.update(kw)
    return work


def test_classify_functions_areas_link():
    cls = ho.classify("Bioinspired self-cleaning surface ; Corrosion", TAX)
    assert "self-clean" in cls["problem_functions"]
    assert "resist-corrosion" in cls["problem_functions"]
    assert cls["nature_link"] == "biomimetic"
    assert "materials" in cls["areas"]


def test_classify_spanish_accent_folded():
    cls = ho.classify("Recubrimiento superhidrofóbico para el reciclaje", TAX)
    assert "shed-water" in cls["problem_functions"]  # accented title vs folded keyword
    assert cls["nature_link"] == "circular"


def test_spanish_keywords_ignored_for_english_title():
    assert ho.classify("Autolimpiante coating ; Misc", TAX)["problem_functions"] == []
    assert "self-clean" in ho.classify("Superficie autolimpiante de la fachada ; Misc", TAX)["problem_functions"]


def test_weak_keyword_alone_assigns_nothing():
    for title in ("Bio-based packaging film", "Wastewater from a plant", "Fatty amines in detergents", "Joint design"):
        assert ho.classify(title, TAX)["problem_functions"] == [], title


def test_link_rules_are_whole_word():
    assert ho.classify("Wastewater sludge", TAX)["nature_link"] == "other"
    assert ho.classify("Waste valorisation", TAX)["nature_link"] == "circular"


def test_classify_nothing():
    cls = ho.classify("A study", TAX)
    assert cls == {"problem_functions": [], "areas": [], "nature_link": "other"}


def test_find_organism():
    assert ho.find_organism("Lotus-inspired coatings") == "lotus"
    assert ho.find_organism("Adhesion of Mytilus edulis byssus") == "Mytilus edulis"
    assert ho.find_organism("Bioinspired materials for packaging") is None
    assert ho.find_organism("Bioinspired Analysis Methods") is None


def test_work_to_record_is_valid_and_has_no_abstract():
    rec = ho.work_to_record(_work(), SECTORS["steel-aluminium"], TAX, "2026-10-10")
    assert rec["type"] == "paper" and rec["summary"] is None
    assert rec["country"] == "ES"  # Uni A twice vs Acme once
    assert rec["identifiers"] == {"doi": "10.1/abc", "openalex_id": "W1"}
    assert {o["kind"] for o in rec["organisations"]} == {"university", "company"}
    assert rec["provenance"]["extracted_by"] == "rules:harvest_openalex v0"
    assert rec["inspiration"] == {"organism": "lotus", "note": None}
    assert "abstract" not in json.dumps(rec)
    from app.models.nature import MapRecord

    MapRecord.model_validate({"id": "map-0001", **rec})


def test_work_without_es_pt_institution_dropped():
    work = _work(authorships=[{"institutions": [_inst("X", "DE", "company")]}])
    assert ho.work_to_record(work, SECTORS["energy"], TAX, "2026-10-10") is None


def test_aggregate_companies_only_es_pt_companies():
    a = ho.work_to_record(_work("https://openalex.org/W1"), SECTORS["steel-aluminium"], TAX, "d")
    b = ho.work_to_record(_work("https://openalex.org/W2", title="Biomimetic recycling of waste"), SECTORS["steel-aluminium"], TAX, "d")
    c = ho.work_to_record(_work("https://openalex.org/W3", title="Biomimetic fabric"), SECTORS["textiles"], TAX, "d")
    comps = ho.aggregate_companies([a, b, c], TAX, "2026-10-10")
    assert len(comps) == 1  # Foreign Ltd (DE) excluded
    comp = comps[0]
    assert comp["type"] == "company" and comp["title"] == "Acme SA"
    assert comp["sector"] == "steel-aluminium"
    assert comp["identifiers"]["url"] == "https://ror.org/x"
    union = set(a["problem_functions"]) | set(b["problem_functions"]) | set(c["problem_functions"])
    assert set(comp["problem_functions"]) == union


def test_assign_ids_deterministic_papers_before_companies():
    a = ho.work_to_record(_work("https://openalex.org/W1"), SECTORS["textiles"], TAX, "d")
    b = ho.work_to_record(_work("https://openalex.org/W2"), SECTORS["steel-aluminium"], TAX, "d")
    comps = ho.aggregate_companies([a, b], TAX, "d")
    one = ho.assign_ids([a, b], comps, TAX)
    two = ho.assign_ids([b, a], comps, TAX)
    assert one == two
    assert [r["id"] for r in one] == ["map-0001", "map-0002", "map-0003"]
    assert [r["type"] for r in one] == ["paper", "paper", "company"]
    assert one[0]["sector"] == "steel-aluminium"


def test_build_map_keeps_sector_with_most_hits_and_respects_budget():
    work = _work(title="Biomimetic steel and aluminium alloy design")
    calls = []

    def fake(url, params=None):
        calls.append(params)
        return {"results": [work], "meta": {"next_cursor": None}}

    records, summary = ho.build_map(TAX, fake, per_sector=5, max_calls=3, run_date="2026-10-10")
    assert summary["calls"] == 3 == len(calls)
    papers = [r for r in records if r["type"] == "paper"]
    assert len(papers) == 1 and papers[0]["sector"] == "steel-aluminium"
    assert len(calls[0]["filter"]) < 4000
    assert "abstract" not in calls[0]["select"]


def test_cached_fetch_hits_disk_once(tmp_path):
    n = []
    f = ho.cached_fetch(lambda u, p=None: n.append(1) or {"x": 1}, tmp_path)
    assert f("u", {"a": 1, "api_key": "k"}) == f("u", {"a": 1, "api_key": "other"}) == {"x": 1}
    assert len(n) == 1


def test_harvest_sector_follows_cursor_pages_and_caps():
    pages = {
        "*": {"results": [{"id": "A"}, {"id": "B"}], "meta": {"next_cursor": "c2"}},
        "c2": {"results": [{"id": "C"}, {"id": "D"}], "meta": {"next_cursor": "c3"}},
        "c3": {"results": [{"id": "E"}], "meta": {"next_cursor": None}},
    }
    seen = []

    def fake(url, params=None):
        seen.append(params["cursor"])
        return pages[params["cursor"]]

    budget = {"calls": 0, "max": 10}
    works = ho.harvest_sector("energy", fake, 3, budget, None)
    assert [w["id"] for w in works] == ["A", "B", "C"]
    assert seen == ["*", "c2"] and budget["calls"] == 2
    budget = {"calls": 0, "max": 1}
    assert len(ho.harvest_sector("energy", fake, 10, budget, "key")) == 2 and budget["calls"] == 1
