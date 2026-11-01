from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import update

from server.auth import SessionDep, SvcDep, UserDep, owned_brand
from server.envelope import action, ok
from server.errors import ApiError, not_found
from server.models import Attempt
from server.routes.common import brief_state, claim_summary, current_attempts, next_step

router = APIRouter(prefix="/v1/brands/{brand_id}/challenges", tags=["challenges"])


class AnswerIn(BaseModel):
    text: str = Field(max_length=10_000)
    evidence: list[str] = Field(default_factory=list, max_length=10)


@router.get("")
def list_challenges(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    current = {a.challenge_id: a for a in current_attempts(s, brand)}
    items = []
    for c in svc.catalog.challenges:
        a = current.get(c.id)
        items.append({
            "id": c.id, "order": c.order, "title": c.title, "required": c.required,
            "est_minutes": c.est_minutes, "section": c.section,
            "status": "answered" if a else "todo",
            "answer": a.answer_text if a else None,
            "feedback": a.feedback if a else None,
        })
    state = brief_state(svc, s, brand)
    _, _, actions = next_step(svc, state)
    return ok({"challenges": items}, next_actions=[action("challenge.next"), *actions],
              progress=state.progress)


@router.get("/next")
def next_challenge(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    state = brief_state(svc, s, brand)
    nxt, guidance, actions = next_step(svc, state)
    return ok({"challenge": nxt.public() if nxt else None},
              instructions=svc.instructions(guidance), next_actions=actions,
              progress=state.progress)


@router.post("/{challenge_id}/answer")
def answer(brand_id: str, challenge_id: str, body: AnswerIn, user: UserDep, s: SessionDep,
           svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    ch = svc.catalog.get(challenge_id)
    if ch is None:
        raise not_found(f"challenge '{challenge_id}'")
    text = body.text.strip()
    if len(text) < ch.min_chars:
        raise ApiError(
            422, "answer_too_short",
            f"Answer is {len(text)} characters; '{ch.title}' needs at least {ch.min_chars}.",
            field="text",
            instructions="Ask the founder for a little more detail (one follow-up), then "
                         "resubmit in their own words. Don't pad the answer yourself.",
            next_actions=[action("challenge.answer", challenge_id=ch.id)],
        )

    # Ingest first: if the LLM/embedder fails, no attempt is recorded and the client can retry.
    result = svc.brain.ingest(
        str(brand.id), text, source_type="challenge_answer", author=str(user.id),
        section_hint=ch.section, source_ref=ch.id,
    )
    feedback = svc.scorer.feedback(ch, text)  # never raises; empty on failure

    s.execute(
        update(Attempt)
        .where(Attempt.brand_id == brand.id, Attempt.challenge_id == ch.id,
               Attempt.is_current.is_(True))
        .values(is_current=False)
    )
    attempt = Attempt(
        brand_id=brand.id, challenge_id=ch.id, challenge_version=ch.version, answer_text=text,
        evidence=body.evidence, feedback=feedback.model_dump(),
        ingest_result=result.model_dump(mode="json"), is_current=True,
    )
    s.add(attempt)
    s.flush()

    state = brief_state(svc, s, brand, snapshot=True)  # commits attempt + snapshot
    attempt.score = state.score.by_section.get(ch.id)
    s.commit()

    nxt, guidance, actions = next_step(svc, state)
    lead = "Saved."
    if result.superseded_claim_ids:
        lead = "Saved; this replaces the earlier answer."
    if feedback.note:
        lead += f" Feedback to pass on briefly (one line, then move on): {feedback.note}"
    return ok(
        {
            "attempt_id": str(attempt.id),
            "challenge_id": ch.id,
            "claims": [claim_summary(c) for c in result.claims],
            "superseded_claim_ids": result.superseded_claim_ids,
            "feedback": feedback.model_dump(),
            "next_challenge": nxt.public() if nxt else None,
        },
        instructions=svc.instructions(f"{lead}\n{guidance}"),
        next_actions=actions,
        progress=state.progress,
    )
