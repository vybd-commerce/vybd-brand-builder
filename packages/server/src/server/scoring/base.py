"""Scorer interface (spec §9.1). Real scorers later just implement this protocol."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from brain import BriefView
from server.challenges import Challenge
from server.models import Attempt


class Feedback(BaseModel):
    note: str = Field(default="", description="At most two sentences of encouragement/critique")
    suggestion: str | None = Field(default=None, description="One concrete improvement, or null")


class ScoreResult(BaseModel):
    scorer_version: str
    total: float
    by_section: dict[str, float]  # challenge id -> points earned
    missing: list[str] = Field(default_factory=list)  # required challenge ids without an answer
    details: dict = Field(default_factory=dict)


class Eligibility(BaseModel):
    eligible: bool
    reasons: list[str] = Field(default_factory=list)


class Scorer(Protocol):
    version: str

    def feedback(self, challenge: Challenge, answer: str) -> Feedback: ...

    def score(self, brand_id: str, attempts: list[Attempt], brief: BriefView) -> ScoreResult: ...

    def eligibility(self, result: ScoreResult) -> Eligibility: ...
