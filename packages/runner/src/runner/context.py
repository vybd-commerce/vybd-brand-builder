"""Phase plugin interface (spec §10.3): RunContext in, PhaseOutput out."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from brain import BrandBrain
from brain.providers import LLMProvider
from brain.types import ClaimKind
from runner.search import Search

BriefSectionKey = Literal["one_liner", "customer", "problem", "alternative", "positioning",
                          "product", "price", "channels", "competitors", "goals"]


class ProposalDraft(BaseModel):
    """A suggested change to the brief. Becomes a brain proposal; never a claim directly."""

    text: str = Field(description="The exact statement to add to the brief, one sentence")
    section: BriefSectionKey
    kind: ClaimKind
    rationale: str = Field(description="Why, in one or two sentences, citing the brief")


class PhaseOutput(BaseModel):
    summary_md: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    proposals: list[ProposalDraft] = Field(default_factory=list)


@dataclass
class RunContext:
    run_id: str
    brand_id: str
    brand_name: str
    frozen: dict[str, Any]  # brief_version + context_pack snapshot taken at submit time
    brain: BrandBrain
    llm: LLMProvider  # budget-wrapped
    search: Search
    outputs: dict[str, PhaseOutput] = field(default_factory=dict)  # prior phases
    log: Callable[..., None] = lambda kind, message, **data: None
    spent: Callable[[], dict[str, Any]] = dict
    stopped_by: str | None = None

    @property
    def brief(self) -> str:
        return self.frozen.get("context_pack", "")

    def prior(self, *names: str) -> str:
        parts = [f"### {n}\n{self.outputs[n].summary_md}" for n in names if n in self.outputs]
        return "\n\n".join(parts) or "(none)"


class Phase(Protocol):
    name: str

    def run(self, ctx: RunContext) -> PhaseOutput: ...
