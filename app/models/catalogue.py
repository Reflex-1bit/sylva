"""
Sylva — Open Nature Catalogue models.

RawRecord is the common harvester output (one JSON object per line in
data/nature/catalogue/raw/<source>/records.jsonl). CatalogueRecord is the
sorted, published record. Sector, Habitat and Group match the JSON files in
data/nature/catalogue/. Area and function ids are not copied here: they come
from data/nature/taxonomy.json and are cross-checked by
scripts/nature/catalogue/validate.py.
"""

import re
from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.models.nature import is_open_licence

# ── Shared types ──────────────────────────────────────────────────────────────

# R1: stable, source-prefixed ids.
ID_PATTERN = r"^(oa-W\d+|pv-[A-Z0-9]+|cd-\d+|ca-[a-z0-9-]+)$"
_ID_RE = re.compile(ID_PATTERN)
_ID_PREFIX_SOURCE = {"oa": "openalex", "pv": "patentsview", "cd": "cordis", "ca": "climate_adapt"}

Source = Literal["openalex", "cordis", "patentsview", "climate_adapt"]
RecordKind = Literal["paper", "patent", "project", "case_study"]

RecordId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
Iso2 = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://\S+$")]
Doi = Annotated[str, StringConstraints(pattern=r"^10\.\S+$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ── Shared pieces ─────────────────────────────────────────────────────────────


class Organism(_Strict):
    name: str
    gbif_key: Optional[int] = None
    rank: Optional[str] = None


class SourceCodes(_Strict):
    cpc: list[str] = []
    openalex_subfields: list[str] = []
    openalex_topics: list[str] = []
    euroscivoc: list[str] = []
    climate_adapt_sectors: list[str] = []


class _RecordCore(_Strict):
    """Fields common to RawRecord and CatalogueRecord."""

    id: RecordId
    source: Source
    source_id: NonEmpty
    kind: RecordKind
    title: NonEmpty
    summary: Optional[str] = None
    summary_licence: Optional[str] = None
    source_licence: str
    url: HttpsUrl
    doi: Optional[Doi] = None
    year: Optional[int] = None
    countries: list[Iso2] = []
    organisations: list[str] = []  # organisation names only, never personal names

    @model_validator(mode="after")
    def _core_rules(self) -> "_RecordCore":
        # R3: a summary is stored only when its licence passes the open-licence gate.
        if self.summary is not None and not is_open_licence(self.summary_licence):
            raise ValueError("summary is allowed only under a CC BY or CC0 summary_licence")
        # The id prefix must agree with the source.
        prefix = self.id.split("-", 1)[0]
        if _ID_PREFIX_SOURCE[prefix] != self.source:
            raise ValueError(f"id prefix '{prefix}' does not match source '{self.source}'")
        return self


# ── Harvester output ──────────────────────────────────────────────────────────


class RawRecord(_RecordCore):
    source_codes: SourceCodes = SourceCodes()
    keywords: list[str] = []
    harvested_on: date


# ── Published catalogue record ────────────────────────────────────────────────


class CatalogueRecord(_RecordCore):
    organism: Optional[Organism] = None
    habitat_id: Optional[str] = None
    primary_sector: NonEmpty
    sector_tags: list[str] = Field(default=[], max_length=3)
    area: Optional[str] = None
    functions: list[str] = []
    sort_confidence: float = Field(ge=0, le=1)
    sort_reason: NonEmpty
    group_ids: list[str] = Field(default=[], max_length=3)
    library_id: Optional[str] = None
    genetic_resource_hint: bool = False
    provenance: Literal["machine_sorted"]
    licence: Literal["CC-BY-4.0"]

    @model_validator(mode="after")
    def _tags_exclude_primary(self) -> "CatalogueRecord":
        if self.primary_sector in self.sector_tags:
            raise ValueError("sector_tags must not include primary_sector")
        if len(set(self.sector_tags)) != len(self.sector_tags):
            raise ValueError("sector_tags must not repeat")
        return self


# ── Reference data files ──────────────────────────────────────────────────────


class Sector(_Strict):
    id: NonEmpty
    label_en: NonEmpty
    label_es: NonEmpty
    label_pt: NonEmpty
    nace_rev21_divisions: list[str] = []
    keywords_en: list[str] = []
    keywords_es: list[str] = []
    cpc_prefixes: list[str] = []
    openalex_subfields: list[str] = []
    candidate: bool
    min_records: int = Field(ge=0)


class SectorsFile(_Strict):
    version: str
    nace_source: HttpsUrl
    sectors: list[Sector]


class Habitat(_Strict):
    id: NonEmpty
    label_en: NonEmpty
    label_es: NonEmpty
    label_pt: NonEmpty
    keywords_en: list[str] = []
    gbif_classes: list[str] = []


class HabitatsFile(_Strict):
    version: str
    habitats: list[Habitat]


class Group(_Strict):
    id: NonEmpty
    name: NonEmpty
    country: Annotated[str, StringConstraints(pattern=r"^([A-Z]{2}|INT)$")]
    habitats: list[str] = []
    flagship_taxa: list[str] = []
    donate_url: HttpsUrl
    every_org_slug: Optional[str] = None
    source_url: HttpsUrl
    checked_on: date


class GroupsFile(_Strict):
    version: str
    groups: list[Group]


class CpcRow(_Strict):
    prefix: NonEmpty
    sector: NonEmpty
    note: NonEmpty


class SubfieldRow(_Strict):
    name: NonEmpty
    sector: NonEmpty
    note: NonEmpty


class TermRow(_Strict):
    term: NonEmpty
    sector: NonEmpty
    note: NonEmpty


class ConcordanceFile(_Strict):
    version: str
    notes: str
    cpc: list[CpcRow]
    openalex_subfield: list[SubfieldRow]
    euroscivoc: list[TermRow]
    climate_adapt_sector: list[TermRow]

    @field_validator("cpc")
    @classmethod
    def _cpc_unique(cls, rows: list[CpcRow]) -> list[CpcRow]:
        prefixes = [r.prefix for r in rows]
        if len(set(prefixes)) != len(prefixes):
            raise ValueError("duplicate CPC prefix in concordance")
        return rows
