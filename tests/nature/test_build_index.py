import importlib.util
import json
import shutil
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.services.nature.embeddings import load_index
from app.services.nature.search import content_hash, index_documents
from app.services.nature.store import DEFAULT_DIR, NatureStore

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "nature" / "build_index.py"
spec = importlib.util.spec_from_file_location("build_index", SCRIPT)
build_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_index)


def test_no_key_prints_message_and_exits_zero(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert build_index.main(["--data-dir", str(tmp_path)]) == 0
    assert "BM25" in capsys.readouterr().out
    assert not (tmp_path / "index").exists()


@pytest.mark.asyncio
async def test_build_writes_loadable_index(tmp_path):
    for name in ("taxonomy.json", "library.json", "industry_map.json"):
        shutil.copy(DEFAULT_DIR / name, tmp_path / name)

    def handler(request: httpx.Request) -> httpx.Response:
        n = len(json.loads(request.content)["requests"])
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] * 768} for _ in range(n)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        meta = await build_index.build(tmp_path, "K", client=client)

    store = NatureStore(tmp_path)
    docs = index_documents(store)
    assert meta["dim"] == 768
    for name, (records, texts) in docs.items():
        loaded = load_index(name, tmp_path, content_hash(texts))
        assert loaded is not None
        matrix, ids = loaded
        assert ids == [r.id for r in records]
        assert matrix.shape == (len(records), 768)
        assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)
    # the quarantined records are not embedded
    assert len(meta["dbs"]["library"]["ids"]) == len(store.library(servable_only=True))
