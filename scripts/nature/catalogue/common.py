"""Shared helpers for the Open Nature Catalogue scripts (paths, loaders, jsonl, date)."""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Type, TypeVar

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pydantic import BaseModel  # noqa: E402

from app.models.catalogue import (  # noqa: E402
    ConcordanceFile,
    GroupsFile,
    HabitatsFile,
    SectorsFile,
)

CATALOGUE_DIR = REPO / "data" / "nature" / "catalogue"
RAW_DIR = CATALOGUE_DIR / "raw"
BUILD_DIR = CATALOGUE_DIR / "build"
TAXONOMY_PATH = REPO / "data" / "nature" / "taxonomy.json"

M = TypeVar("M", bound=BaseModel)


def _load(name: str, model: Type[M], directory: Optional[Path] = None) -> M:
    path = (directory or CATALOGUE_DIR) / name
    return model.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_sectors(directory: Optional[Path] = None) -> SectorsFile:
    return _load("sectors.json", SectorsFile, directory)


def load_habitats(directory: Optional[Path] = None) -> HabitatsFile:
    return _load("habitats.json", HabitatsFile, directory)


def load_concordance(directory: Optional[Path] = None) -> ConcordanceFile:
    return _load("concordance.json", ConcordanceFile, directory)


def load_groups(directory: Optional[Path] = None) -> GroupsFile:
    return _load("groups.json", GroupsFile, directory)


def load_taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def write_jsonl(path: Path, models: Iterable[BaseModel]) -> int:
    """Write one JSON object per line (UTF-8, no BOM, LF). Returns the count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for m in models:
            fh.write(m.model_dump_json() + "\n")
            count += 1
    return count


def read_jsonl(path: Path, model: Type[M]) -> list[M]:
    """Read and validate a jsonl file; a missing file is an empty list."""
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                out.append(model.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path.name}:{n}: {exc}") from exc
    return out


def openalex_licence(oa_license: Optional[str]) -> Optional[str]:
    """OpenAlex 'license' id -> catalogue licence string (cc-by -> CC-BY, no version invented; cc0 -> CC0-1.0)."""
    lic = (oa_license or "").strip().lower()
    if not lic:
        return None
    if lic == "cc-by":
        return "CC-BY"
    if lic == "cc0":
        return "CC0-1.0"
    return lic.upper()


def today() -> str:
    return date.today().isoformat()
