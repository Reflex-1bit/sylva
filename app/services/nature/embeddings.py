"""
Sylva - Nature arm: Gemini embeddings client and on-disk index loader.

gemini-embedding-2 takes no taskType; the task is encoded in the text prefix.
Auth is the x-goog-api-key header (never the query string).
"""

import json
import os
from pathlib import Path
from typing import Literal, Optional

import httpx
import numpy as np

DEFAULT_MODEL = "gemini-embedding-2"
DEFAULT_DIM = 768
BATCH_SIZE = 100
_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def embed_model() -> str:
    return os.environ.get("NATURE_EMBED_MODEL") or DEFAULT_MODEL


def format_text(text: str, kind: Literal["document", "query"], title: Optional[str] = None) -> str:
    if kind == "query":
        return f"task: search result | query: {text}"
    return f"title: {title or 'none'} | text: {text}"


def _request_body(texts: list[str], model: str, dim: int, nested: bool) -> dict:
    reqs = []
    for t in texts:
        r: dict = {"model": f"models/{model}", "content": {"parts": [{"text": t}]}}
        if nested:
            r["embedContentConfig"] = {"outputDimensionality": dim}
        else:
            r["outputDimensionality"] = dim
        reqs.append(r)
    return {"requests": reqs}


async def _post_batch(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    texts: list[str],
    model: str,
    dim: int,
    nested: list[bool],
) -> list[list[float]]:
    """POST one batch. `nested` is a one-item state shared across the batches of a
    call: once the nested form is rejected (400), the top-level form is used for
    every later batch without retrying."""
    resp = await client.post(url, headers=headers, json=_request_body(texts, model, dim, nested[0]))
    if resp.status_code == 400 and nested[0]:
        nested[0] = False
        resp = await client.post(url, headers=headers, json=_request_body(texts, model, dim, False))
    resp.raise_for_status()
    vectors = [e["values"] for e in resp.json()["embeddings"]]
    if len(vectors) != len(texts):
        raise ValueError(f"expected {len(texts)} embeddings, got {len(vectors)}")
    return vectors


async def embed_texts(
    texts: list[str],
    *,
    kind: Literal["document", "query"],
    api_key: str,
    titles: Optional[list[str]] = None,
    model: Optional[str] = None,
    dim: int = DEFAULT_DIM,
    client: Optional[httpx.AsyncClient] = None,
) -> np.ndarray:
    """Return an (n, dim) float32 matrix of L2-normalised embeddings, in input order."""
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)
    model = model or embed_model()
    formatted = [format_text(t, kind, titles[i] if titles else None) for i, t in enumerate(texts)]
    url = f"{_BASE}/{model}:batchEmbedContents"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=60.0)
    try:
        vectors: list[list[float]] = []
        nested = [True]
        for i in range(0, len(formatted), BATCH_SIZE):
            vectors += await _post_batch(
                client, url, headers, formatted[i : i + BATCH_SIZE], model, dim, nested
            )
    finally:
        if own:
            await client.aclose()
    mat = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.where(norms == 0, 1.0, norms)


def load_index(
    name: str,
    data_dir: Path,
    expected_hash: str,
    *,
    model: Optional[str] = None,
    dim: int = DEFAULT_DIM,
) -> Optional[tuple[np.ndarray, list[str]]]:
    """Load index/{name}.npy if index_meta.json matches model, dim and content hash."""
    index_dir = Path(data_dir) / "index"
    try:
        meta = json.loads((index_dir / "index_meta.json").read_text(encoding="utf-8"))
        entry = meta["dbs"][name]
        if meta["model"] != (model or embed_model()) or meta["dim"] != dim:
            return None
        if entry["hash"] != expected_hash:
            return None
        matrix = np.load(index_dir / f"{name}.npy", allow_pickle=False)
        ids = list(entry["ids"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if matrix.ndim != 2 or matrix.shape != (len(ids), dim):
        return None
    return matrix, ids
