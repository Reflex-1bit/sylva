import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.catalogue import CatalogueRecord, Group, RawRecord

ROOT = Path(__file__).resolve().parents[3]
CAT = ROOT / "data" / "nature" / "catalogue"
VALIDATE = ROOT / "scripts" / "nature" / "catalogue" / "validate.py"

_SPEC = importlib.util.spec_from_file_location(
    "catalogue_common", ROOT / "scripts" / "nature" / "catalogue" / "common.py")
common = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(common)


def raw(**kw):
    base = dict(id="oa-W123", source="openalex", source_id="W123", kind="paper",
                title="Lotus-inspired coating", source_licence="CC-BY-4.0",
                url="https://openalex.org/W123", harvested_on="2026-10-11")
    base.update(kw)
    return base


def cat(**kw):
    base = dict(id="oa-W123", source="openalex", source_id="W123", kind="paper",
                title="Lotus-inspired coating", source_licence="CC-BY-4.0",
                url="https://openalex.org/W123", primary_sector="chemicals",
                sort_confidence=0.8, sort_reason="cpc:C09 -> chemicals",
                provenance="machine_sorted", licence="CC-BY-4.0")
    base.update(kw)
    return base


# ── models ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rid,source", [
    ("oa-W123", "openalex"), ("pv-US1234567", "patentsview"), ("pv-D987", "patentsview"),
    ("cd-101234", "cordis"), ("ca-green-roofs-2", "climate_adapt")])
def test_id_accepts(rid, source):
    assert RawRecord(**raw(id=rid, source=source)).id == rid


@pytest.mark.parametrize("rid", ["oa-123", "oa-w123", "pv-us123", "cd-abc", "ca-Green", "cat-000001", "W123", "oa-W12x"])
def test_id_rejects(rid):
    with pytest.raises(ValidationError):
        RawRecord(**raw(id=rid))


def test_id_prefix_must_match_source():
    with pytest.raises(ValidationError):
        RawRecord(**raw(id="cd-101", source="openalex"))


def test_summary_licence_gate():
    for ok in ("CC-BY-4.0", "CC0-1.0"):
        assert RawRecord(**raw(summary="text", summary_licence=ok)).summary == "text"
    for bad in ("CC-BY-NC-4.0", "CC-BY-SA-4.0", None):
        with pytest.raises(ValidationError):
            RawRecord(**raw(summary="text", summary_licence=bad))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(summary="text", summary_licence="CC-BY-NC-4.0"))
    assert RawRecord(**raw(summary_licence="CC-BY-NC-4.0")).summary is None  # no summary, no gate


def test_url_must_be_https_and_doi_bare():
    with pytest.raises(ValidationError):
        RawRecord(**raw(url="http://openalex.org/W123"))
    with pytest.raises(ValidationError):
        RawRecord(**raw(doi="https://doi.org/10.1/x"))
    assert RawRecord(**raw(doi="10.1000/xyz")).doi == "10.1000/xyz"


def test_countries_iso2_upper():
    assert RawRecord(**raw(countries=["ES", "PT"])).countries == ["ES", "PT"]
    with pytest.raises(ValidationError):
        RawRecord(**raw(countries=["es"]))


def test_empty_title_rejected():
    with pytest.raises(ValidationError):
        RawRecord(**raw(title=""))


def test_sector_tags_max_three_and_exclude_primary():
    assert CatalogueRecord(**cat(sector_tags=["energy", "textiles", "packaging"]))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(sector_tags=["energy", "textiles", "packaging", "automotive"]))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(sector_tags=["chemicals"]))


def test_group_ids_max_three():
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(group_ids=["a", "b", "c", "d"]))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        RawRecord(**raw(surprise=1))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(keywords=["x"]))
    with pytest.raises(ValidationError):
        RawRecord(**raw(source_codes={"cpc": [], "other": []}))


def test_catalogue_literals_and_confidence():
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(provenance="human"))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(licence="CC-BY-NC-4.0"))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(sort_confidence=1.2))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(sort_reason=""))


def test_group_model():
    g = dict(id="g1", name="Group", country="INT", habitats=["marine"], flagship_taxa=[],
             donate_url="https://example.org/donate", every_org_slug=None,
             source_url="https://example.org", checked_on="2026-10-11")
    assert Group(**g).country == "INT"
    with pytest.raises(ValidationError):
        Group(**{**g, "country": "int"})
    with pytest.raises(ValidationError):
        Group(**{**g, "donate_url": "http://example.org"})


# ── loaders and jsonl ─────────────────────────────────────────────────────────


def test_loaders_on_real_files():
    sectors = common.load_sectors()
    ids = [s.id for s in sectors.sectors]
    tax = json.loads((ROOT / "data" / "nature" / "taxonomy.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in tax["sectors"]] == ids[:10]
    assert len(ids) == 18 and "other" in ids
    assert all(s.min_records == (300 if s.candidate else 0) for s in sectors.sectors)
    assert len(common.load_habitats().habitats) == 14
    assert len(common.load_groups().groups) >= 28  # 2 per habitat at least
    assert common.load_concordance().cpc


def test_taxonomy_sector_ids_match():
    # Keyword lists may diverge from taxonomy.json (ruling F-A); only the ids must match.
    tax = json.loads((ROOT / "data" / "nature" / "taxonomy.json").read_text(encoding="utf-8"))
    ids = [s.id for s in common.load_sectors().sectors]
    assert [s["id"] for s in tax["sectors"]] == ids[:10]


def test_weak_keyword_lists_and_no_generic_strong_words():
    sectors = {s.id: s for s in common.load_sectors().sectors}
    assert all(hasattr(s, "keywords_weak_en") and hasattr(s, "keywords_weak_es") for s in sectors.values())
    for sid, word in [("energy", "energy"), ("packaging", "paper"), ("forestry-fisheries", "forest"),
                      ("health-medical", "tissue"), ("aerospace-transport", "rotor"), ("aerospace-transport", "train")]:
        assert word not in sectors[sid].keywords_en and word in sectors[sid].keywords_weak_en
    # Tuning round TUNE-1 moved wing and ship to aerospace-transport's strong list on purpose (with
    # aircraft, UAV, flight, hull, ...), as corroboration for its subfields; they are no longer weak.
    for word in ("wing", "ship", "drone"):
        assert word in sectors["aerospace-transport"].keywords_en
        assert word not in sectors["aerospace-transport"].keywords_weak_en
    # ... but 'vessel' stays weak (blood vessel); only the phrase 'marine vessel' is strong.
    assert "vessel" in sectors["aerospace-transport"].keywords_weak_en
    assert "vessel" not in sectors["aerospace-transport"].keywords_en
    # Generic flow words stay out of the strong lists.
    assert not {"flow", "fluid"} & set(sectors["aerospace-transport"].keywords_en)
    assert "facade" not in sectors["construction-materials"].keywords_en
    assert "waste management" not in sectors["water-utilities"].keywords_en
    habs = {h.id: h for h in common.load_habitats().habitats}
    assert all(w in habs[h].keywords_weak_en for h, w in [("soil", "ant"), ("polar", "ice"), ("forest", "tree")])


def test_concordance_decisions_and_notes():
    conc = common.load_concordance()
    cpc = {r.prefix: r.sector for r in conc.cpc}
    assert cpc["C12N"] == "chemicals" and cpc["C12G"] == "agrifood" and "C12" not in cpc
    assert "B63J" not in cpc and cpc["G01"] == "electronics-ict" and cpc["C23"] == "chemicals"
    assert cpc["B82Y"] == "chemicals"
    sub = {r.name: r for r in conc.openalex_subfield}
    assert "Plant Science" not in sub and sub["Dermatology"].sector == "health-medical"
    assert sub["Polymers and Plastics"].sector == "chemicals" and sub["Pollution"].sector == "waste-recycling"
    assert sub["Information Systems"].strength == "medium" and sub["Food Science"].strength == "strong"
    for phrase in ("whole-word", "longest prefix", "unmapped", "0.6", "0.25", "tie", "medium"):
        assert phrase in conc.notes


def test_subfield_snapshot_covers_sectors():
    names = set((ROOT / "scripts" / "nature" / "catalogue" / "openalex_subfields.txt").read_text(encoding="utf-8").splitlines())
    assert len(names) > 200
    for s in common.load_sectors().sectors:
        assert set(s.openalex_subfields) <= names


def test_whitespace_title_year_range_and_dates():
    for bad in (dict(title="   "), dict(source_id=" "), dict(year=-5), dict(year=99999),
                dict(harvested_on="2026-10-11T00:00:00"), dict(harvested_on="11/10/2026")):
        with pytest.raises(ValidationError):
            RawRecord(**raw(**bad))
    assert RawRecord(**raw(year=2024)).year == 2024


def test_duplicate_functions_and_groups_rejected():
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(functions=["self-clean", "self-clean"]))
    with pytest.raises(ValidationError):
        CatalogueRecord(**cat(group_ids=["a", "a"]))

def test_jsonl_round_trip(tmp_path):
    recs = [RawRecord(**raw(id=f"oa-W{i}", source_id=f"W{i}", title=f"Título {i}")) for i in range(3)]
    path = tmp_path / "raw" / "openalex" / "records.jsonl"
    assert common.write_jsonl(path, recs) == 3
    assert path.read_bytes()[:3] != b"\xef\xbb\xbf"
    assert common.read_jsonl(path, RawRecord) == recs
    assert common.read_jsonl(tmp_path / "missing.jsonl", RawRecord) == []


def test_read_jsonl_reports_line(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps(raw(id="bad")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="r.jsonl:1"):
        common.read_jsonl(path, RawRecord)


def test_openalex_licence():
    assert common.openalex_licence("cc-by") == "CC-BY-4.0"
    assert common.openalex_licence("cc0") == "CC0-1.0"
    assert common.openalex_licence("cc-by-nc") == "CC-BY-NC"
    assert common.openalex_licence("cc-by-sa") == "CC-BY-SA"
    assert common.openalex_licence(None) is None
    assert common.openalex_licence("") is None
    assert common.openalex_licence("   ") is None


def test_today_is_iso():
    assert len(common.today()) == 10


# ── validate.py ───────────────────────────────────────────────────────────────


def run_validate(*args):
    return subprocess.run([sys.executable, str(VALIDATE), *args], cwd=ROOT, capture_output=True, text=True)


def test_validate_passes_on_real_files():
    r = run_validate()
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


def test_validate_fails_on_bad_concordance_sector(tmp_path):
    d = tmp_path / "cat"
    shutil.copytree(CAT, d, ignore=shutil.ignore_patterns("raw", "build"))
    conc = json.loads((d / "concordance.json").read_text(encoding="utf-8"))
    conc["cpc"][0]["sector"] = "no-such-sector"
    (d / "concordance.json").write_text(json.dumps(conc), encoding="utf-8")
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1
    assert "no-such-sector" in r.stderr


def test_validate_fails_when_taxonomy_sector_missing(tmp_path):
    d = tmp_path / "cat"
    shutil.copytree(CAT, d, ignore=shutil.ignore_patterns("raw", "build"))
    s = json.loads((d / "sectors.json").read_text(encoding="utf-8"))
    s["sectors"] = [x for x in s["sectors"] if x["id"] != "packaging"]
    (d / "sectors.json").write_text(json.dumps(s), encoding="utf-8")
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1
    assert "packaging" in r.stderr


def test_validate_fails_on_duplicate_habitat(tmp_path):
    d = tmp_path / "cat"
    shutil.copytree(CAT, d, ignore=shutil.ignore_patterns("raw", "build"))
    h = json.loads((d / "habitats.json").read_text(encoding="utf-8"))
    h["habitats"].append(h["habitats"][0])
    (d / "habitats.json").write_text(json.dumps(h), encoding="utf-8")
    assert run_validate("--data-dir", str(d)).returncode == 1


def _wrapper(records):
    return {"licence": "CC-BY-4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Sylva", "version": "2026-10-11", "db": "catalogue", "records": records}


def test_validate_build(tmp_path):
    (tmp_path / "catalogue.json").write_text(json.dumps(_wrapper([
        cat(area="materials", functions=["self-clean"], habitat_id="marine", sector_tags=["energy"])])),
        encoding="utf-8")
    r = run_validate("--build", str(tmp_path))
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("change", [
    {"primary_sector": "nope"}, {"habitat_id": "nope"}, {"area": "nope"},
    {"functions": ["nope"]}, {"group_ids": ["nope"]}, {"sector_tags": ["nope"]},
])
def test_validate_build_cross_refs(tmp_path, change):
    (tmp_path / "catalogue.json").write_text(json.dumps(_wrapper([cat(**change)])), encoding="utf-8")
    r = run_validate("--build", str(tmp_path))
    assert r.returncode == 1
    assert "nope" in r.stderr


def test_validate_build_bad_record_and_duplicate(tmp_path):
    (tmp_path / "catalogue.json").write_text(json.dumps(_wrapper([cat(), cat()])), encoding="utf-8")
    assert run_validate("--build", str(tmp_path)).returncode == 1
    (tmp_path / "catalogue.json").write_text(json.dumps(_wrapper([cat(provenance="x")])), encoding="utf-8")
    assert run_validate("--build", str(tmp_path)).returncode == 1


def _copy_cat(tmp_path):
    d = tmp_path / "cat"
    shutil.copytree(CAT, d, ignore=shutil.ignore_patterns("raw", "build"))
    return d


def test_validate_fails_when_concordance_row_not_in_sector_list(tmp_path):
    d = _copy_cat(tmp_path)
    conc = json.loads((d / "concordance.json").read_text(encoding="utf-8"))
    conc["cpc"][0]["sector"] = "energy"  # valid sector, but not that sector's own list
    (d / "concordance.json").write_text(json.dumps(conc), encoding="utf-8")
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "not in sector" in r.stderr


def test_validate_fails_on_duplicate_concordance_key(tmp_path):
    d = _copy_cat(tmp_path)
    conc = json.loads((d / "concordance.json").read_text(encoding="utf-8"))
    conc["openalex_subfield"].append(conc["openalex_subfield"][0])
    (d / "concordance.json").write_text(json.dumps(conc), encoding="utf-8")
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "duplicate key" in r.stderr


def test_validate_fails_when_key_in_two_sectors(tmp_path):
    d = _copy_cat(tmp_path)
    s = json.loads((d / "sectors.json").read_text(encoding="utf-8"))
    by_id = {x["id"]: x for x in s["sectors"]}
    by_id["energy"]["cpc_prefixes"].append(by_id["packaging"]["cpc_prefixes"][0])
    (d / "sectors.json").write_text(json.dumps(s), encoding="utf-8")
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "several sectors" in r.stderr


def test_validate_fails_on_unknown_openalex_subfield(tmp_path):
    d = _copy_cat(tmp_path)
    s = json.loads((d / "sectors.json").read_text(encoding="utf-8"))
    s["sectors"][0]["openalex_subfields"].append("Metalz and Alloys")
    (d / "sectors.json").write_text(json.dumps(s), encoding="utf-8")
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "Metalz" in r.stderr