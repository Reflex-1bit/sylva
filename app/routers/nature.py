"""
Sylva - /nature router: nature library, industry R&D map, sector gaps, RAG ask.

Quarantined library records (serving gate) never appear on any endpoint.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Optional, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.models.nature import (
    AskRequest,
    AskResponse,
    Kind,
    LibraryHit,
    LibraryRecord,
    MapHit,
    MapRecord,
    MapType,
    NatureStats,
    ProvenanceStatus,
)
from app.services import rag_service
from app.services.nature import rag
from app.services.nature.links import sector_gaps, sectors_for_record
from app.services.nature.matcher import parse_functions, score_library, with_function_candidates
from app.services.nature.search import NatureSearch
from app.services.nature.store import NatureDataError, NatureStore, get_store

LOG = logging.getLogger("sylva.router.nature")
router = APIRouter()

ASK_TIMEOUT_S = 50
DATA_UNAVAILABLE = "nature data unavailable"
LICENCE_ID = "CC-BY-4.0"
LICENCE_NAME = "CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
# Same wording as data/nature/LICENSE.txt. HTTP headers carry the ASCII form.
ATTRIBUTION = "Sylva — nature library and industry R&D map, CC BY 4.0"
ATTRIBUTION_ASCII = ATTRIBUTION.replace("—", "-")
EXPORT_DBS = ("library", "industry_map")
EXPORT_ALIASES = {"map": "industry_map"}
_CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def get_search(store: NatureStore = Depends(get_store)) -> NatureSearch:
    return _search_for(store)


@lru_cache(maxsize=4)
def _search_for(store: NatureStore) -> NatureSearch:
    return NatureSearch(store)


def _unavailable(exc: Exception) -> HTTPException:
    """Log why the data cannot be served (file names, never paths) and return a fixed 503."""
    if isinstance(exc, FileNotFoundError):
        LOG.error("nature data missing: %s", Path(exc.filename or "").name or "unknown file")
    else:
        LOG.error("nature data invalid: %s", exc)
    return HTTPException(status_code=503, detail=DATA_UNAVAILABLE)


@contextmanager
def _serving() -> Iterator[None]:
    """Map missing or invalid data files to 503, as the other routers do."""
    try:
        yield
    except (FileNotFoundError, NatureDataError) as e:
        raise _unavailable(e) from None


def _check(value: Optional[str], allowed: set[str], name: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(status_code=422, detail=f"unknown {name} '{value}'")


def _ids(taxonomy: dict, key: str) -> set[str]:
    return {item["id"] for item in taxonomy.get(key, [])}


def _servable_ids(store: NatureStore) -> set[str]:
    return {r.id for r in store.library(servable_only=True)}


def _public_map(rec: MapRecord, servable: set[str]) -> MapRecord:
    """Map record with library_links restricted to served library ids."""
    return rec.model_copy(update={"library_links": [i for i in rec.library_links if i in servable]})


# ── meta + stats ──────────────────────────────────────────────────────────────


@router.get("/nature/meta")
def nature_meta(store: NatureStore = Depends(get_store)):
    with _serving():
        taxonomy = store.taxonomy()
    return {
        "licence": {"id": LICENCE_ID, "name": LICENCE_NAME, "url": LICENCE_URL, "attribution": ATTRIBUTION},
        "version": taxonomy.get("version"),
        "taxonomy": taxonomy,
    }


@router.get("/nature/stats", response_model=NatureStats)
def nature_stats(store: NatureStore = Depends(get_store)):
    with _serving():
        return store.stats()


# ── library ───────────────────────────────────────────────────────────────────


@router.get("/nature/library", response_model=list[LibraryHit])
async def list_library(
    q: Optional[str] = None,
    area: Optional[str] = None,
    function: Optional[str] = None,
    sector: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    store: NatureStore = Depends(get_store),
    search: NatureSearch = Depends(get_search),
):
    """Ranked like /nature/ask when q is given; otherwise filtered records by id.

    Unknown area/function/sector/kind/status values return 422.
    """
    with _serving():
        taxonomy = store.taxonomy()
        _check(area, _ids(taxonomy, "areas"), "area")
        _check(function, _ids(taxonomy, "functions"), "function")
        _check(sector, _ids(taxonomy, "sectors"), "sector")
        _check(kind, set(get_args(Kind)), "kind")
        _check(status, set(get_args(ProvenanceStatus)), "status")

        query = (q or "").strip()
        if query:
            functions = parse_functions(query, taxonomy)
            raw = await search.search_library(
                query,
                areas=[area] if area else None,
                functions=[function] if function else None,
                sectors=[sector] if sector else None,
                kinds=[kind] if kind else None,
                statuses=[status] if status else None,
                k=limit * 3,
                api_key=rag_service._api_key(),
            )
            raw = with_function_candidates(
                raw,
                functions,
                store,
                areas=[area] if area else None,
                functions=[function] if function else None,
                sectors=[sector] if sector else None,
                kinds=[kind] if kind else None,
                statuses=[status] if status else None,
            )
            return score_library(raw, functions, store, store.industry_map())[:limit]

        records = [
            r
            for r in store.library(servable_only=True)
            if (not area or area in r.areas)
            and (not function or function in r.functions)
            and (not sector or sector in r.sector_tags)
            and (not kind or r.kind == kind)
            and (not status or r.provenance.status == status)
        ]
        records.sort(key=lambda r: r.id)
        return _unranked_hits(records[:limit], store)


def _unranked_hits(records: list[LibraryRecord], store: NatureStore) -> list[LibraryHit]:
    """Browse mode: no retrieval signal, so fit is 0 and the breakdown says so."""
    scored = score_library([(r, 0.0) for r in records], [], store, store.industry_map())
    out = []
    for hit in scored:
        fit = hit.breakdown["fit"]
        breakdown = {
            **hit.breakdown,
            "fit": 0.0,
            "retrieval_normalised": 0.0,
            "retrieval_none": 1.0,
        }
        out.append(hit.model_copy(update={"score": round(hit.score - fit, 4), "breakdown": breakdown}))
    out.sort(key=lambda h: h.record.id)
    return out


@router.get("/nature/library/{record_id}")
def get_library_record(record_id: str, store: NatureStore = Depends(get_store)):
    with _serving():
        rec = store.get_library(record_id, servable_only=True)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"library record '{record_id}' not found")
        return {
            "record": rec.model_dump(mode="json"),
            "evidence_grade": store.evidence_grade(rec),
            "sectors": sectors_for_record(rec, store),
        }


# ── industry map ──────────────────────────────────────────────────────────────


@router.get("/nature/map", response_model=list[MapHit])
async def list_map(
    q: Optional[str] = None,
    sector: Optional[str] = None,
    type: Optional[str] = None,
    country: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    limit: int = Query(default=20, ge=1, le=100),
    store: NatureStore = Depends(get_store),
    search: NatureSearch = Depends(get_search),
):
    """Ranked by retrieval when q is given; otherwise filtered records by id (score 0).

    Unknown sector/type values return 422.
    """
    with _serving():
        _check(sector, _ids(store.taxonomy(), "sectors"), "sector")
        _check(type, set(get_args(MapType)), "type")
        servable = _servable_ids(store)

        query = (q or "").strip()
        if query:
            raw = await search.search_map(
                query,
                sector=sector,
                types=[type] if type else None,
                country=country,
                year_from=year_from,
                year_to=year_to,
                k=limit,
                api_key=rag_service._api_key(),
            )
            return [MapHit(record=_public_map(r, servable), score=s) for r, s in raw]

        def keep(r: MapRecord) -> bool:
            if year_from is not None or year_to is not None:
                if r.year is None:
                    return False
                if (year_from is not None and r.year < year_from) or (
                    year_to is not None and r.year > year_to
                ):
                    return False
            return (
                (not sector or r.sector == sector)
                and (not type or r.type == type)
                and (not country or r.country.upper() == country.upper())
            )

        records = sorted((r for r in store.industry_map() if keep(r)), key=lambda r: r.id)
        return [MapHit(record=_public_map(r, servable), score=0.0) for r in records[:limit]]


@router.get("/nature/map/{record_id}", response_model=MapRecord)
def get_map_record(record_id: str, store: NatureStore = Depends(get_store)):
    with _serving():
        rec = store.get_map(record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"map record '{record_id}' not found")
        return _public_map(rec, _servable_ids(store))


# ── sectors ───────────────────────────────────────────────────────────────────


@router.get("/nature/sectors")
def list_sectors(store: NatureStore = Depends(get_store)):
    with _serving():
        counts: dict[str, int] = {}
        for m in store.industry_map():
            counts[m.sector] = counts.get(m.sector, 0) + 1
        return [{**s, "map_count": counts.get(s["id"], 0)} for s in store.taxonomy().get("sectors", [])]


@router.get("/nature/sectors/{sector_id}/gaps")
def get_sector_gaps(
    sector_id: str,
    limit: int = Query(default=10, ge=1, le=100),
    store: NatureStore = Depends(get_store),
):
    with _serving():
        if sector_id not in _ids(store.taxonomy(), "sectors"):
            raise HTTPException(status_code=404, detail=f"sector '{sector_id}' not found")
        return sector_gaps(sector_id, store, limit=limit)


# ── ask ───────────────────────────────────────────────────────────────────────


@router.post("/nature/ask", response_model=AskResponse)
async def nature_ask(
    req: AskRequest,
    store: NatureStore = Depends(get_store),
    search: NatureSearch = Depends(get_search),
):
    """Unknown sector or area values return 422, as on GET /nature/library.

    An empty or blank sector means no sector; blank areas are ignored.
    """
    req = req.model_copy(
        update={
            "sector": (req.sector or "").strip() or None,
            "areas": [a.strip() for a in req.areas if a.strip()],
        }
    )
    with _serving():
        taxonomy = store.taxonomy()
    _check(req.sector, _ids(taxonomy, "sectors"), "sector")
    for area in req.areas:
        _check(area, _ids(taxonomy, "areas"), "area")
    try:
        return await asyncio.wait_for(rag.ask(req, store, search), timeout=ASK_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"nature ask timed out after {ASK_TIMEOUT_S}s")
    except (FileNotFoundError, NatureDataError) as e:
        raise _unavailable(e) from None


# ── export ────────────────────────────────────────────────────────────────────


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict,)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return "; ".join(_csv_cell(v) for v in value)
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_START):
        return "'" + value  # stop spreadsheets reading the cell as a formula
    return str(value)


def _to_csv(rows: list[dict], model: type) -> str:
    header = list(model.model_fields)
    for row in rows:
        header += [k for k in row if k not in header]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_cell(row.get(k)) for k in header])
    return buf.getvalue()


@router.get("/nature/export/{db}")
def export_db(
    db: str,
    request: Request,
    format: str = Query(default="json"),
    store: NatureStore = Depends(get_store),
):
    """Servable library records or all map records, as json or csv (CC BY 4.0).

    `db` is `library` or `industry_map` (alias `map`). JSON wraps the records with
    the licence and attribution; CSV stays a pure table and carries them in the
    Link and X-Attribution headers.
    """
    db = EXPORT_ALIASES.get(db, db)
    if db not in EXPORT_DBS:
        raise HTTPException(status_code=404, detail=f"unknown database '{db}'")
    if format not in ("json", "csv"):
        raise HTTPException(status_code=422, detail="format must be 'json' or 'csv'")
    with _serving():
        if db == "library":
            model = LibraryRecord
            rows = [r.model_dump(mode="json") for r in store.library(servable_only=True)]
        else:
            model = MapRecord
            servable = _servable_ids(store)
            rows = [_public_map(r, servable).model_dump(mode="json") for r in store.industry_map()]
    if format == "json":
        wrapped = {
            "licence": LICENCE_ID,
            "licence_url": LICENCE_URL,
            "attribution": ATTRIBUTION,
            "version": request.app.version,  # APP_VERSION, set on the FastAPI app in main.py
            "db": db,
            "records": rows,
        }
        body, media = json.dumps(wrapped, ensure_ascii=False, indent=1), "application/json"
    else:
        body, media = _to_csv(rows, model), "text/csv"
    return Response(
        content=body,
        media_type=media,
        headers={
            "X-License": LICENCE_ID,
            "Link": f'<{LICENCE_URL}>; rel="license"',
            "X-Attribution": ATTRIBUTION_ASCII,
            "Content-Disposition": f'attachment; filename="sylva-nature-{db}-{LICENCE_ID}.{format}"',
        },
    )
