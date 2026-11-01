from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from brain import Proposal
from server.auth import SessionDep, SvcDep, UserDep, owned_brand
from server.envelope import action, ok
from server.errors import ApiError

router = APIRouter(prefix="/v1/brands/{brand_id}/proposals", tags=["proposals"])


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def proposal_out(p: Proposal) -> dict:
    return p.model_dump(mode="json")


@router.get("")
def list_proposals(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep,
                   status: str = "pending") -> dict:
    brand = owned_brand(s, user, brand_id)
    if status not in ("pending", "accepted", "rejected", "all"):
        raise ApiError(422, "invalid_status", "status must be pending|accepted|rejected|all",
                       field="status")
    items = svc.brain.list_proposals(str(brand.id), None if status == "all" else status)
    actions = []
    if items and status == "pending":
        pid = items[0].id
        actions = [action("proposal.accept", proposal_id=pid),
                   action("proposal.reject", proposal_id=pid)]
    instructions = (
        "Walk the founder through each proposal: read it and its rationale, ask whether it "
        "fits their brand, then accept or reject with their reason. Never decide for them."
        if items and status == "pending" else "No proposals to review."
    )
    return ok({"proposals": [proposal_out(p) for p in items]},
              instructions=svc.instructions(instructions), next_actions=actions)


def _remaining(svc, brand_id: str) -> tuple[str, list]:
    left = svc.brain.list_proposals(brand_id)
    if not left:
        return "All proposals reviewed. The brief is updated.", [action("brief.show")]
    return (f"{len(left)} proposal(s) left to review.",
            [action("proposal.accept", proposal_id=left[0].id),
             action("proposal.reject", proposal_id=left[0].id), action("proposal.list")])


@router.post("/{proposal_id}/accept")
def accept(brand_id: str, proposal_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    claim = svc.brain.accept_proposal(str(brand.id), proposal_id, by=str(user.id))
    msg, actions = _remaining(svc, str(brand.id))
    return ok({"proposal_id": proposal_id, "claim": {"id": claim.id, "text": claim.text,
                                                      "section": claim.section}},
              instructions=f"Accepted and added to the brief. {msg}", next_actions=actions)


@router.post("/{proposal_id}/reject")
def reject(brand_id: str, proposal_id: str, body: RejectIn, user: UserDep, s: SessionDep,
           svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    svc.brain.reject_proposal(str(brand.id), proposal_id, by=str(user.id),
                              reason=body.reason)
    msg, actions = _remaining(svc, str(brand.id))
    return ok({"proposal_id": proposal_id, "status": "rejected"},
              instructions=f"Rejected; the reason is remembered. {msg}", next_actions=actions)
