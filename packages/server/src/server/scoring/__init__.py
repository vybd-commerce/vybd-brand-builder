"""Pluggable scoring. Select with SCORER=<name>."""

from __future__ import annotations

from brain.providers import LLMProvider
from server.challenges import ChallengeCatalog
from server.scoring.base import Eligibility, Feedback, Scorer, ScoreResult
from server.scoring.completeness_v0 import CompletenessScorerV0

__all__ = ["Eligibility", "Feedback", "ScoreResult", "Scorer", "get_scorer"]

SCORERS = {"completeness_v0": CompletenessScorerV0}


def get_scorer(name: str, catalog: ChallengeCatalog, llm: LLMProvider) -> Scorer:
    try:
        return SCORERS[name](catalog, llm)
    except KeyError:
        raise ValueError(f"Unknown SCORER={name!r}. Valid: {sorted(SCORERS)}") from None
