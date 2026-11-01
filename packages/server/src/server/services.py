"""Per-app service container (DB, brain, challenge content). Built lazily so importing the app
never needs a DB connection or provider keys."""

from __future__ import annotations

from functools import cached_property

from sqlalchemy.orm import Session, sessionmaker

from brain import BrandBrain
from brain.providers import get_embedder, get_llm
from server import db
from server.challenges import ChallengeCatalog
from server.config import Settings


class Services:
    def __init__(self, settings: Settings, *, session_factory: sessionmaker[Session] | None = None,
                 brain: BrandBrain | None = None):
        self.settings = settings
        self._sf = session_factory
        self._brain = brain
        self.catalog = ChallengeCatalog.load(settings.content_dir / "challenges"
                                             / settings.challenge_set)
        self.global_instructions = (
            (settings.content_dir / "agent_instructions.md").read_text().strip()
        )

    @cached_property
    def session_factory(self) -> sessionmaker[Session]:
        return self._sf or db.session_factory()

    @cached_property
    def brain(self) -> BrandBrain:
        return self._brain or BrandBrain(self.session_factory, get_llm(), get_embedder())

    @cached_property
    def scorer(self):
        from server.scoring import get_scorer

        return get_scorer(self.settings.scorer, self.catalog, self.brain.llm)

    def instructions(self, specific: str = "") -> str:
        return f"{self.global_instructions}\n\n{specific.strip()}".strip()
