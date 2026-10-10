"""
Sylva - Nature arm: hybrid search (BM25 + optional Gemini embeddings, RRF).

BM25 always runs. When an API key is given and a valid on-disk index exists,
cosine similarity is fused with BM25 by reciprocal-rank fusion (k=60).
Scores returned are the fused score divided by the maximum in the result
set, so the best hit is 1.0.

The library is searched over servable records only; the map has no gate.
"""

import asyncio
import hashlib
import json
import logging
from typing import Optional, Union

import httpx
import numpy as np

from app.models.nature import LibraryRecord, MapRecord
from app.services.nature.bm25 import BM25
from app.services.nature.embeddings import embed_texts, load_index
from app.services.nature.store import NatureStore, get_store
from app.services.nature.text import tokenize

log = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES = 100  # depth of each ranked list entering the fusion
QUERY_EMBED_TIMEOUT_S = 8  # past this, the query runs on BM25 alone

Record = Union[LibraryRecord, MapRecord]


def _labels(ids: list[str], items: list[dict], key: str = "label") -> list[str]:
    by_id = {i["id"]: i.get(key) or i.get("label_en") or i["id"] for i in items}
    return [by_id.get(i, i) for i in ids]


def doc_text(record: Record, taxonomy: dict) -> str:
    """Text indexed for a record: wording plus taxonomy labels for its ids."""
    parts = [record.title, record.summary or ""]
    if isinstance(record, LibraryRecord):
        parts += [record.mechanism or "", record.structure or "", record.trait or ""]
        if record.organism:
            parts += [record.organism.scientific_name, *record.organism.common_names]
        sectors = record.sector_tags
        functions = record.functions
    else:
        if record.inspiration:
            parts += [record.inspiration.organism or "", record.inspiration.note or ""]
        parts += [o.name for o in record.organisations]
        sectors = [record.sector]
        functions = record.problem_functions
    parts += _labels(functions, taxonomy.get("functions", []))
    parts += _labels(record.areas, taxonomy.get("areas", []))
    parts += _labels(sectors, taxonomy.get("sectors", []), "label_en")
    return " ".join(p for p in parts if p)


def content_hash(texts: list[str]) -> str:
    return hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode("utf-8")).hexdigest()


def index_documents(store: NatureStore) -> dict[str, tuple[list[Record], list[str]]]:
    """The records and doc_text lists that are indexed, per db name."""
    tax = store.taxonomy()
    lib = store.library(servable_only=True)
    imap = store.industry_map()
    return {
        "library": (lib, [doc_text(r, tax) for r in lib]),
        "industry_map": (imap, [doc_text(r, tax) for r in imap]),
    }


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal-rank fusion: sum of 1/(k + rank) over each ranked list (rank from 1)."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


class _Db:
    def __init__(self, name: str, records: list[Record], texts: list[str]):
        self.name = name
        self.records = records
        self.texts = texts
        self.hash = content_hash(texts)
        self.bm25 = BM25([tokenize(t) for t in texts])
        self.vectors: Optional[np.ndarray] = None
        self.vectors_checked = False


class NatureSearch:
    def __init__(self, store: Optional[NatureStore] = None):
        self.store = store or get_store()
        self._dbs: dict[str, _Db] = {}

    def _db(self, name: str) -> _Db:
        if name not in self._dbs:
            records, texts = index_documents(self.store)[name]
            self._dbs[name] = _Db(name, records, texts)
        return self._dbs[name]

    def _vectors(self, db: _Db) -> Optional[np.ndarray]:
        """Index rows aligned to db.records, or None if there is no valid index."""
        if not db.vectors_checked:
            db.vectors_checked = True
            loaded = load_index(db.name, self.store.data_dir, db.hash)
            if loaded is not None:
                matrix, ids = loaded
                if ids == [r.id for r in db.records]:
                    db.vectors = matrix
        return db.vectors

    async def _rank(
        self, db: _Db, query: str, allowed: np.ndarray, k: int, api_key: Optional[str]
    ) -> list[tuple[Record, float]]:
        bm = db.bm25.scores(tokenize(query))
        bm = np.where(allowed, bm, 0.0)
        order = np.argsort(-bm, kind="stable")
        rankings = [[int(i) for i in order[:CANDIDATES] if bm[i] > 0]]

        vectors = self._vectors(db) if api_key else None
        if vectors is not None:
            try:
                q = await asyncio.wait_for(
                    embed_texts([query], kind="query", api_key=api_key),
                    timeout=QUERY_EMBED_TIMEOUT_S,
                )
                sims = np.where(allowed, vectors @ q[0], -np.inf)
                vec_order = np.argsort(-sims, kind="stable")
                rankings.append([int(i) for i in vec_order[:CANDIDATES] if allowed[i]])
            except asyncio.TimeoutError:
                log.warning("query embedding took over %ss, using BM25 only", QUERY_EMBED_TIMEOUT_S)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("query embedding failed, using BM25 only: %s", exc)

        fused = rrf(rankings)
        ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        if not ranked:
            return []
        top = ranked[0][1]
        return [(db.records[i], score / top) for i, score in ranked]

    async def search_library(
        self,
        query: str,
        *,
        areas: Optional[list[str]] = None,
        functions: Optional[list[str]] = None,
        sectors: Optional[list[str]] = None,
        kinds: Optional[list[str]] = None,
        statuses: Optional[list[str]] = None,
        k: int = 10,
        api_key: Optional[str] = None,
    ) -> list[tuple[LibraryRecord, float]]:
        db = self._db("library")
        allowed = np.array(
            [
                self.store.is_servable(r)  # defence in depth: the gate always applies
                and (not areas or bool(set(areas) & set(r.areas)))
                and (not functions or bool(set(functions) & set(r.functions)))
                and (not sectors or bool(set(sectors) & set(r.sector_tags)))
                and (not kinds or r.kind in kinds)
                and (not statuses or r.provenance.status in statuses)
                for r in db.records
            ],
            dtype=bool,
        )
        return await self._rank(db, query, allowed, k, api_key)

    async def search_map(
        self,
        query: str,
        *,
        sector: Optional[str] = None,
        types: Optional[list[str]] = None,
        country: Optional[str] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        k: int = 10,
        api_key: Optional[str] = None,
    ) -> list[tuple[MapRecord, float]]:
        db = self._db("industry_map")

        def year_ok(r: MapRecord) -> bool:
            if year_from is None and year_to is None:
                return True
            if r.year is None:
                return False
            return (year_from is None or r.year >= year_from) and (
                year_to is None or r.year <= year_to
            )

        allowed = np.array(
            [
                (not sector or r.sector == sector)
                and (not types or r.type in types)
                and (not country or r.country.upper() == country.upper())
                and year_ok(r)
                for r in db.records
            ],
            dtype=bool,
        )
        return await self._rank(db, query, allowed, k, api_key)
