import asyncio
import copy
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import nature as router_mod
from app.routers.nature import get_search
from app.services.nature.search import NatureSearch
from app.services.nature.store import NatureStore, get_store
from tests.nature.test_matcher_rag import LIB, MAP, TAXONOMY, lib, mp

API = "/api/v1/nature"

QUARANTINED = lib(
    id="lib-0003",
    title="Quarantined enzyme coating",
    trait_type="biochemical",
    legal_review="pending",
)


def build_store(tmp_path, library, industry):
    (tmp_path / "taxonomy.json").write_text(json.dumps(TAXONOMY), encoding="utf-8")
    (tmp_path / "library.json").write_text(json.dumps(library), encoding="utf-8")
    (tmp_path / "industry_map.json").write_text(json.dumps(industry), encoding="utf-8")
    return NatureStore(tmp_path)


@pytest.fixture
def client(tmp_path, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    library = [
        lib(),
        lib(
            id="lib-0002",
            kind="practice",
            title="Termite mound ventilation",
            summary="Passive cooling through mound chimneys.",
            areas=["form"],
            functions=["cool-passively"],
            mechanism=None,
            organism=None,
            performance=[],
            evidence=[{"citation": "A"}],
            known_products=["Cooling tower"],
        ),
        QUARANTINED,
    ]
    industry = [
        mp(library_links=["lib-0001", "lib-0003"]),
        mp(id="map-0002", sector="textiles", title="Textile dirt shedding", year=2020,
           problem_functions=["self-clean"], country="PT"),
    ]
    store = build_store(tmp_path, library, industry)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_search] = lambda: NatureSearch(store)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_meta(client):
    body = client.get(f"{API}/meta").json()
    assert body["licence"]["name"] == "CC BY 4.0"
    assert body["licence"]["url"].startswith("https://creativecommons.org/licenses/by/4.0")
    assert body["licence"]["attribution"]
    assert body["version"] == "0.1.0"
    assert body["taxonomy"]["functions"]


def test_stats_counts_quarantine_without_ids(client):
    body = client.get(f"{API}/stats").json()
    assert body["library_total"] == 3
    assert body["library_served"] == 2
    assert body["quarantined"] == 1
    assert "lib-0003" not in json.dumps(body)


def test_library_browse_sorted_by_id_with_fit_zero(client):
    hits = client.get(f"{API}/library").json()
    assert [h["record"]["id"] for h in hits] == ["lib-0001", "lib-0002"]
    for h in hits:
        assert h["breakdown"]["fit"] == 0.0
        assert h["breakdown"]["retrieval_none"] == 1.0
    assert hits[0]["evidence_grade"] == "strong"


def test_library_filters(client):
    ids = lambda p: [h["record"]["id"] for h in client.get(f"{API}/library", params=p).json()]
    assert ids({"kind": "practice"}) == ["lib-0002"]
    assert ids({"function": "self-clean"}) == ["lib-0001"]
    assert ids({"area": "form", "limit": 1}) == ["lib-0001"]
    assert ids({"status": "ai_extracted"}) == ["lib-0001", "lib-0002"]


@pytest.mark.parametrize(
    "param", [{"area": "x"}, {"function": "x"}, {"sector": "x"}, {"kind": "x"}, {"status": "x"}]
)
def test_library_unknown_filter_is_422(client, param):
    assert client.get(f"{API}/library", params=param).status_code == 422


def test_library_limit_bounds(client):
    assert client.get(f"{API}/library", params={"limit": 0}).status_code == 422
    assert client.get(f"{API}/library", params={"limit": 101}).status_code == 422


def test_library_query_ranks_and_hides_quarantined(client):
    hits = client.get(f"{API}/library", params={"q": "water repellent coating"}).json()
    ids = [h["record"]["id"] for h in hits]
    assert ids[0] == "lib-0001"
    assert "lib-0003" not in ids
    assert "retrieval_none" not in hits[0]["breakdown"]
    assert hits[0]["breakdown"]["fit"] > 0


def test_library_record_detail(client):
    body = client.get(f"{API}/library/lib-0001").json()
    assert body["record"]["id"] == "lib-0001"
    assert body["evidence_grade"] == "strong"
    assert body["sectors"]["using"] == ["packaging"]


def test_quarantined_and_missing_library_ids_are_404(client):
    assert client.get(f"{API}/library/lib-0003").status_code == 404
    assert client.get(f"{API}/library/lib-9999").status_code == 404


def test_map_browse_filters_and_hides_quarantined_links(client):
    hits = client.get(f"{API}/map").json()
    assert [h["record"]["id"] for h in hits] == ["map-0001", "map-0002"]
    assert hits[0]["record"]["library_links"] == ["lib-0001"]
    assert [h["record"]["id"] for h in client.get(f"{API}/map", params={"country": "pt"}).json()] == ["map-0002"]
    assert [h["record"]["id"] for h in client.get(f"{API}/map", params={"year_from": 2019}).json()] == ["map-0002"]
    assert [h["record"]["id"] for h in client.get(f"{API}/map", params={"sector": "packaging"}).json()] == ["map-0001"]
    assert client.get(f"{API}/map", params={"sector": "nope"}).status_code == 422
    assert client.get(f"{API}/map", params={"type": "nope"}).status_code == 422


def test_map_query(client):
    hits = client.get(f"{API}/map", params={"q": "carton water coatings"}).json()
    assert hits[0]["record"]["id"] == "map-0001"
    assert "lib-0003" not in json.dumps(hits)


def test_map_record_detail(client):
    body = client.get(f"{API}/map/map-0001").json()
    assert body["library_links"] == ["lib-0001"]
    assert client.get(f"{API}/map/map-9999").status_code == 404


def test_sectors_with_counts(client):
    sectors = {s["id"]: s for s in client.get(f"{API}/sectors").json()}
    assert sectors["packaging"]["map_count"] == 1
    assert sectors["textiles"]["map_count"] == 1


def test_sector_gaps(client):
    body = client.get(f"{API}/sectors/textiles/gaps").json()
    assert body["sector_id"] == "textiles"
    assert "lib-0003" not in json.dumps(body)
    assert client.get(f"{API}/sectors/nope/gaps").status_code == 404


def test_ask_falls_back_without_key(client):
    resp = client.post(f"{API}/ask", json={"challenge": "We need a water repellent carton coating"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"].startswith("fallback")
    assert body["library_hits"][0]["record"]["id"] == "lib-0001"
    assert "lib-0003" not in json.dumps(body)


def test_ask_validation_error(client):
    assert client.post(f"{API}/ask", json={"challenge": "short"}).status_code == 422


def test_ask_timeout_is_504(client, monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(router_mod.rag, "ask", slow)
    monkeypatch.setattr(router_mod, "ASK_TIMEOUT_S", 0.05)
    resp = client.post(f"{API}/ask", json={"challenge": "We need a water repellent coating"})
    assert resp.status_code == 504


def test_export_json_excludes_quarantine_and_sets_headers(client):
    resp = client.get(f"{API}/export/library")
    assert resp.status_code == 200
    assert resp.headers["X-License"] == "CC-BY-4.0"
    assert resp.headers["Content-Disposition"].startswith("attachment")
    assert [r["id"] for r in resp.json()] == ["lib-0001", "lib-0002"]


def test_export_csv_header_and_flattening(client):
    resp = client.get(f"{API}/export/library", params={"format": "csv"})
    assert resp.headers["X-License"] == "CC-BY-4.0"
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["Content-Disposition"].startswith("attachment")
    rows = list(csv.reader(io.StringIO(resp.text)))
    header = rows[0]
    assert header[:3] == ["id", "kind", "title"]
    assert len(rows) == 3
    first = dict(zip(header, rows[1]))
    assert first["functions"] == "shed-water; self-clean"
    assert json.loads(first["organism"])["scientific_name"] == "Nelumbo nucifera"
    assert "lib-0003" not in resp.text


def test_export_map_all_records_with_filtered_links(client):
    resp = client.get(f"{API}/export/industry_map", params={"format": "csv"})
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [r["id"] for r in rows] == ["map-0001", "map-0002"]
    assert rows[0]["library_links"] == "lib-0001"


def test_export_bad_db_and_format(client):
    assert client.get(f"{API}/export/nope").status_code == 404
    assert client.get(f"{API}/export/library", params={"format": "xml"}).status_code == 422


def test_missing_data_is_503(tmp_path):
    store = NatureStore(tmp_path / "missing")
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_search] = lambda: NatureSearch(store)
    try:
        c = TestClient(app)
        assert c.get(f"{API}/meta").status_code == 503
        assert c.get(f"{API}/library").status_code == 503
        assert c.post(f"{API}/ask", json={"challenge": "water repellent coating"}).status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_real_data_serves_without_quarantined_records():
    get_store.cache_clear()
    c = TestClient(app)
    store = get_store()
    quarantined = {r.id for r in store.library(servable_only=False)} - {r.id for r in store.library()}
    assert quarantined
    for rid in quarantined:
        assert c.get(f"{API}/library/{rid}").status_code == 404
    csv_text = c.get(f"{API}/export/library", params={"format": "csv"}).text
    exported = {row["id"] for row in csv.DictReader(io.StringIO(csv_text))}
    assert not exported & quarantined
    assert c.get("/health").json()["version"] == "0.3.0"
