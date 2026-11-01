"""Public return types of the BrandBrain interface. Everything outside the brain sees only these."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ClaimKind = Literal["fact", "decision", "constraint", "hypothesis", "idea", "preference"]
ClaimStatus = Literal["accepted", "proposed", "rejected", "superseded", "parked"]
ProposalStatus = Literal["pending", "accepted", "rejected"]

CLAIM_KINDS: tuple[str, ...] = ClaimKind.__args__  # type: ignore[attr-defined]
CLAIM_STATUSES: tuple[str, ...] = ClaimStatus.__args__  # type: ignore[attr-defined]

# v0 brief sections, in display order. Unknown sections are allowed (shown under "Other").
BRIEF_SECTIONS: dict[str, str] = {
    "one_liner": "One-liner",
    "customer": "Customer",
    "problem": "Problem",
    "alternative": "Current alternative",
    "positioning": "Positioning",
    "product": "Product",
    "price": "Price",
    "channels": "Channels",
    "competitors": "Competitors",
    "goals": "Goals",
}

# source_type values the brain accepts via ingest(). Run output must use propose().
USER_SOURCE_TYPES = frozenset({"challenge_answer", "note", "import"})


class Evidence(BaseModel):
    raw_input_id: str
    excerpt: str


class Claim(BaseModel):
    id: str
    brand_id: str
    text: str
    section: str
    kind: ClaimKind
    status: ClaimStatus
    authority: str
    confidence: float
    supersedes_id: str | None = None
    created_at: datetime
    updated_at: datetime
    evidence: list[Evidence] = Field(default_factory=list)
    score: float | None = None  # similarity, set by search()


class IngestResult(BaseModel):
    raw_input_id: str
    claims: list[Claim]
    superseded_claim_ids: list[str] = Field(default_factory=list)
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class BriefSection(BaseModel):
    key: str
    title: str
    claims: list[Claim]


class BriefView(BaseModel):
    brand_id: str
    version: str  # changes whenever the set of accepted claims changes
    sections: list[BriefSection]  # all v0 sections in order, possibly empty
    other: list[BriefSection] = Field(default_factory=list)  # non-standard sections
    claim_count: int = 0

    @property
    def empty_sections(self) -> list[str]:
        return [s.key for s in self.sections if not s.claims]

    def to_markdown(self, include_empty: bool = False) -> str:
        lines: list[str] = []
        for s in [*self.sections, *self.other]:
            if not s.claims and not include_empty:
                continue
            lines.append(f"## {s.title}")
            if not s.claims:
                lines.append("_(empty)_")
            lines += [f"- {c.text}" for c in s.claims]
            lines.append("")
        return "\n".join(lines).strip()


class Proposal(BaseModel):
    id: str
    brand_id: str
    text: str
    section: str
    kind: ClaimKind
    rationale: str
    origin: str
    origin_ref: str | None = None
    status: ProposalStatus
    decided_by: str | None = None
    decision_note: str | None = None
    resulting_claim_id: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class BrainError(Exception):
    """Base for brain errors the server maps to clean API errors."""


class BrandSpaceNotFound(BrainError):
    pass


class ProposalNotFound(BrainError):
    pass


class ProposalAlreadyDecided(BrainError):
    pass
