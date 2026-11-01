from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.auth import SessionDep, SvcDep, UserDep, is_admin, owned_brand
from server.envelope import action, ok
from server.errors import ApiError
from server.models import ACTIVE_RUN_STATUSES, Brand, Run, RunEvent, User, now
from server.routes.common import brief_state, next_step

router = APIRouter(prefix="/v1", tags=["runs"])

CONTEXT_PACK_TOKENS = 6000


def run_out(r: Run, brand: Brand | None = None) -> dict:
    out = {
        "id": str(r.id), "brand_id": str(r.brand_id), "status": r.status,
        "current_phase": r.current_phase, "budget": r.budget, "spent": r.spent,
        "completed_phases": (r.checkpoint or {}).get("completed_phases", []),
        "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }
    if brand is not None:
        out["brand_name"] = brand.name
    return out


def status_guidance(r: Run) -> str:
    return {
        "requested": "The run is waiting for admin approval. Tell the founder it will start "
                     "once approved; check back with `vybd run status`.",
        "approved": "Approved; waiting for a worker.",
        "queued": "Queued; a worker will pick it up shortly. Poll `vybd run status`.",
        "running": f"Running (phase: {r.current_phase or 'starting'}). Poll `vybd run status` "
                   "every few minutes; it can take a while.",
        "paused": "Paused. It will resume automatically.",
        "completed": "Done. Show the founder the report (`vybd run report`), then walk through "
                     "the proposals one by one and accept or reject each with their decision.",
        "failed": "The run failed. Tell the founder; an admin can re-queue it.",
        "cancelled": "The run was cancelled.",
    }.get(r.status, "")


def run_actions(r: Run) -> list:
    rid = str(r.id)
    if r.status == "completed":
        return [action("run.report", run_id=rid), action("proposal.list"),
                action("run.events", run_id=rid)]
    return [action("run.status", run_id=rid), action("run.events", run_id=rid)]


def visible_run(s: Session, user: User, svc, run_id: str) -> tuple[Run, Brand]:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise ApiError(404, "not_found", "run not found") from None
    r = s.get(Run, rid)
    brand = s.get(Brand, r.brand_id) if r else None
    if r is None or brand is None or (brand.owner_id != user.id and not is_admin(user, svc)):
        raise ApiError(404, "not_found", "run not found")
    return r, brand


def queue(r: Run, svc, by: str) -> None:
    r.status = "queued"
    r.approved_at = now()
    r.approved_by = by
    r.budget = dict(svc.settings.run_budget)


@router.post("/brands/{brand_id}/runs", status_code=201)
def submit_run(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    brand = owned_brand(s, user, brand_id)
    state = brief_state(svc, s, brand, snapshot=True)
    if not state.eligibility.eligible:
        _, guidance, actions = next_step(svc, state)
        raise ApiError(
            409, "not_eligible",
            "The brief isn't ready for a run: " + "; ".join(state.eligibility.reasons),
            instructions="Finish the required challenges first.\n" + guidance,
            next_actions=actions,
        )
    active = s.scalars(
        select(Run).where(Run.brand_id == brand.id, Run.status.in_(ACTIVE_RUN_STATUSES))
    ).first()
    if active:
        raise ApiError(409, "run_active",
                       f"This brand already has a run in progress ({active.status}).",
                       instructions="Only one run per brand at a time. Check its status.",
                       next_actions=[action("run.status", run_id=str(active.id))])

    frozen = {
        "brief_version": state.brief.version,
        "context_pack": svc.brain.context_pack(str(brand.id), "Brand Brain run: grow this brand",
                                               max_tokens=CONTEXT_PACK_TOKENS),
        "brand_name": brand.name,
        "score": state.score.total,
    }
    run = Run(brand_id=brand.id, requested_by=user.id, status="requested", budget={},
              spent={}, checkpoint={"frozen": frozen, "completed_phases": [], "outputs": {}})
    if svc.settings.auto_approve_runs:
        queue(run, svc, by="auto")
    s.add(run)
    s.flush()
    s.add(RunEvent(run_id=run.id, kind="submitted", message=f"submitted by {user.email}",
                   data={"brief_version": frozen["brief_version"], "auto_approved":
                         run.status == "queued"}))
    s.commit()
    return ok({"run": run_out(run)}, instructions=svc.instructions(status_guidance(run)),
              next_actions=run_actions(run))


@router.get("/brands/{brand_id}/runs")
def list_brand_runs(brand_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    """Runs for one brand, newest first (used by the UI; not in the v0 spec table)."""
    brand = owned_brand(s, user, brand_id)
    runs = s.scalars(
        select(Run).where(Run.brand_id == brand.id).order_by(Run.created_at.desc()).limit(20)
    ).all()
    actions = run_actions(runs[0]) if runs else []
    return ok({"runs": [run_out(r, brand) for r in runs]}, next_actions=actions)


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    r, brand = visible_run(s, user, svc, run_id)
    return ok({"run": run_out(r, brand)}, instructions=status_guidance(r),
              next_actions=run_actions(r))


@router.get("/runs/{run_id}/events")
def get_events(run_id: str, user: UserDep, s: SessionDep, svc: SvcDep,
               limit: int = 200) -> dict:
    r, _ = visible_run(s, user, svc, run_id)
    events = s.scalars(
        select(RunEvent).where(RunEvent.run_id == r.id)
        .order_by(RunEvent.created_at.desc()).limit(max(1, min(limit, 1000)))
    ).all()
    return ok({"events": [
        {"created_at": e.created_at.isoformat(), "phase": e.phase, "kind": e.kind,
         "message": e.message, "tokens": e.tokens, "cost_usd": e.cost_usd, "data": e.data}
        for e in reversed(events)
    ]}, next_actions=run_actions(r))


@router.get("/runs/{run_id}/report")
def get_report(run_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    r, _ = visible_run(s, user, svc, run_id)
    if not r.report_md:
        raise ApiError(409, "report_not_ready", f"No report yet (run is {r.status}).",
                       instructions=status_guidance(r), next_actions=run_actions(r))
    return ok({"run_id": str(r.id), "status": r.status, "report_md": r.report_md},
              instructions=status_guidance(r), next_actions=run_actions(r))
