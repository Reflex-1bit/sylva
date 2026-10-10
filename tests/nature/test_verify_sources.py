import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "verify_sources", Path(__file__).resolve().parents[2] / "scripts" / "nature" / "verify_sources.py"
)
vs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vs)


def _record(rid="lib-0001", doi="10.1/ok", sci="Nelumbo nucifera"):
    return {
        "id": rid,
        "kind": "mechanism",
        "title": "Lotus effect",
        "summary": "Water beads on the leaf.",
        "areas": ["form"],
        "functions": ["self-clean"],
        "organism": {"scientific_name": sci, "common_names": ["lotus"]},
        "mechanism": "Micro-roughness plus wax.",
        "trait_type": "morphological",
        "legal_review": "not_required",
        "knowledge_source": "peer_reviewed",
        "consent": "not_applicable",
        "evidence": [
            {"citation": "Barthlott W, Neinhuis C (1997) Purity of the sacred lotus. Planta", "doi": doi}
        ],
        "provenance": {"status": "ai_extracted", "extracted_by": "t", "extracted_on": "2026-10-10"},
        "confidence": "medium",
        "caveat": "Summarised from the literature.",
    }


def test_title_match_accept_and_reject():
    cit = "Barthlott W, Neinhuis C (1997) Purity of the sacred lotus, or escape from contamination"
    assert vs.title_matches("Purity of the sacred lotus, or escape from contamination in biological surfaces", cit)
    assert not vs.title_matches("Gecko adhesion on rough surfaces", cit)
    assert not vs.title_matches("", cit)


def test_licence_mapping():
    lic = lambda u: vs.licence_from_crossref([{"URL": u}])  # noqa: E731
    assert lic("https://creativecommons.org/licenses/by/4.0/") == "CC-BY-4.0"
    assert lic("http://creativecommons.org/licenses/by-sa/3.0/") == "CC-BY-SA-3.0"
    assert lic("https://creativecommons.org/publicdomain/zero/1.0/") == "CC0-1.0"
    assert lic("https://creativecommons.org/licenses/by-nc/4.0/") is None
    assert lic("https://creativecommons.org/licenses/by-nc-nd/4.0/") is None
    assert lic("https://www.springer.com/tdm") is None
    assert vs.licence_from_crossref(None) is None


def test_accept_gbif():
    assert vs.accept_gbif({"matchType": "EXACT", "confidence": 98, "usageKey": 1})
    assert vs.accept_gbif({"matchType": "FUZZY", "confidence": 90, "usageKey": 1})
    assert not vs.accept_gbif({"matchType": "HIGHERRANK", "confidence": 99, "usageKey": 1})
    assert not vs.accept_gbif({"matchType": "EXACT", "confidence": 80, "usageKey": 1})
    assert not vs.accept_gbif({"matchType": "NONE", "confidence": 100})
    assert not vs.accept_gbif(None)


def _fake_fetch(url, params=None):
    if url.startswith(vs.CROSSREF_URL):
        if url.endswith("10.1/ok"):
            return {
                "message": {
                    "title": ["Purity of the sacred lotus"],
                    "issued": {"date-parts": [[1997, 1]]},
                    "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
                }
            }
        if url.endswith("10.1/wrong"):
            return {"message": {"title": ["Completely different topic"], "issued": {"date-parts": [[2001]]}}}
        return None
    if params["name"] == "Nelumbo nucifera":
        return {"usageKey": 42, "matchType": "EXACT", "confidence": 99, "kingdom": "Plantae"}
    return {"matchType": "HIGHERRANK", "confidence": 95, "usageKey": 7}


def test_end_to_end_on_tmp_library(tmp_path, monkeypatch, capsys):
    recs = [
        _record("lib-0001", "10.1/ok"),
        _record("lib-0002", "10.1/wrong", sci="Fakeus unknownus"),
        _record("lib-0003", "10.1/missing"),
    ]
    (tmp_path / "library.json").write_text(json.dumps(recs), encoding="utf-8")
    orig = vs.verify_library
    monkeypatch.setattr(vs, "verify_library", lambda r, **kw: orig(r, fetch=_fake_fetch, sleep=lambda s: None))
    report_path = tmp_path / "report.json"
    assert vs.main(["--data-dir", str(tmp_path), "--report", str(report_path)]) == 0

    out = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in out] == ["lib-0001", "lib-0002", "lib-0003"]
    ev = out[0]["evidence"][0]
    assert ev["verified"] is True and ev["year"] == 1997
    assert ev["licence"] == "CC-BY-4.0" and ev["open_access"] is True
    assert out[0]["organism"]["gbif_usage_key"] == 42
    assert out[0]["organism"]["kingdom"] == "Plantae"
    assert out[1]["evidence"][0]["verified"] is False
    assert out[1]["organism"].get("gbif_usage_key") is None
    assert out[2]["evidence"][0]["verified"] is False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dois_checked"] == 3 and report["verified"] == 1
    assert len(report["failed"]) == 2 and report["organisms_matched"] == 2
    assert "verified=1 failed=2" in capsys.readouterr().out


def test_dry_run_does_not_write(tmp_path, monkeypatch):
    path = tmp_path / "library.json"
    path.write_text(json.dumps([_record()]), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    orig = vs.verify_library
    monkeypatch.setattr(vs, "verify_library", lambda r, **kw: orig(r, fetch=_fake_fetch, sleep=lambda s: None))
    assert vs.main(["--data-dir", str(tmp_path), "--dry-run"]) == 0
    assert path.read_text(encoding="utf-8") == before


def test_invalid_update_keeps_original():
    rec = _record()
    rec["evidence"][0]["supporting_sentence"] = "quoted"
    rec["evidence"][0]["licence"] = "CC-BY-4.0"  # valid before; Crossref says no licence below

    def fetch(url, params=None):
        if url.startswith(vs.CROSSREF_URL):
            return {"message": {"title": ["Purity of the sacred lotus"], "issued": {"date-parts": [[1997]]}}}
        return None

    updated, report = vs.verify_library([rec], fetch=fetch, sleep=lambda s: None)
    assert updated[0] == rec
    assert report["invalid"] and report["invalid"][0]["id"] == "lib-0001"
