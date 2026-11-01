"""Run worker. `python -m runner.worker` (or `make worker`). Safe to run several at once.

Claiming: `SELECT … FOR UPDATE SKIP LOCKED` on app.runs for `queued` runs, or `running` runs
whose lease expired (a crashed worker). A heartbeat thread renews the lease every minute and
notices cancellation. After every phase the checkpoint is written; on resume, completed phases
are skipped and their outputs reused.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from brain import BrandBrain
from brain.providers import LLMProvider, LLMResult
from runner.budget import BudgetedLLM, BudgetExceeded, BudgetTracker
from runner.context import Phase, PhaseOutput, RunContext
from runner.pipeline import REPORT_PHASE, default_pipeline
from runner.search import Search
from server.models import Brand, Run, RunEvent, now

log = logging.getLogger("runner.worker")

POLL_SECONDS = float(os.environ.get("RUNNER_POLL_SECONDS", "5"))
LEASE_SECONDS = float(os.environ.get("RUNNER_LEASE_SECONDS", "300"))
HEARTBEAT_SECONDS = float(os.environ.get("RUNNER_HEARTBEAT_SECONDS", "60"))


@dataclass
class Worker:
    session_factory: sessionmaker[Session]
    brain: BrandBrain
    llm: LLMProvider
    search: Search
    phases: list[Phase] = field(default_factory=default_pipeline)
    lease_seconds: float = LEASE_SECONDS
    heartbeat_seconds: float = HEARTBEAT_SECONDS
    worker_id: str = field(default_factory=lambda: f"w-{uuid.uuid4().hex[:8]}")

    # ---------- queue ----------

    def claim(self) -> uuid.UUID | None:
        with self.session_factory.begin() as s:
            run = s.execute(
                select(Run)
                .where(or_(Run.status == "queued",
                           and_(Run.status == "running", Run.lease_expires_at < now())))
                .order_by(Run.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).scalar_one_or_none()
            if run is None:
                return None
            reclaimed = run.status == "running"
            run.status = "running"
            run.started_at = run.started_at or now()
            run.lease_expires_at = now() + timedelta(seconds=self.lease_seconds)
            s.add(RunEvent(run_id=run.id, kind="claimed",
                           message=("reclaimed after lease expiry" if reclaimed else "claimed")
                           + f" by {self.worker_id}"))
            return run.id

    def poll_once(self) -> bool:
        run_id = self.claim()
        if run_id is None:
            return False
        self.execute(run_id)
        return True

    # ---------- helpers ----------

    def _event(self, run_id: uuid.UUID, kind: str, message: str, *, phase: str | None = None,
               tokens: int = 0, cost_usd: float = 0.0, **data: Any) -> None:
        with self.session_factory.begin() as s:
            s.add(RunEvent(run_id=run_id, phase=phase, kind=kind, message=message[:4000],
                           data=data, tokens=tokens, cost_usd=cost_usd))

    def _update(self, run_id: uuid.UUID, *, only_if_running: bool = True, **values: Any) -> bool:
        with self.session_factory.begin() as s:
            q = update(Run).where(Run.id == run_id)
            if only_if_running:
                q = q.where(Run.status == "running")
            return s.execute(q.values(**values)).rowcount == 1

    def _status(self, run_id: uuid.UUID) -> str | None:
        with self.session_factory() as s:
            return s.scalar(select(Run.status).where(Run.id == run_id))

    def _heartbeat(self, run_id: uuid.UUID, stop: threading.Event,
                   cancelled: threading.Event) -> None:
        while not stop.wait(self.heartbeat_seconds):
            ok = self._update(run_id, lease_expires_at=now()
                              + timedelta(seconds=self.lease_seconds))
            if not ok:
                cancelled.set()
                return

    # ---------- execution ----------

    def execute(self, run_id: uuid.UUID) -> None:
        with self.session_factory() as s:
            run = s.get(Run, run_id)
            if run is None or run.status != "running":
                return
            brand = s.get(Brand, run.brand_id)
            ckpt = dict(run.checkpoint or {})
            budget, spent0 = dict(run.budget or {}), dict(run.spent or {})

        completed: list[str] = list(ckpt.get("completed_phases", []))
        outputs = {k: PhaseOutput.model_validate(v) for k, v in ckpt.get("outputs", {}).items()}
        current: dict[str, str | None] = {"phase": None}

        def on_llm(spent: dict, result: LLMResult | None, label: str) -> None:
            self._update(run_id, spent=spent)
            if result is not None:
                self._event(run_id, "llm_call", f"{label} via {result.model}",
                            phase=current["phase"],
                            tokens=result.input_tokens + result.output_tokens,
                            cost_usd=result.cost_usd, model=result.model)

        tracker = BudgetTracker(budget, spent0, on_change=on_llm)
        ctx = RunContext(
            run_id=str(run_id), brand_id=str(brand.id), brand_name=brand.name,
            frozen=ckpt.get("frozen", {}), brain=self.brain,
            llm=BudgetedLLM(self.llm, tracker), search=self.search, outputs=outputs,
            log=lambda kind, message, **data: self._event(run_id, kind, message,
                                                          phase=current["phase"], **data),
            spent=lambda: tracker.spent, stopped_by=tracker.stopped_by,
        )

        stop, cancelled = threading.Event(), threading.Event()
        hb = threading.Thread(target=self._heartbeat, args=(run_id, stop, cancelled), daemon=True)
        hb.start()
        try:
            for phase in self.phases:
                if phase.name in completed:
                    self._event(run_id, "phase_skip", "already completed (resumed run)",
                                phase=phase.name)
                    continue
                if cancelled.is_set() or self._status(run_id) != "running":
                    self._event(run_id, "stopped", "run no longer running; stopping")
                    return
                if ctx.stopped_by and phase.name != REPORT_PHASE:
                    continue
                current["phase"] = phase.name
                self._update(run_id, current_phase=phase.name)
                self._event(run_id, "phase_start", phase.name, phase=phase.name)
                try:
                    if phase.name != REPORT_PHASE:
                        tracker.check()
                    out = phase.run(ctx)
                except BudgetExceeded as e:
                    ctx.stopped_by = e.limit
                    self._event(run_id, "budget_stop", str(e), phase=phase.name,
                                limit=e.limit, spent=tracker.spent)
                    continue
                outputs[phase.name] = out
                completed.append(phase.name)
                self._update(run_id, spent=tracker.spent, checkpoint={
                    **ckpt, "completed_phases": completed,
                    "outputs": {k: v.model_dump(mode="json") for k, v in outputs.items()},
                })
                self._event(run_id, "phase_end", f"{phase.name} done", phase=phase.name,
                            proposals=len(out.proposals))
            self._finish(run_id, ctx, outputs, tracker)
        except Exception as e:
            log.exception("run %s failed", run_id)
            self._event(run_id, "error", f"{type(e).__name__}: {e}", phase=current["phase"],
                        traceback=traceback.format_exc()[-4000:])
            self._update(run_id, status="failed", error=f"{type(e).__name__}: {e}"[:2000],
                         finished_at=now(), lease_expires_at=None, spent=tracker.spent)
        finally:
            stop.set()

    def _finish(self, run_id: uuid.UUID, ctx: RunContext, outputs: dict[str, PhaseOutput],
                tracker: BudgetTracker) -> None:
        report = outputs.get(REPORT_PHASE)
        if report is None:
            raise RuntimeError("pipeline finished without a report phase output")
        # Idempotent: a crash between proposing and completing must not duplicate proposals.
        existing = {
            " ".join(p.text.lower().split())
            for p in self.brain.list_proposals(ctx.brand_id, None) if p.origin_ref == ctx.run_id
        }
        created = 0
        for p in report.proposals:
            if " ".join(p.text.lower().split()) in existing:
                continue
            self.brain.propose(ctx.brand_id, p.text, section=p.section, kind=p.kind,
                               rationale=p.rationale, origin="run", origin_ref=ctx.run_id)
            created += 1
        spent = tracker.spent
        if ctx.stopped_by:
            spent["stopped_by"] = ctx.stopped_by
        self._update(run_id, status="completed", report_md=report.summary_md, spent=spent,
                     current_phase=None, finished_at=now(), lease_expires_at=None)
        self._event(run_id, "completed", f"run completed; {created} proposal(s) created",
                    stopped_by=ctx.stopped_by, spent=spent)


def build_worker() -> Worker:
    from brain.providers import get_embedder, get_llm
    from runner.search import get_search
    from server import db

    sf = db.session_factory()
    llm = get_llm("runner")  # RUNNER_LLM_MODEL / RUNNER_LLM_MODELS override LLM_MODEL(S)
    return Worker(session_factory=sf, brain=BrandBrain(sf, llm, get_embedder()), llm=llm,
                  search=get_search())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    worker = build_worker()
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("worker %s started (poll every %.1fs)", worker.worker_id, POLL_SECONDS)
    while not stop:
        try:
            if worker.poll_once():
                continue
        except Exception:
            log.exception("poll failed")
        time.sleep(POLL_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
