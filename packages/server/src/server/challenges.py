"""Challenge content: YAML loader, schema validation, next-challenge logic."""

from __future__ import annotations

import pathlib
from collections.abc import Iterable

import yaml
from pydantic import BaseModel, Field, model_validator


class Challenge(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    order: int
    section: str
    required: bool
    est_minutes: float = Field(gt=0)
    title: str
    lesson: str
    example: str
    task: str
    agent_instructions: str
    quick_replies: list[str] = Field(default_factory=list)
    min_chars: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _lesson_short(self) -> Challenge:
        if len(self.lesson.split()) > 60:
            raise ValueError(f"challenge {self.id}: lesson must be under 60 words")
        return self

    def public(self) -> dict:
        """What clients see (everything; agent_instructions are meant for the driving agent)."""
        return self.model_dump()


class ChallengeCatalog:
    def __init__(self, challenges: Iterable[Challenge]):
        self.challenges = sorted(challenges, key=lambda c: c.order)
        self.by_id = {c.id: c for c in self.challenges}
        if len(self.by_id) != len(self.challenges):
            raise ValueError("duplicate challenge ids")
        if len({c.order for c in self.challenges}) != len(self.challenges):
            raise ValueError("duplicate challenge order values")

    @classmethod
    def load(cls, directory: pathlib.Path) -> ChallengeCatalog:
        files = sorted(directory.glob("*.yaml"))
        if not files:
            raise ValueError(f"no challenge YAML files in {directory}")
        out = []
        for f in files:
            try:
                out.append(Challenge.model_validate(yaml.safe_load(f.read_text())))
            except Exception as e:
                raise ValueError(f"invalid challenge file {f.name}: {e}") from e
        return cls(out)

    @property
    def required(self) -> list[Challenge]:
        return [c for c in self.challenges if c.required]

    def get(self, challenge_id: str) -> Challenge | None:
        return self.by_id.get(challenge_id)

    def next(self, answered: set[str]) -> Challenge | None:
        """First required challenge without a current attempt (by order), then optional ones."""
        for c in self.required:
            if c.id not in answered:
                return c
        for c in self.challenges:
            if not c.required and c.id not in answered:
                return c
        return None

    def progress(self, answered: set[str]) -> dict:
        req = self.required
        done = [c for c in req if c.id in answered]
        left = sum(c.est_minutes for c in self.challenges if c.id not in answered)
        return {
            "completed": len(done),
            "required": len(req),
            "optional_completed": len(
                [c for c in self.challenges if not c.required and c.id in answered]
            ),
            "est_minutes_left": round(left, 1),
            "all_required_done": len(done) == len(req),
        }
