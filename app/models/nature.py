"""
Sylva — Nature arm models (nature library, industry R&D map, ask API).

Ids for areas, functions and sectors are plain strings here; the NatureStore
checks them against data/nature/taxonomy.json.
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ── Enums (exported for later tasks) ──────────────────────────────────────────

Kind = Literal["mechanism", "material", "process", "practice"]
TraitType = Literal[
    "morphological", "biochemical", "genetic", "behavioural", "ecological", "not_applicable"
]
LegalReview = Literal["not_required", "pending", "cleared"]
KnowledgeSource = Literal["peer_reviewed", "grey_literature", "traditional", "field_observation"]
Consent = Literal["not_applicable", "pending", "granted"]
MeasuredIn = Literal["literature", "reproduced", "field"]
ProvenanceStatus = Literal["ai_extracted", "expert_validated", "disputed"]
Confidence = Literal["low", "medium", "high"]
MapType = Literal["paper", "patent", "grant", "project", "company"]
NatureLink = Literal["biomimetic", "bio_based", "nature_based_solution", "circular", "other"]
OrgKind = Literal["company", "university", "research_centre", "public_body", "other"]
EvidenceGrade = Literal["strong", "moderate", "weak", "contested"]

_OPEN_LICENCE_PREFIXES = ("CC-BY", "CC0")


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ── Shared pieces ─────────────────────────────────────────────────────────────


class Organism(_Strict):
    scientific_name: str
    common_names: list[str] = []
    kingdom: Optional[str] = None
    gbif_usage_key: Optional[int] = None
    gbif_match_type: Optional[str] = None


class PerformanceItem(_Strict):
    metric: str
    value: Optional[float] = None
    units: Optional[str] = None
    measured_in: MeasuredIn = "literature"


class Evidence(_Strict):
    citation: str
    doi: Optional[str] = None
    url: Optional[str] = None
    year: Optional[int] = None
    open_access: bool = False
    licence: Optional[str] = None
    supporting_sentence: Optional[str] = None
    page: Optional[str] = None
    verified: bool = False

    @model_validator(mode="after")
    def _sentence_needs_open_licence(self) -> "Evidence":
        if self.supporting_sentence is not None:
            if not (self.licence or "").startswith(_OPEN_LICENCE_PREFIXES):
                raise ValueError(
                    "supporting_sentence is allowed only when licence starts with 'CC-BY' or 'CC0'"
                )
        return self


class Provenance(_Strict):
    status: ProvenanceStatus
    extracted_by: str
    extracted_on: date
    validated_by: Optional[str] = None
    validated_on: Optional[date] = None

    @model_validator(mode="after")
    def _validated_needs_validator(self) -> "Provenance":
        if self.status == "expert_validated" and not (self.validated_by and self.validated_on):
            raise ValueError("expert_validated requires validated_by and validated_on")
        return self


class SourceRegion(_Strict):
    region: str
    reserve_id: Optional[str] = None
    note: Optional[str] = None


class Contributor(_Strict):
    name: str
    role: str
    place: Optional[str] = None


# ── Nature library ────────────────────────────────────────────────────────────


class LibraryRecord(_Strict):
    id: str
    kind: Kind
    title: str
    summary: str
    areas: list[str] = Field(min_length=1)
    functions: list[str] = Field(min_length=1)
    sector_tags: list[str] = []
    organism: Optional[Organism] = None
    trait: Optional[str] = None
    structure: Optional[str] = None
    mechanism: Optional[str] = None
    trait_type: TraitType
    legal_review: LegalReview
    knowledge_source: KnowledgeSource
    consent: Consent
    performance: list[PerformanceItem] = []
    evidence: list[Evidence] = Field(min_length=1)
    known_products: list[str] = []
    popular_claim_note: Optional[str] = None
    provenance: Provenance
    confidence: Confidence
    caveat: str = Field(min_length=1)
    source_region: Optional[SourceRegion] = None
    contributors: list[Contributor] = []
    see_also: list[str] = []

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "LibraryRecord":
        if self.kind == "mechanism" and not (self.mechanism or "").strip():
            raise ValueError("kind 'mechanism' requires a non-empty 'mechanism'")
        if self.trait_type in ("biochemical", "genetic") and self.legal_review == "not_required":
            raise ValueError("biochemical/genetic traits need legal_review 'pending' or 'cleared'")
        if self.knowledge_source == "traditional" and self.consent == "not_applicable":
            raise ValueError("traditional knowledge needs consent 'pending' or 'granted'")
        return self


# ── Industry R&D map ──────────────────────────────────────────────────────────


class Inspiration(_Strict):
    organism: Optional[str] = None
    note: Optional[str] = None


class Organisation(_Strict):
    name: str
    country: Optional[str] = None
    kind: OrgKind
    ror: Optional[str] = None


class Identifiers(_Strict):
    doi: Optional[str] = None
    openalex_id: Optional[str] = None
    patent_number: Optional[str] = None
    grant_id: Optional[str] = None
    url: Optional[str] = None


class MapSource(_Strict):
    name: str
    licence: str
    retrieved_on: date


class MapRecord(_Strict):
    id: str
    type: MapType
    title: str
    summary: Optional[str] = None
    sector: str
    nace_divisions: list[str] = []
    problem_functions: list[str] = []
    areas: list[str] = []
    nature_link: NatureLink
    inspiration: Optional[Inspiration] = None
    country: str = Field(min_length=2, max_length=2)
    region: Optional[str] = None
    organisations: list[Organisation] = []
    year: Optional[int] = None
    trl: Optional[int] = Field(default=None, ge=1, le=9)
    identifiers: Identifiers = Identifiers()
    library_links: list[str] = []
    source: MapSource
    provenance: Provenance


# ── API response / request models ─────────────────────────────────────────────


class LibraryHit(_Strict):
    record: LibraryRecord
    score: float
    breakdown: dict[str, float]
    evidence_grade: EvidenceGrade


class MapHit(_Strict):
    record: MapRecord
    score: float


class NatureStats(_Strict):
    version: str
    licence: str
    library_total: int
    library_served: int
    quarantined: int
    by_status: dict[str, int]
    by_area: dict[str, int]
    by_kind: dict[str, int]
    with_measured_values: int
    validated_share: float
    measured_share: float
    map_total: int
    map_by_sector: dict[str, int]
    map_by_type: dict[str, int]
    map_by_country: dict[str, int]


class AskRequest(_Strict):
    challenge: str = Field(min_length=8, max_length=2000)
    sector: Optional[str] = None
    areas: list[str] = []
    functions: list[str] = []
    strict_functions: bool = False
    top_k: int = Field(default=8, ge=1, le=20)


class AskResponse(_Strict):
    challenge: str
    parsed_functions: list[str]
    verdict: str
    answer: dict
    library_hits: list[LibraryHit]
    map_hits: list[MapHit]
    gaps: list[str]
    model: str
    licence: str
