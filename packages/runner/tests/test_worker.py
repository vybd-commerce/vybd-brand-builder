"""Milestone 6: worker, lease, budget, checkpoints, resume — fake providers, real Postgres."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from brain import BrandBrain
from brain.providers import FakeEmbedder, embed_dim
from brain.testing import fake_llm
from runner.budget import BudgetedLLM, BudgetExceeded, BudgetTracker
from runner.context import PhaseOutput
from runner.pipeline import default_pipeline
from runner.search import FakeSearch
from runner.worker import Worker
from server.models import Brand, Run, RunEvent, User, now

BUDGET = {"max_wall_seconds": 36000, "max_tokens": 2_000_000, "max_cost_usd": 25,
          "max_steps": 400}


# ---------- budget unit tests (no DB) ----------

def test_budget_tracker_limits_and_wall_clock() -> None:
    t = [100.0]
    tracker = BudgetTracker({"max_steps": 2, "max_wall_seconds": 50},
                            {"wall_seconds": 10, "steps": 0}, clock=lambda: t[0])
    llm = BudgetedLLM(fake_llm(), tracker)
    llm.complete("s", "u")
    llm.complete("s", "u")
    assert tracker.spent["steps"] == 2 and tracker.spent["tokens"] > 0
    with pytest.raises(BudgetExceeded) as e:
        llm.complete("s", "u")
    assert e.value.limit == "max_steps"

    t2 = [0.0]
    wall = BudgetTracker({"max_wall_seconds": 50}, {"wall_seconds": 45}, clock=lambda: t2[0])
    wall.check()
    t2[0] = 6.0
    with pytest.raises(BudgetExceeded):
        wall.check()
    assert wall.spent["stopped_by"] == "max_wall_seconds"


# ---------- DB-backed ----------

@pytest.fixture
def brain(session_factory) -> BrandBrain:
    return BrandBrain(session_factory, fake_llm(), FakeEmbedder(dim=embed_dim()))


def make_worker(session_factory, brain, phases=None, **kw) -> Worker:
    return Worker(session_factory=session_factory, brain=brain, llm=fake_llm(),
                  search=FakeSearch(), phases=phases or default_pipeline(),
                  heartbeat_seconds=kw.pop("heartbeat_seconds", 3600), **kw)


@pytest.fixture
def queued_run(session_factory, brain):
    def _make(budget=None, status="queued", lease=None) -> uuid.UUID:
        with session_factory.begin() as s:
            u = User(email=f"r-{uuid.uuid4().hex[:8]}@example.com", display_name="r")
            s.add(u)
            s.flush()
            b = Brand(owner_id=u.id, name="Chilli Co")
            s.add(b)
            s.flush()
            brain.create_brand_space(str(b.id))
            brain.ingest(str(b.id), "Small-batch hot sauce made with Kerala chillies.",
                         source_type="challenge_answer", author="u", section_hint="one_liner",
                         source_ref="one_liner")
            run = Run(brand_id=b.id, requested_by=u.id, status=status,
                      budget=budget or dict(BUDGET), spent={}, lease_expires_at=lease,
                      checkpoint={"frozen": {"brief_version": "v1",
                                             "context_pack": brain.context_pack(str(b.id), "x")},
                                  "completed_phases": [], "outputs": {}})
            s.add(run)
            s.flush()
            return run.id
    return _make


def _run(session_factory, rid) -> Run:
    with session_factory() as s:
        return s.get(Run, rid)


def _events(session_factory, rid) -> list[RunEvent]:
    with session_factory() as s:
        return list(s.scalars(select(RunEvent).where(RunEvent.run_id == rid)
                              .order_by(RunEvent.created_at)))


def _drain(worker: Worker, rid) -> None:
    """Process runs until ours is done (other tests' runs may share the queue)."""
    for _ in range(50):
        if not worker.poll_once():
            break
        if _run(worker.session_factory, rid).status not in ("queued", "running"):
            break


@pytest.mark.db
def test_full_pipeline_completes_with_report_and_proposals(session_factory, brain,
                                                           queued_run) -> None:
    rid = queued_run()
    _drain(make_worker(session_factory, brain), rid)
    run = _run(session_factory, rid)
    assert run.status == "completed", run.error
    assert run.checkpoint["completed_phases"] == [p.name for p in default_pipeline()]
    for title in ("What we know", "Market scan", "Customer insight", "Opportunities",
                  "30-day focus plan", "Proposed brief changes"):
        assert f"## {title}" in run.report_md
    assert run.spent["steps"] == 6 and run.spent["tokens"] > 0
    assert run.lease_expires_at is None and run.finished_at is not None

    kinds = [e.kind for e in _events(session_factory, rid)]
    assert kinds.count("phase_start") == 6 and kinds.count("llm_call") == 6
    assert "search" in kinds and kinds[-1] == "completed"

    proposals = brain.list_proposals(str(run.brand_id))
    assert proposals and all(p.origin == "run" and p.origin_ref == str(rid) for p in proposals)
    # runs never write claims directly
    assert all(c.authority == "user" for c in brain.store.claims(str(run.brand_id)))


class Counting:
    def __init__(self, inner, fail_times=0):
        self.inner, self.name, self.calls, self.fail_times = inner, inner.name, 0, fail_times

    def run(self, ctx) -> PhaseOutput:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("simulated crash in phase 3")
        return self.inner.run(ctx)


@pytest.mark.db
def test_crash_then_resume_skips_completed_phases(session_factory, brain, queued_run) -> None:
    phases = [Counting(p, fail_times=1 if i == 2 else 0) for i, p in enumerate(default_pipeline())]
    rid = queued_run()
    worker = make_worker(session_factory, brain, phases=phases)
    _drain(worker, rid)
    run = _run(session_factory, rid)
    assert run.status == "failed" and "simulated crash" in run.error
    assert run.checkpoint["completed_phases"] == ["understand", "market_scan"]

    with session_factory.begin() as s:  # what `admin approve` does for a failed run
        s.get(Run, rid).status = "queued"
    _drain(worker, rid)
    run = _run(session_factory, rid)
    assert run.status == "completed", run.error
    assert [p.calls for p in phases] == [1, 1, 2, 1, 1, 1]
    assert [e.phase for e in _events(session_factory, rid) if e.kind == "phase_skip"] == [
        "understand", "market_scan"]


@pytest.mark.db
def test_budget_stop_completes_cleanly(session_factory, brain, queued_run) -> None:
    rid = queued_run(budget={**BUDGET, "max_steps": 2})
    _drain(make_worker(session_factory, brain), rid)
    run = _run(session_factory, rid)
    assert run.status == "completed"
    assert run.spent["stopped_by"] == "max_steps" and run.spent["steps"] == 2
    assert "Stopped early" in run.report_md and "_Not reached in this run._" in run.report_md
    assert run.checkpoint["completed_phases"] == ["understand", "report"]
    assert "budget_stop" in [e.kind for e in _events(session_factory, rid)]


@pytest.mark.db
def test_expired_lease_is_reclaimed_and_live_lease_is_not(session_factory, brain,
                                                         queued_run) -> None:
    live = queued_run(status="running", lease=now() + timedelta(minutes=5))
    dead = queued_run(status="running", lease=now() - timedelta(seconds=1))
    worker = make_worker(session_factory, brain)
    claimed = []
    while (rid := worker.claim()) is not None:
        claimed.append(rid)
    assert dead in claimed and live not in claimed
    msgs = [e.message for e in _events(session_factory, dead) if e.kind == "claimed"]
    assert msgs and msgs[0].startswith("reclaimed after lease expiry")


@pytest.mark.db
def test_locked_run_is_skipped(session_factory, brain, queued_run) -> None:
    rid = queued_run()
    worker = make_worker(session_factory, brain)
    with session_factory.begin() as s:  # another worker holds the row lock
        s.execute(select(Run).where(Run.id == rid).with_for_update()).scalar_one()
        while (other := worker.claim()) is not None:
            assert other != rid
    assert worker.claim() == rid  # free once the lock is released


@pytest.mark.db
def test_cancelled_before_execute_does_nothing(session_factory, brain, queued_run) -> None:
    rid = queued_run()
    worker = make_worker(session_factory, brain)
    claimed = None
    while claimed not in (rid,):
        claimed = worker.claim()
        assert claimed is not None, "our queued run was never claimed"
    with session_factory.begin() as s:
        s.get(Run, rid).status = "cancelled"
    worker.execute(rid)
    assert _run(session_factory, rid).checkpoint["completed_phases"] == []
