import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.nature import AskRequest, Evidence, LibraryRecord, MapRecord
from app.services.nature.store import DEFAULT_DIR, NatureDataError, NatureStore

REPO = Path(__file__).resolve().parents[2]

TAXONOMY = {
    "version": "0.1.0",
    "licence": "CC-BY-4.0",
    "areas": [{"id": "form", "label": "Form", "question": "q"}],
    "functions": [{"id": "self-clean", "group": "protect-surfaces", "label": "x",
                   "keywords_en": ["dirt"], "keywords_es": ["suciedad"]}],
    "sectors": [{"id": "packaging", "label_en": "P", "label_es": "E", "nace_rev21_divisions": ["17"],
                 "keywords_en": [], "keywords_es": []}],
}

LIB = {
    "id": "lib-0001", "kind": "mechanism", "title": "Lotus effect",
    "summary": "Micro-textured leaves shed water and dirt.",
    "areas": ["form"], "functions": ["self-clean"], "sector_tags": ["packaging"],
    "mechanism": "Micro and nano roughness traps air so droplets roll off.",
    "trait_type": "morphological", "legal_review": "not_required",
    "knowledge_source": "peer_reviewed", "consent": "not_applicable",
    "evidence": [{"citation": "A et al. 2020", "doi": "10.1/x"}],
    "provenance": {"status": "ai_extracted", "extracted_by": "t", "extracted_on": "2026-01-01"},
    "confidence": "medium", "caveat": "Lab data only.",
}

MAP = {
    "id": "map-0001", "type": "paper", "title": "Paper", "sector": "packaging",
    "problem_functions": ["self-clean"], "areas": ["form"], "nature_link": "biomimetic",
    "country": "ES", "library_links": ["lib-0001"],
    "source": {"name": "OpenAlex", "licence": "CC0", "retrieved_on": "2026-01-01"},
    "provenance": {"status": "ai_extracted", "extracted_by": "t", "extracted_on": "2026-01-01"},
}


def lib(**changes):
    rec = copy.deepcopy(LIB)
    rec.update(changes)
    return rec


def make_store(tmp_path, library=None, industry=None, taxonomy=None):
    (tmp_path / "taxonomy.json").write_text(json.dumps(taxonomy or TAXONOMY), encoding="utf-8")
    (tmp_path / "library.json").write_text(json.dumps(library or []), encoding="utf-8")
    (tmp_path / "industry_map.json").write_text(json.dumps(industry or []), encoding="utf-8")
    return NatureStore(tmp_path)


# ── model validators ──────────────────────────────────────────────────────────

def test_valid_records_parse():
    LibraryRecord.model_validate(LIB)
    MapRecord.model_validate(MAP)


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        LibraryRecord.model_validate(lib(surprise=1))


def test_mechanism_kind_requires_mechanism():
    with pytest.raises(ValidationError, match="mechanism"):
        LibraryRecord.model_validate(lib(mechanism=None))
    LibraryRecord.model_validate(lib(kind="material", mechanism=None))


def test_biochemical_not_required_rejected():
    with pytest.raises(ValidationError, match="legal_review"):
        LibraryRecord.model_validate(lib(trait_type="biochemical", legal_review="not_required"))


def test_traditional_not_applicable_consent_rejected():
    with pytest.raises(ValidationError, match="consent"):
        LibraryRecord.model_validate(lib(knowledge_source="traditional", consent="not_applicable"))


def test_supporting_sentence_needs_open_licence():
    with pytest.raises(ValidationError, match="supporting_sentence"):
        Evidence(citation="c", supporting_sentence="s", licence="publisher-copyright")
    with pytest.raises(ValidationError):
        Evidence(citation="c", supporting_sentence="s")
    assert Evidence(citation="c", supporting_sentence="s", licence="CC-BY-4.0")
    assert Evidence(citation="c", supporting_sentence="s", licence="CC0-1.0")


@pytest.mark.parametrize(
    "licence", ["CC-BY-NC-4.0", "CC-BY-SA-4.0", "CC-BY-ND-4.0", "CC-BY-NC-ND-4.0", "CC-BYX", "CC0-2.0"]
)
def test_supporting_sentence_rejected_under_restricted_cc_licences(licence):
    with pytest.raises(ValidationError, match="supporting_sentence"):
        Evidence(citation="c", supporting_sentence="s", licence=licence)
    assert Evidence(citation="c", licence=licence).licence == licence  # the id itself is kept


@pytest.mark.parametrize("licence", ["CC-BY-4.0", "CC-BY", "CC0-1.0", "CC0"])
def test_supporting_sentence_accepted_under_cc_by_and_cc0(licence):
    assert Evidence(citation="c", supporting_sentence="s", licence=licence).supporting_sentence == "s"


def test_expert_validated_needs_validator():
    prov = {"status": "expert_validated", "extracted_by": "t", "extracted_on": "2026-01-01"}
    with pytest.raises(ValidationError, match="validated_by"):
        LibraryRecord.model_validate(lib(provenance=prov))
    prov.update(validated_by="Dr X", validated_on="2026-02-01")
    LibraryRecord.model_validate(lib(provenance=prov))


def test_empty_caveat_and_evidence_rejected():
    with pytest.raises(ValidationError):
        LibraryRecord.model_validate(lib(caveat=""))
    with pytest.raises(ValidationError):
        LibraryRecord.model_validate(lib(evidence=[]))


def test_ask_request_bounds():
    assert AskRequest(challenge="capture water from air").top_k == 8
    with pytest.raises(ValidationError):
        AskRequest(challenge="short")
    with pytest.raises(ValidationError):
        AskRequest(challenge="long enough challenge", top_k=21)


# ── serving gate ──────────────────────────────────────────────────────────────

def test_serving_gate_hides_pending_legal_and_unconsented_traditional(tmp_path):
    records = [
        lib(id="lib-0001"),
        lib(id="lib-0002", trait_type="genetic", legal_review="pending"),
        lib(id="lib-0003", trait_type="biochemical", legal_review="cleared"),
        lib(id="lib-0004", knowledge_source="traditional", consent="pending"),
        lib(id="lib-0005", knowledge_source="traditional", consent="granted"),
    ]
    store = make_store(tmp_path, records)
    assert [r.id for r in store.library()] == ["lib-0001", "lib-0003", "lib-0005"]
    assert len(store.library(servable_only=False)) == 5
    assert store.get_library("lib-0002") is None
    assert store.get_library("lib-0002", servable_only=False).id == "lib-0002"
    assert store.get_library("lib-0001").id == "lib-0001"


# ── referential checks ────────────────────────────────────────────────────────

def test_unknown_function_fails_referential_check(tmp_path):
    store = make_store(tmp_path, [lib(functions=["levitate"])])
    with pytest.raises(NatureDataError, match="unknown function 'levitate'"):
        store.library()


def test_all_problems_listed_and_duplicates_found(tmp_path):
    store = make_store(
        tmp_path,
        [lib(areas=["nope"]), lib()],
        [{**MAP, "sector": "ghost", "library_links": ["lib-9999"]}],
    )
    with pytest.raises(NatureDataError) as exc:
        store.stats()
    text = str(exc.value)
    assert "unknown area 'nope'" in text
    assert "duplicate id lib-0001" in text
    assert "unknown sector 'ghost'" in text
    assert "library_link 'lib-9999' not found" in text
    assert len(exc.value.problems) == 4


def test_schema_error_reported_as_nature_data_error(tmp_path):
    store = make_store(tmp_path, [lib(surprise=1)])
    with pytest.raises(NatureDataError, match="surprise"):
        store.library()


def test_wrong_top_level_shapes_are_nature_data_errors(tmp_path):
    with pytest.raises(NatureDataError, match="taxonomy.json: top level must be an object"):
        make_store(tmp_path, taxonomy=["not", "a", "dict"]).taxonomy()
    (tmp_path / "taxonomy.json").write_text(json.dumps(TAXONOMY), encoding="utf-8")
    (tmp_path / "library.json").write_text("{}", encoding="utf-8")
    (tmp_path / "industry_map.json").write_text('"x"', encoding="utf-8")
    with pytest.raises(NatureDataError) as exc:
        NatureStore(tmp_path).library()
    assert "library.json: top level must be an array" in str(exc.value)
    assert "industry_map.json: top level must be an array" in str(exc.value)


def test_bad_utf8_and_unreadable_files_are_nature_data_errors(tmp_path):
    store = make_store(tmp_path, [lib()])
    (tmp_path / "library.json").write_bytes(b'[{"id": "\xff\xfe"}]')
    with pytest.raises(NatureDataError, match="library.json: not valid UTF-8"):
        store.library()
    (tmp_path / "library.json").unlink()
    (tmp_path / "library.json").mkdir()  # reading a directory is an OSError
    with pytest.raises(NatureDataError, match="library.json: unreadable"):
        NatureStore(tmp_path).library()


def test_cold_start_is_safe_across_threads(tmp_path):
    import threading

    store = make_store(tmp_path, [lib()], [MAP])
    start = threading.Barrier(8)
    errors, sizes = [], []

    def worker():
        start.wait()
        try:
            sizes.append((len(store.library()), len(store.industry_map())))
        except Exception as exc:  # pragma: no cover - only on a race
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and set(sizes) == {(1, 1)}


def test_valid_map_links_load(tmp_path):
    store = make_store(tmp_path, [lib()], [MAP])
    assert store.get_map("map-0001").library_links == ["lib-0001"]
    assert store.get_map("missing") is None


def test_reload_picks_up_changes(tmp_path):
    store = make_store(tmp_path, [lib()])
    assert len(store.library()) == 1
    (tmp_path / "library.json").write_text("[]", encoding="utf-8")
    assert len(store.library()) == 1
    store.reload()
    assert store.library() == []


# ── evidence grade ────────────────────────────────────────────────────────────

def grade(**changes):
    return NatureStore.evidence_grade(LibraryRecord.model_validate(lib(**changes)))


def test_evidence_grades():
    two = [{"citation": "a", "doi": "10.1/a"}, {"citation": "b", "url": "https://x.org"}]
    measured = [{"metric": "angle", "value": 160.0, "units": "deg"}]
    unmeasured = [{"metric": "angle", "value": None}]
    assert grade() == "weak"
    assert grade(performance=unmeasured) == "weak"
    assert grade(performance=measured) == "moderate"
    assert grade(evidence=two) == "moderate"
    assert grade(evidence=two, performance=unmeasured) == "moderate"
    assert grade(evidence=two, performance=measured) == "strong"
    assert grade(evidence=[{"citation": "a"}, {"citation": "b"}], performance=measured) == "moderate"
    assert grade(popular_claim_note="myth", evidence=two, performance=measured) == "contested"
    disputed = {"status": "disputed", "extracted_by": "t", "extracted_on": "2026-01-01"}
    assert grade(provenance=disputed, evidence=two, performance=measured) == "contested"


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats_counts(tmp_path):
    validated = {"status": "expert_validated", "extracted_by": "t", "extracted_on": "2026-01-01",
                 "validated_by": "Dr X", "validated_on": "2026-02-01"}
    records = [
        lib(id="lib-0001", performance=[{"metric": "m", "value": 1.0}], provenance=validated),
        lib(id="lib-0002", kind="material", mechanism=None),
        lib(id="lib-0003", trait_type="genetic", legal_review="pending"),
    ]
    stats = make_store(tmp_path, records, [MAP]).stats()
    assert stats["version"] == "0.1.0" and stats["licence"] == "CC-BY-4.0"
    assert stats["library_total"] == 3
    assert stats["library_served"] == 2
    assert stats["quarantined"] == 1
    assert stats["by_status"] == {"expert_validated": 1, "ai_extracted": 1}
    assert stats["by_area"] == {"form": 2}
    assert stats["by_kind"] == {"mechanism": 1, "material": 1}
    assert stats["with_measured_values"] == 1
    assert stats["validated_share"] == 0.5
    assert stats["measured_share"] == 0.5
    assert stats["map_total"] == 1
    assert stats["map_by_sector"] == {"packaging": 1}
    assert stats["map_by_type"] == {"paper": 1}
    assert stats["map_by_country"] == {"ES": 1}


def test_stats_empty_store_has_zero_shares(tmp_path):
    stats = make_store(tmp_path).stats()
    assert stats["library_total"] == 0 and stats["validated_share"] == 0.0


# ── shipped data ──────────────────────────────────────────────────────────────

def test_default_dir_is_repo_data_nature():
    assert DEFAULT_DIR == REPO / "data" / "nature"
    assert (DEFAULT_DIR / "taxonomy.json").is_file()


def test_shipped_taxonomy_shape():
    tax = NatureStore().taxonomy()
    assert tax["version"] == "0.1.0" and tax["licence"] == "CC-BY-4.0"
    assert [a["id"] for a in tax["areas"]] == [
        "form", "process", "materials", "energy", "circularity", "systems", "place"]
    groups = {g["id"] for g in tax["function_groups"]}
    assert len(groups) == 12 and len(tax["functions"]) >= 40
    ids = [f["id"] for f in tax["functions"]]
    assert len(ids) == len(set(ids))
    for f in tax["functions"]:
        assert f["group"] in groups
        # ES lists carry accented and unaccented spellings of the same word
        assert 4 <= len(f["keywords_en"]) <= 12 and 4 <= len(f["keywords_es"]) <= 16
    assert len(tax["sectors"]) == 10
    assert [t["level"] for t in tax["trl"]["levels"]] == list(range(1, 10))


@pytest.mark.parametrize("phrase,function_id", [
    ("dirt", "self-clean"), ("without detergent", "self-clean"),
    ("cooling energy", "cool-passively"), ("lighter structural component", "lighten-structure"),
    ("packaging that biodegrades", "biodegrade"), ("water from air", "capture-water"),
])
def test_challenge_phrases_map_to_functions(phrase, function_id):
    fn = next(f for f in NatureStore().taxonomy()["functions"] if f["id"] == function_id)
    assert phrase in fn["keywords_en"]


def test_validate_script_exits_zero():
    result = subprocess.run([sys.executable, "scripts/nature/validate_db.py"],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_validate_script_fails_on_bad_data(tmp_path):
    make_store(tmp_path, [lib(functions=["levitate"])])
    result = subprocess.run([sys.executable, "scripts/nature/validate_db.py", "--data-dir", str(tmp_path)],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 1
    assert "levitate" in result.stderr
