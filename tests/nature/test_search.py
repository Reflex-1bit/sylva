import json
import shutil
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.services.nature import embeddings
from app.services.nature.bm25 import BM25
from app.services.nature.embeddings import embed_texts, load_index
from app.services.nature.search import NatureSearch, content_hash, doc_text, rrf
from app.services.nature.store import DEFAULT_DIR, NatureStore
from app.services.nature.text import normalise, tokenize

REAL_STORE = NatureStore(DEFAULT_DIR)


# ── text ─────────────────────────────────────────────────────────────────


def test_accent_fold():
    assert normalise("compresión") == "compresion"
    assert tokenize("Compresión") == ["compresion"]


def test_tokenize_stopwords_short_and_plurals():
    assert tokenize("The sheds of a leaf, de la hoja") == ["shed", "leaf", "hoja"]
    assert tokenize("x 7 ok") == ["ok"]
    assert tokenize("batteries glass leaves") == ["battery", "glass", "leave"]


# ── bm25 ─────────────────────────────────────────────────────────────────


def test_bm25_ranks_obvious_doc_first():
    docs = [tokenize(t) for t in [
        "lotus leaf self cleaning surface",
        "termite mound ventilation",
        "bamboo light stiff stem",
    ]]
    scores = BM25(docs).scores(tokenize("self cleaning leaf"))
    assert int(np.argmax(scores)) == 0
    assert scores[1] == 0 and scores[2] == 0


def test_bm25_unknown_terms_score_zero():
    assert BM25([["a1"], ["b1"]]).scores(["zzz"]).tolist() == [0.0, 0.0]


# ── rrf ──────────────────────────────────────────────────────────────────


def test_rrf_order():
    fused = rrf([[0, 1, 2], [2, 1, 0]])
    assert fused[0] == pytest.approx(fused[2])  # symmetric
    assert fused[0] == pytest.approx(1 / 61 + 1 / 63)
    assert fused[1] == pytest.approx(2 / 62)
    assert fused[0] > fused[1]  # convex: extremes beat the middle
    order = sorted(rrf([[0, 1, 2], [0, 2, 1]]).items(), key=lambda kv: -kv[1])
    assert [i for i, _ in order] == [0, 1, 2]
    assert max(rrf([[5, 6], [6]]).items(), key=lambda kv: kv[1])[0] == 6


# ── embeddings ───────────────────────────────────────────────────────────


def _transport(calls, reject_nested=False, vec=(3.0, 4.0)):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request, body))
        first = body["requests"][0]
        if reject_nested and "embedContentConfig" in first:
            return httpx.Response(400, json={"error": "bad"})
        n = len(body["requests"])
        return httpx.Response(200, json={"embeddings": [{"values": list(vec)} for _ in range(n)]})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_embed_texts_request_and_normalisation():
    calls = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        out = await embed_texts(
            ["body one", "body two"],
            kind="document",
            api_key="K",
            titles=["T1", "T2"],
            dim=2,
            client=client,
        )
    request, body = calls[0]
    assert request.headers["x-goog-api-key"] == "K"
    assert "key=" not in str(request.url)
    assert str(request.url).endswith("models/gemini-embedding-2:batchEmbedContents")
    first = body["requests"][0]
    assert first["model"] == "models/gemini-embedding-2"
    assert first["content"]["parts"][0]["text"] == "title: T1 | text: body one"
    assert first["embedContentConfig"] == {"outputDimensionality": 2}
    assert "taskType" not in first
    assert out.shape == (2, 2)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)
    assert np.allclose(out[0], [0.6, 0.8])


@pytest.mark.asyncio
async def test_embed_query_prefix_and_batching():
    calls = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        await embed_texts(["q"], kind="query", api_key="K", dim=2, client=client)
        assert calls[0][1]["requests"][0]["content"]["parts"][0]["text"] == (
            "task: search result | query: q"
        )
        calls.clear()
        out = await embed_texts(["t"] * 250, kind="document", api_key="K", dim=2, client=client)
    assert [len(b["requests"]) for _, b in calls] == [100, 100, 50]
    assert out.shape == (250, 2)


@pytest.mark.asyncio
async def test_embed_400_retries_once_with_top_level_dimension():
    calls = []
    async with httpx.AsyncClient(transport=_transport(calls, reject_nested=True)) as client:
        out = await embed_texts(["a"], kind="query", api_key="K", dim=2, client=client)
    assert len(calls) == 2
    retry = calls[1][1]["requests"][0]
    assert retry["outputDimensionality"] == 2 and "embedContentConfig" not in retry
    assert out.shape == (1, 2)


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("NATURE_EMBED_MODEL", "other-model")
    assert embeddings.embed_model() == "other-model"


# ── index loading ────────────────────────────────────────────────────────


def _write_index(dirpath: Path, texts, ids, model="gemini-embedding-2", dim=4):
    index = dirpath / "index"
    index.mkdir(parents=True, exist_ok=True)
    np.save(index / "library.npy", np.eye(len(ids), dim, dtype=np.float32))
    (index / "index_meta.json").write_text(
        json.dumps(
            {"model": model, "dim": dim, "dbs": {"library": {"hash": content_hash(texts), "ids": ids}}}
        )
    )


def test_stale_or_mismatched_index_ignored(tmp_path):
    texts = ["a", "b"]
    _write_index(tmp_path, texts, ["x", "y"])
    assert load_index("library", tmp_path, content_hash(texts), dim=4) is not None
    assert load_index("library", tmp_path, content_hash(["a", "changed"]), dim=4) is None
    assert load_index("library", tmp_path, content_hash(texts), dim=768) is None
    assert load_index("library", tmp_path, content_hash(texts), model="m2", dim=4) is None
    assert load_index("map", tmp_path, "h") is None
    assert load_index("library", tmp_path / "nowhere", "h") is None


# ── search over the real data ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_without_key_works_and_normalises():
    hits = await NatureSearch(REAL_STORE).search_library("fog water capture", k=5)
    assert len(hits) == 5
    assert hits[0][1] == 1.0
    assert all(0 < s <= 1.0 for _, s in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


@pytest.mark.asyncio
async def test_quarantined_never_returned():
    all_lib = REAL_STORE.library(servable_only=False)
    quarantined = [r for r in all_lib if not REAL_STORE.is_servable(r)]
    assert quarantined
    search = NatureSearch(REAL_STORE)
    for rec in quarantined:
        for query in (rec.title, rec.id, rec.title + " " + (rec.summary or "")):
            hits = await search.search_library(query, k=100)
            assert rec.id not in {r.id for r, _ in hits}


@pytest.mark.asyncio
async def test_library_filters():
    search = NatureSearch(REAL_STORE)
    hits = await search.search_library("water", functions=["capture-water"], k=50)
    assert hits and all("capture-water" in r.functions for r, _ in hits)
    hits = await search.search_library("surface", kinds=["practice"], k=50)
    assert all(r.kind == "practice" for r, _ in hits)


@pytest.mark.asyncio
async def test_map_search_and_filters():
    search = NatureSearch(REAL_STORE)
    hits = await search.search_map("biomimetic", k=5)
    assert hits and len(hits) <= 5
    target = REAL_STORE.industry_map()[0]
    hits = await search.search_map(
        "the", sector=target.sector, types=[target.type], country=target.country, k=50
    )
    assert all(
        r.sector == target.sector and r.type == target.type and r.country == target.country
        for r, _ in hits
    )
    hits = await search.search_map("energy", year_from=2020, year_to=2022, k=50)
    assert all(r.year is not None and 2020 <= r.year <= 2022 for r, _ in hits)


def test_doc_text_includes_labels():
    tax = REAL_STORE.taxonomy()
    rec = REAL_STORE.get_library("lib-0001")
    text = doc_text(rec, tax)
    assert rec.title in text and "Self-clean" in text and "Shed water" in text


# ── hybrid path with a mocked embedding transport ────────────────────────


@pytest.mark.asyncio
async def test_hybrid_uses_valid_index_and_survives_embedding_failure(tmp_path, monkeypatch):
    for name in ("taxonomy.json", "library.json", "industry_map.json"):
        shutil.copy(DEFAULT_DIR / name, tmp_path / name)
    store = NatureStore(tmp_path)
    from app.services.nature.search import index_documents

    records, texts = index_documents(store)["library"]
    dim = 768
    rng = np.random.default_rng(0)
    matrix = rng.normal(size=(len(records), dim)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    index = tmp_path / "index"
    index.mkdir()
    np.save(index / "library.npy", matrix)
    (index / "index_meta.json").write_text(json.dumps({
        "model": embeddings.embed_model(), "dim": dim,
        "dbs": {"library": {"hash": content_hash(texts), "ids": [r.id for r in records]}},
    }))

    target = 7  # the query vector equals this record's vector
    async def fake_embed(texts_, **kw):
        assert kw["kind"] == "query" and kw["api_key"] == "K"
        return matrix[target : target + 1]

    monkeypatch.setattr("app.services.nature.search.embed_texts", fake_embed)
    hits = await NatureSearch(store).search_library("zzzz unmatched words", k=3, api_key="K")
    assert hits[0][0].id == records[target].id  # BM25 has no hits; cosine alone decides

    async def failing_embed(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.nature.search.embed_texts", failing_embed)
    hits = await NatureSearch(store).search_library("fog water capture", k=3, api_key="K")
    assert len(hits) == 3

    # stale index: change the data, the index is ignored, BM25 only
    lib = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    lib[0]["title"] = lib[0]["title"] + " changed"
    (tmp_path / "library.json").write_text(json.dumps(lib), encoding="utf-8")
    called = []

    async def spy_embed(*a, **kw):
        called.append(1)
        return matrix[:1]

    monkeypatch.setattr("app.services.nature.search.embed_texts", spy_embed)
    await NatureSearch(NatureStore(tmp_path)).search_library("fog water", api_key="K")
    assert not called


# ── acceptance: 5 challenges against the real library.json ───────────────

CHALLENGES = {
    "surface that sheds dirt without detergent": {"self-clean", "shed-water", "prevent-fouling"},
    "reduce cooling energy in a building": {"cool-passively", "regulate-temperature", "insulate"},
    "lighter structural component for cars": {"lighten-structure"},
    "packaging that biodegrades": {"biodegrade"},
    "capture water from air": {"capture-water"},
}


def test_expected_functions_exist_in_taxonomy():
    known = {f["id"] for f in REAL_STORE.taxonomy()["functions"]}
    for expected in CHALLENGES.values():
        assert expected <= known


@pytest.mark.asyncio
@pytest.mark.parametrize("query", list(CHALLENGES))
async def test_challenge_returns_five_relevant_records(query):
    hits = await NatureSearch(REAL_STORE).search_library(query, k=10)
    assert len(hits) >= 5
    assert all(REAL_STORE.is_servable(r) for r, _ in hits)
    top3 = hits[:3]
    assert any(CHALLENGES[query] & set(r.functions) for r, _ in top3)
    assert all(r.evidence for r, _ in hits)  # every hit carries sources
