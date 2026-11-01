from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from server.auth import SessionDep, SvcDep, UserDep, owned_brand
from server.envelope import ok
from server.errors import ApiError
from server.routes.common import brief_state, claim_summary, next_step

router = APIRouter(prefix="/v1/brands/{brand_id}/notes", tags=["notes"])


class NoteIn(BaseModel):
    text: str = Field(max_length=20_000)


@router.post("", status_code=201)
def add_note(brand_id: str, body: NoteIn, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    text = body.text.strip()
    if not text:
        raise ApiError(422, "empty_note", "Note is empty", field="text")
    result = svc.brain.ingest(str(brand.id), text, source_type="note", author=str(user.id))
    state = brief_state(svc, s, brand)
    _, guidance, actions = next_step(svc, state)
    return ok(
        {"raw_input_id": result.raw_input_id,
         "claims": [claim_summary(c) for c in result.claims]},
        instructions=svc.instructions(f"Note saved to the brand brain.\n{guidance}"),
        next_actions=actions,
        progress=state.progress,
    )
