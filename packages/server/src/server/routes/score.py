from __future__ import annotations

from fastapi import APIRouter

from server.auth import SessionDep, SvcDep, UserDep, owned_brand
from server.envelope import action, ok
from server.routes.common import brief_state, next_step

router = APIRouter(prefix="/v1/brands/{brand_id}/score", tags=["score"])


@router.get("")
def get_score(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    state = brief_state(svc, s, brand, snapshot=True)
    _, guidance, actions = next_step(svc, state)
    if state.eligibility.eligible:
        instructions = "The brief is eligible for a Brand Brain run. Offer to submit it."
        actions = [action("run.submit"), *[a for a in actions if a.action != "run.submit"]]
    else:
        instructions = (
            "Not eligible yet: " + "; ".join(state.eligibility.reasons) + ".\n" + guidance
        )
    return ok(
        {"score": {
            "scorer_version": state.score.scorer_version,
            "total": state.score.total,
            "by_section": state.score.by_section,
            "missing": state.score.missing,
            "eligible": state.eligibility.eligible,
            "reasons": state.eligibility.reasons,
        }},
        instructions=svc.instructions(instructions),
        next_actions=actions,
        progress=state.progress,
    )
