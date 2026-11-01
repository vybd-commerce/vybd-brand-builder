"""Shared brief-flow helpers: what's answered, score/progress, and what the agent does next."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain import BriefView, Claim
from server.challenges import Challenge
from server.envelope import NextAction, Progress, action
from server.models import Attempt, Brand, ScoreSnapshot
from server.scoring import Eligibility, ScoreResult
from server.services import Services


@dataclass
class BriefState:
    answered: set[str]
    brief: BriefView
    score: ScoreResult
    eligibility: Eligibility
    progress: Progress


def current_attempts(s: Session, brand: Brand) -> list[Attempt]:
    return list(s.scalars(
        select(Attempt).where(Attempt.brand_id == brand.id, Attempt.is_current.is_(True))
    ))


def brief_state(svc: Services, s: Session, brand: Brand, *, snapshot: bool = False) -> BriefState:
    attempts = current_attempts(s, brand)
    answered = {a.challenge_id for a in attempts}
    brief = svc.brain.brief(str(brand.id))
    result = svc.scorer.score(str(brand.id), attempts, brief)
    elig = svc.scorer.eligibility(result)
    if snapshot:
        s.add(ScoreSnapshot(
            brand_id=brand.id, scorer_version=result.scorer_version, total=result.total,
            by_section=result.by_section, eligible=elig.eligible,
            details={**result.details, "missing": result.missing, "reasons": elig.reasons},
        ))
        s.commit()
    p = svc.catalog.progress(answered)
    return BriefState(
        answered=answered, brief=brief, score=result, eligibility=elig,
        progress=Progress(completed=p["completed"], required=p["required"],
                          est_minutes_left=p["est_minutes_left"], score=result.total,
                          eligible=elig.eligible),
    )


def claim_summary(c: Claim) -> dict:
    return {"id": c.id, "text": c.text, "section": c.section, "kind": c.kind,
            "confidence": c.confidence}


def next_step(svc: Services, state: BriefState) -> tuple[Challenge | None, str, list[NextAction]]:
    """Next challenge (or None), agent guidance for it, and next_actions."""
    nxt = svc.catalog.next(state.answered)
    eligible = state.eligibility.eligible
    if nxt is None:
        return None, (
            "Every challenge is answered. Tell the founder their brief is ready, show it "
            "briefly if they want, then offer to submit it for a Brand Brain run."
        ), [action("run.submit"), action("brief.show"), action("note.add")]

    guidance = (
        f"Next challenge: '{nxt.title}' ({nxt.est_minutes:g} min). Share the lesson in a "
        f"sentence or two, then ask the task.\n{nxt.agent_instructions.strip()}"
    )
    actions = [action("challenge.answer", challenge_id=nxt.id), action("note.add"),
               action("brief.show")]
    if eligible:
        guidance = (
            "All required challenges are done, so the brief can be submitted now. "
            f"'{nxt.title}' is optional: offer it, and skip it if the founder prefers.\n"
            + guidance
        )
        actions.insert(1, action("run.submit"))
    return nxt, guidance, actions
