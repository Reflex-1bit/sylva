"""Sylva-wild request and response models (/api/v1/wild)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Intent = Literal["fix", "build"]


class WildAskRequest(BaseModel):
    intent: Intent = "fix"
    sector: Optional[str] = Field(default=None, max_length=64, description="sector id, or null for 'Not sure'")
    problem: str = Field(min_length=10, max_length=1000)

    @field_validator("problem")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 10:
            raise ValueError("describe the problem in at least 10 characters")
        return v

    @field_validator("sector")
    @classmethod
    def _blank_is_none(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() or None if isinstance(v, str) else v


class DonationGroup(BaseModel):
    id: str
    name: str
    donate_url: str


class RecordHit(BaseModel):
    ref: str  # "R1".."R12": how the answer cites this record
    id: str
    title: str
    url: str
    doi: Optional[str] = None
    year: Optional[int] = None
    kind: str
    source: str
    primary_sector: str
    organism: Optional[str] = None
    has_summary: bool = False
    groups: list[DonationGroup] = []


class Solution(BaseModel):
    title: str
    nature_strategy: str
    why_it_fits: str
    caveat: str = ""
    refs: list[str]  # cited R# refs, all present in `records`


class WildAskResponse(BaseModel):
    intent: Intent
    sector: Optional[str]
    queries: list[str]
    summary: str
    solutions: list[Solution]
    next_steps: list[str]
    records: list[RecordHit]
    model: str
    notice: str
    attribution: str


class SectorOption(BaseModel):
    id: str
    label_en: str
    label_es: Optional[str] = None
    label_pt: Optional[str] = None
    count: int


class WildMeta(BaseModel):
    sectors: list[SectorOption]
    record_count: int
    index_status: Literal["ready", "loading", "missing", "error"]
    index_built_on: Optional[str] = None
    llm_available: bool
    notice: str
    attribution: str
