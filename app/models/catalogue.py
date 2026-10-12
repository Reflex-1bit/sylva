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
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, field_validator, model_validator

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
def _strict_iso_date(v):
    """Accept a date or a plain 'YYYY-MM-DD' string; reject datetimes and other strings."""
    if isinstance(v, datetime):
        raise ValueError("date must be YYYY-MM-DD, not a datetime")
    if isinstance(v, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ValueError("date must be YYYY-MM-DD")
    return v


IsoDate = Annotated[date, BeforeValidator(_strict_iso_date)]


NonEmpty = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# Personal-data hygiene: no contact addresses in stored text. scripts/nature/catalogue/scrub.py
# removes them; the record validator rejects any that remain. The final label must be alphabetic
# so ratios such as "mAP@0.5" are not mistaken for addresses.
EMAIL_RE = re.compile(r"[\w.+%-]+@(?:[\w-]+\.)+[A-Za-z]{2,}")
OBFUSCATED_EMAIL_RE = re.compile(
    r"[\w.+%-]+\s*[\[({]\s*at\s*[\])}]\s*(?:[\w-]+\s*(?:\.|[\[({]\s*dot\s*[\])}])\s*)+[A-Za-z]{2,}",
    re.I,
)
MAILTO_RE = re.compile(r"mailto:\S*", re.I)


def contains_contact(text: str) -> bool:
    return bool(EMAIL_RE.search(text) or OBFUSCATED_EMAIL_RE.search(text) or MAILTO_RE.search(text))


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
    year: Optional[int] = Field(default=None, ge=1500, le=2100)
    countries: list[Iso2] = []
    organisations: list[str] = []  # organisation names only, never personal names

    @model_validator(mode="after")
    def _core_rules(self) -> "_RecordCore":
        # R3: a summary is stored only when its licence passes the open-licence gate.
        if self.summary is not None and not is_open_licence(self.summary_licence):
            raise ValueError("summary is allowed only under a CC BY or CC0 summary_licence")
        if self.summary is not None and contains_contact(self.summary):
            raise ValueError("summary must not contain an email address or mailto link")
        # The id prefix must agree with the source.
        prefix = self.id.split("-", 1)[0]
        if _ID_PREFIX_SOURCE[prefix] != self.source:
            raise ValueError(f"id prefix '{prefix}' does not match source '{self.source}'")
        return self


# ── Harvester output ──────────────────────────────────────────────────────────


class RawRecord(_RecordCore):
    source_codes: SourceCodes = SourceCodes()
    keywords: list[str] = []
    harvested_on: IsoDate


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
        for name in ("sector_tags", "functions", "group_ids"):
            vals = getattr(self, name)
            if len(set(vals)) != len(vals):
                raise ValueError(f"{name} must not repeat")
        return self


# ── Reference data files ──────────────────────────────────────────────────────


class Sector(_Strict):
    id: NonEmpty
    label_en: NonEmpty
    label_es: NonEmpty
    label_pt: NonEmpty
    description: Optional[str] = Field(default=None, max_length=300)
    nace_rev21_divisions: list[str] = []
    keywords_en: list[str] = []
    keywords_es: list[str] = []
    keywords_weak_en: list[str] = []
    keywords_weak_es: list[str] = []
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
    keywords_weak_en: list[str] = []
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
    checked_on: IsoDate


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
    strength: Literal["strong", "medium"] = "strong"
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
