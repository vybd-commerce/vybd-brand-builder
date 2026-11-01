"""Admin run controls. Admin = email in ADMIN_EMAILS.

Approval is the hook for later automated review/audit (runs cost real money).
`approve` also re-queues a failed or paused run: it resumes from its last checkpoint.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from server.auth import SessionDep, SvcDep, UserDep, is_admin
from server.envelope import action, ok
from server.errors import ApiError
from server.models import TERMINAL_RUN_STATUSES, Brand, Run, RunEvent, User, now
from server.routes.runs import queue, run_out, visible_run

router = APIRouter(prefix="/v1/admin", tags=["admin"])

RUN_STATUSES = ("requested", "approved", "queued", "running", "paused", "completed", "failed",
                "cancelled")


def require_admin(user: User, svc) -> None:
    if not is_admin(user, svc):
        raise ApiError(403, "forbidden", "Admin only (email must be in ADMIN_EMAILS).")


@router.get("/runs")
def list_runs(user: UserDep, s: SessionDep, svc: SvcDep, status: str = "requested") -> dict:
    require_admin(user, svc)
    q = select(Run, Brand).join(Brand, Brand.id == Run.brand_id)
    if status != "all":
        if status not in RUN_STATUSES:
            raise ApiError(422, "invalid_status", f"status must be one of {RUN_STATUSES} or all",
                           field="status")
        q = q.where(Run.status == status)
    rows = s.execute(q.order_by(Run.created_at).limit(200)).all()
    runs = [run_out(r, b) for r, b in rows]
    actions = [action("admin.approve", run_id=runs[0]["id"]),
               action("admin.cancel", run_id=runs[0]["id"])] if runs else []
    return ok({"runs": runs}, next_actions=actions)


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    require_admin(user, svc)
    r, brand = visible_run(s, user, svc, run_id)
    if r.status not in ("requested", "failed", "paused"):
        raise ApiError(409, "invalid_state", f"Can't approve a run that is {r.status}.")
    resumed = r.status != "requested"
    queue(r, svc, by=user.email)
    if resumed:
        r.error = None
        r.finished_at = None
    s.add(RunEvent(run_id=r.id, kind="resumed" if resumed else "approved",
                   message=f"{'re-queued' if resumed else 'approved'} by {user.email}",
                   data={"budget": r.budget}))
    s.commit()
    return ok({"run": run_out(r, brand)}, instructions="Queued; a worker will pick it up.",
              next_actions=[action("run.status", run_id=str(r.id))])


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    require_admin(user, svc)
    r, brand = visible_run(s, user, svc, run_id)
    if r.status in TERMINAL_RUN_STATUSES:
        raise ApiError(409, "invalid_state", f"Run is already {r.status}.")
    r.status = "cancelled"
    r.finished_at = now()
    r.lease_expires_at = None
    s.add(RunEvent(run_id=r.id, kind="cancelled", message=f"cancelled by {user.email}"))
    s.commit()
    return ok({"run": run_out(r, brand)},
              instructions="Cancelled. A running worker stops at its next checkpoint.")
