"""
Sylva — Nature arm data store: lazy load, validate, serving gate, stats.

Reads data/nature/{taxonomy,library,industry_map}.json. Never touches
data/species_db.json.
"""

import json
import threading
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models.nature import EvidenceGrade, LibraryRecord, MapRecord

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "nature"


class NatureDataError(ValueError):
    """Raised when the nature databases fail validation; lists all problems."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s):\n- " + "\n- ".join(problems))


def _read_json(path: Path) -> Any:
    """Parse one data file. Messages name the file, never its full path."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise NatureDataError([f"{path.name}: invalid JSON ({exc})"]) from exc
    except UnicodeDecodeError as exc:
        raise NatureDataError([f"{path.name}: not valid UTF-8 ({exc.reason} at byte {exc.start})"]) from exc
    except OSError as exc:
        raise NatureDataError([f"{path.name}: unreadable ({exc.strerror or type(exc).__name__})"]) from exc


def _dupes(ids: list[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1)


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


class NatureStore:
    def __init__(self, data_dir: Path = DEFAULT_DIR):
        self.data_dir = Path(data_dir)
        self._taxonomy: dict | None = None
        self._library: list[LibraryRecord] | None = None
        self._map: list[MapRecord] | None = None
        self._lock = threading.Lock()

    # ── loading ───────────────────────────────────────────────────────────────

    def reload(self) -> None:
        with self._lock:
            self._taxonomy = None  # first: _load() keys on it
            self._library = self._map = None

    def _load(self) -> None:
        if self._taxonomy is not None:
            return
        with self._lock:  # one loader on a cold start; the others wait for it
            if self._taxonomy is not None:
                return
            taxonomy = _read_json(self.data_dir / "taxonomy.json")
            raw_lib = _read_json(self.data_dir / "library.json")
            raw_map = _read_json(self.data_dir / "industry_map.json")
            if not isinstance(taxonomy, dict):
                raise NatureDataError(["taxonomy.json: top level must be an object"])

            problems: list[str] = []
            library = self._parse(raw_lib, LibraryRecord, "library.json", problems)
            industry = self._parse(raw_map, MapRecord, "industry_map.json", problems)
            self._check_references(taxonomy, library, industry, problems)
            if problems:
                raise NatureDataError(problems)

            self._library, self._map = library, industry
            self._taxonomy = taxonomy  # last: a non-None taxonomy means fully loaded

    @staticmethod
    def _parse(raw: Any, model: type, fname: str, problems: list[str]) -> list:
        if not isinstance(raw, list):
            problems.append(f"{fname}: top level must be an array")
            return []
        out = []
        for idx, item in enumerate(raw):
            label = item.get("id", f"#{idx}") if isinstance(item, dict) else f"#{idx}"
            try:
                out.append(model.model_validate(item))
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(p) for p in err["loc"])
                    problems.append(f"{fname} {label}: {loc}: {err['msg']}")
        return out

    @staticmethod
    def _check_references(
        tax: dict, library: list[LibraryRecord], industry: list[MapRecord], problems: list[str]
    ) -> None:
        areas = {a["id"] for a in tax.get("areas", [])}
        functions = {f["id"] for f in tax.get("functions", [])}
        sectors = {s["id"] for s in tax.get("sectors", [])}

        for d in _dupes([r.id for r in library]):
            problems.append(f"library.json: duplicate id {d}")
        for d in _dupes([r.id for r in industry]):
            problems.append(f"industry_map.json: duplicate id {d}")

        for r in library:
            for a in r.areas:
                if a not in areas:
                    problems.append(f"library.json {r.id}: unknown area '{a}'")
            for f in r.functions:
                if f not in functions:
                    problems.append(f"library.json {r.id}: unknown function '{f}'")
            for s in r.sector_tags:
                if s not in sectors:
                    problems.append(f"library.json {r.id}: unknown sector '{s}'")

        lib_ids = {r.id for r in library}
        for r in industry:
            if r.sector not in sectors:
                problems.append(f"industry_map.json {r.id}: unknown sector '{r.sector}'")
            for a in r.areas:
                if a not in areas:
                    problems.append(f"industry_map.json {r.id}: unknown area '{a}'")
            for f in r.problem_functions:
                if f not in functions:
                    problems.append(f"industry_map.json {r.id}: unknown function '{f}'")
            for link in r.library_links:
                if link not in lib_ids:
                    problems.append(f"industry_map.json {r.id}: library_link '{link}' not found")

    # ── accessors ─────────────────────────────────────────────────────────────

    def taxonomy(self) -> dict:
        self._load()
        return self._taxonomy

    def library(self, servable_only: bool = True) -> list[LibraryRecord]:
        self._load()
        if servable_only:
            return [r for r in self._library if self.is_servable(r)]
        return list(self._library)

    def industry_map(self) -> list[MapRecord]:
        self._load()
        return list(self._map)

    def get_library(self, record_id: str, servable_only: bool = True) -> LibraryRecord | None:
        for r in self.library(servable_only):
            if r.id == record_id:
                return r
        return None

    def get_map(self, record_id: str) -> MapRecord | None:
        for r in self.industry_map():
            if r.id == record_id:
                return r
        return None

    # ── serving gate and evidence ─────────────────────────────────────────────

    @staticmethod
    def is_servable(rec: LibraryRecord) -> bool:
        if rec.trait_type in ("biochemical", "genetic") and rec.legal_review == "pending":
            return False
        if rec.knowledge_source == "traditional" and rec.consent != "granted":
            return False
        return True

    @staticmethod
    def evidence_grade(rec: LibraryRecord) -> EvidenceGrade:
        if rec.provenance.status == "disputed" or rec.popular_claim_note:
            return "contested"
        sources = len(rec.evidence)
        has_measured = any(p.value is not None for p in rec.performance)
        located = sum(1 for e in rec.evidence if e.doi or e.url)
        if located >= 2 and has_measured:
            return "strong"
        if sources >= 2 or (sources >= 1 and has_measured):
            return "moderate"
        return "weak"

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Counts over the served library; quarantined records are only counted
        in library_total and quarantined."""
        self._load()
        served = self.library(servable_only=True)
        measured = sum(1 for r in served if any(p.value is not None for p in r.performance))
        validated = sum(1 for r in served if r.provenance.status == "expert_validated")
        industry = self._map
        return {
            "version": self._taxonomy.get("version"),
            "licence": self._taxonomy.get("licence"),
            "library_total": len(self._library),
            "library_served": len(served),
            "quarantined": len(self._library) - len(served),
            "by_status": dict(Counter(r.provenance.status for r in served)),
            "by_area": dict(Counter(a for r in served for a in r.areas)),
            "by_kind": dict(Counter(r.kind for r in served)),
            "with_measured_values": measured,
            "validated_share": _share(validated, len(served)),
            "measured_share": _share(measured, len(served)),
            "map_total": len(industry),
            "map_by_sector": dict(Counter(r.sector for r in industry)),
            "map_by_type": dict(Counter(r.type for r in industry)),
            "map_by_country": dict(Counter(r.country for r in industry)),
        }


@lru_cache(maxsize=1)
def get_store() -> NatureStore:
    return NatureStore()
