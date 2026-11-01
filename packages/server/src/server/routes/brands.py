from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from brain import BriefSection
from server.auth import SessionDep, SvcDep, UserDep, owned_brand
from server.envelope import action, ok
from server.errors import ApiError
from server.models import Brand
from server.routes.common import brief_state, next_step

router = APIRouter(prefix="/v1/brands", tags=["brands"])


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def brand_out(b: Brand) -> dict:
    return {"id": str(b.id), "name": b.name, "created_at": b.created_at.isoformat()}


@router.post("", status_code=201)
def create_brand(body: BrandIn, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_name", "Brand name is empty", field="name")
    brand = Brand(owner_id=user.id, name=name)
    s.add(brand)
    s.flush()
    svc.brain.create_brand_space(str(brand.id))
    s.commit()
    state = brief_state(svc, s, brand)
    _, _, actions = next_step(svc, state)
    return ok(
        {"brand": brand_out(brand)},
        instructions=svc.instructions(
            "Brand created. Tell the founder the brief takes about 10 minutes, then start the "
            "first challenge with `vybd challenge next`."
        ),
        next_actions=[action("challenge.next"), *actions[1:]],
        progress=state.progress,
    )


@router.get("")
def list_brands(user: UserDep, s: SessionDep) -> dict:
    brands = s.scalars(
        select(Brand).where(Brand.owner_id == user.id).order_by(Brand.created_at)
    ).all()
    return ok(
        {"brands": [brand_out(b) for b in brands]},
        next_actions=[action("brand.use", brand_id="<id>"), action("brand.create", name="Name")],
    )


def section_out(sec: BriefSection) -> dict:
    return {
        "key": sec.key,
        "title": sec.title,
        "claims": [{"id": c.id, "text": c.text, "kind": c.kind, "confidence": c.confidence}
                   for c in sec.claims],
    }


@router.get("/{brand_id}/brief")
def get_brief(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep,
              section: str | None = None) -> dict:
    brand = owned_brand(s, user, brand_id)
    state = brief_state(svc, s, brand)
    brief = state.brief
    sections = brief.sections + brief.other
    if section:
        sections = [x for x in sections if x.key == section]
        if not sections:
            raise ApiError(404, "not_found", f"section '{section}' not found")
    nxt, _, actions = next_step(svc, state)
    return ok(
        {
            "brand": brand_out(brand),
            "version": brief.version,
            "claim_count": brief.claim_count,
            "sections": [section_out(x) for x in sections],
            "empty_sections": brief.empty_sections,
            "markdown": brief.to_markdown(include_empty=True),
        },
        instructions="Show the founder the brief in plain language if they asked for it. "
                     "Don't edit it for them; changes go through challenge answers or notes.",
        next_actions=[action("challenge.next")] if nxt else actions,
        progress=state.progress,
    )
