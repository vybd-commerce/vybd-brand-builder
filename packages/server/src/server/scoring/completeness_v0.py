"""CompletenessScorerV0: deliberately simple.

- feedback: one LLM call → {note ≤2 sentences, suggestion|null}. Never blocks; failure → empty.
- score: each required challenge with a current attempt = equal share of 100; optional ones add
  a small bonus; capped at 100. Pure arithmetic.
- eligibility: all required challenges have current attempts.

# STUB: real scoring (answer quality, specificity, evidence) is a separate workstream.
"""

from __future__ import annotations

import logging

from brain import BriefView
from brain.providers import LLMProvider
from server.challenges import Challenge, ChallengeCatalog
from server.models import Attempt
from server.scoring.base import Eligibility, Feedback, ScoreResult

log = logging.getLogger("server.scoring")

OPTIONAL_BONUS = 5.0

FEEDBACK_SYSTEM = (
    "You are a warm, sharp brand coach giving a founder quick feedback on one answer in their "
    "brand brief. Be specific to what they wrote. At most two short sentences in `note`. "
    "If one concrete change would make the answer much stronger, put it in `suggestion` "
    "(one sentence); otherwise null. Never rewrite their answer for them. "
    'Respond with JSON: {"note": "...", "suggestion": "..." | null}'
)


class CompletenessScorerV0:
    version = "completeness_v0"

    def __init__(self, catalog: ChallengeCatalog, llm: LLMProvider):
        self.catalog = catalog
        self.llm = llm

    def feedback(self, challenge: Challenge, answer: str) -> Feedback:
        user = (
            f"Challenge: {challenge.title}\nWhat we asked: {challenge.task.strip()}\n"
            f"Why it matters: {challenge.lesson.strip()}\n\nFounder's answer:\n{answer}"
        )
        try:
            fb = self.llm.complete_structured(FEEDBACK_SYSTEM, user, Feedback, max_tokens=600).value
        except Exception as e:  # never block submission on feedback
            log.warning("feedback failed for %s: %s", challenge.id, e)
            return Feedback()
        note = " ".join(fb.note.split())
        return Feedback(note=note[:400], suggestion=(fb.suggestion or None))

    def score(self, brand_id: str, attempts: list[Attempt], brief: BriefView) -> ScoreResult:
        current = {a.challenge_id for a in attempts if a.is_current}
        required = self.catalog.required
        share = 100.0 / len(required) if required else 0.0
        by_section: dict[str, float] = {}
        for c in self.catalog.challenges:
            if c.id in current:
                by_section[c.id] = round(share if c.required else OPTIONAL_BONUS, 2)
            else:
                by_section[c.id] = 0.0
        total = min(100.0, round(sum(by_section.values()), 1))
        missing = [c.id for c in required if c.id not in current]
        return ScoreResult(
            scorer_version=self.version, total=total, by_section=by_section, missing=missing,
            details={"brief_version": brief.version, "claim_count": brief.claim_count},
        )

    def eligibility(self, result: ScoreResult) -> Eligibility:
        if result.missing:
            return Eligibility(eligible=False,
                               reasons=[f"answer the '{m}' challenge" for m in result.missing])
        return Eligibility(eligible=True)
