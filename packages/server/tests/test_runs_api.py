"""Milestone 5: scoring, eligibility, run submit, admin approve/cancel, proposals API."""

from __future__ import annotations

import pytest

from brain.providers import FakeLLM, ProviderError
from server.challenges import ChallengeCatalog
from server.config import Settings
from server.scoring import CompletenessScorerV0  # noqa: F401  (import check)
from server.scoring.completeness_v0 import CompletenessScorerV0 as Scorer

pytestmark = pytest.mark.db

ANSWERS = {
    "one_liner": "Small-batch hot sauce made with Kerala chillies.",
    "customer": "Indian-American home cooks in their 30s who cook dal every week.",
    "problem": "Supermarket hot sauces taste sweet and vinegary.",
    "alternative": "They use Sriracha or bring chilli pickle back from India.",
    "positioning": "The only hot sauce built for Indian home cooking.",
    "product_price": "A 5oz green chilli sauce at $9.",
    "channels": "Our own website and Indian grocery stores.",
    "goals": "Decide between grocery wholesale and online for the first six months.",
}


def _answer_all(client, brand, ids=ANSWERS):
    for cid in ids:
        r = client.post(f"/v1/brands/{brand['id']}/challenges/{cid}/answer",
                        json={"text": ANSWERS.get(cid, "Diaspora Co., Brooklyn Delhi.")},
                        headers=brand["headers"])
        assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(signup, services):
    user = signup()
    services.settings.admin_emails = services.settings.admin_emails | {user["email"]}
    return user


@pytest.fixture
def ready(client, brand):
    _answer_all(client, brand)
    return brand


# ---------- scorer unit ----------

def test_scorer_arithmetic_and_eligibility() -> None:
    cat = ChallengeCatalog.load(Settings().content_dir / "challenges" / "brief_v1")
    scorer = Scorer(cat, FakeLLM())

    class A:
        def __init__(self, cid):
            self.challenge_id, self.is_current = cid, True

    from brain.brief import build_brief
    brief = build_brief("b", [])
    half = scorer.score("b", [A(c) for c in list(ANSWERS)[:4]], brief)
    assert half.total == 50.0 and len(half.missing) == 4
    assert not scorer.eligibility(half).eligible

    full = scorer.score("b", [A(c) for c in [*ANSWERS, "competitors"]], brief)
    assert full.total == 100.0 and full.missing == []  # optional bonus capped
    assert scorer.eligibility(full).eligible


def test_feedback_never_raises() -> None:
    cat = ChallengeCatalog.load(Settings().content_dir / "challenges" / "brief_v1")
    llm = FakeLLM()

    def boom(*a, **k):
        raise ProviderError("down")

    llm.complete_structured = boom
    fb = Scorer(cat, llm).feedback(cat.get("customer"), "Nurses")
    assert fb.note == "" and fb.suggestion is None


# ---------- score + feedback via API ----------

def test_score_endpoint_and_progress(client, brand) -> None:
    r = client.get(f"/v1/brands/{brand['id']}/score", headers=brand["headers"]).json()
    assert r["data"]["score"]["total"] == 0 and r["data"]["score"]["eligible"] is False
    assert len(r["data"]["score"]["missing"]) == 8
    assert r["progress"]["eligible"] is False

    body = _answer_all(client, brand, ["one_liner"])
    assert body["data"]["feedback"]["note"].startswith("fake note")
    assert body["progress"]["score"] == 12.5

    body = _answer_all(client, brand)
    assert body["progress"]["score"] == 100.0 and body["progress"]["eligible"] is True
    r = client.get(f"/v1/brands/{brand['id']}/score", headers=brand["headers"]).json()
    assert r["data"]["score"]["eligible"] is True
    assert r["next_actions"][0]["action"] == "run.submit"


# ---------- submit + lifecycle ----------

def test_submit_blocked_until_eligible(client, brand) -> None:
    r = client.post(f"/v1/brands/{brand['id']}/runs", headers=brand["headers"])
    assert r.status_code == 409
    assert r.json()["errors"][0]["code"] == "not_eligible"
    assert r.json()["next_actions"][0]["action"] == "challenge.answer"


def test_submit_then_admin_approve_and_cancel(client, ready, admin, signup) -> None:
    r = client.post(f"/v1/brands/{ready['id']}/runs", headers=ready["headers"])
    assert r.status_code == 201, r.text
    run = r.json()["data"]["run"]
    assert run["status"] == "requested" and run["budget"] == {}

    dup = client.post(f"/v1/brands/{ready['id']}/runs", headers=ready["headers"])
    assert dup.status_code == 409 and dup.json()["errors"][0]["code"] == "run_active"

    # visibility
    assert client.get(f"/v1/runs/{run['id']}", headers=ready["headers"]).status_code == 200
    stranger = signup()
    assert client.get(f"/v1/runs/{run['id']}", headers=stranger["headers"]).status_code == 404
    assert client.get(f"/v1/runs/{run['id']}", headers=admin["headers"]).status_code == 200

    # report not ready
    rep = client.get(f"/v1/runs/{run['id']}/report", headers=ready["headers"])
    assert rep.status_code == 409 and rep.json()["errors"][0]["code"] == "report_not_ready"

    # admin gate
    assert client.get("/v1/admin/runs", headers=ready["headers"]).status_code == 403
    listed = client.get("/v1/admin/runs", headers=admin["headers"]).json()["data"]["runs"]
    assert run["id"] in [x["id"] for x in listed]

    ap = client.post(f"/v1/admin/runs/{run['id']}/approve", headers=admin["headers"]).json()
    assert ap["data"]["run"]["status"] == "queued"
    assert ap["data"]["run"]["budget"]["max_wall_seconds"] == 36000
    again = client.post(f"/v1/admin/runs/{run['id']}/approve", headers=admin["headers"])
    assert again.status_code == 409

    c = client.post(f"/v1/admin/runs/{run['id']}/cancel", headers=admin["headers"]).json()
    assert c["data"]["run"]["status"] == "cancelled"
    assert client.post(f"/v1/admin/runs/{run['id']}/cancel",
                       headers=admin["headers"]).status_code == 409

    events = client.get(f"/v1/runs/{run['id']}/events", headers=ready["headers"]).json()
    assert [e["kind"] for e in events["data"]["events"]] == ["submitted", "approved", "cancelled"]

    # cancelled run no longer blocks a new submission
    assert client.post(f"/v1/brands/{ready['id']}/runs", headers=ready["headers"]).status_code \
        == 201


def test_auto_approve_and_frozen_brief(client, ready, services) -> None:
    services.settings.auto_approve_runs = True
    r = client.post(f"/v1/brands/{ready['id']}/runs", headers=ready["headers"]).json()
    run = r["data"]["run"]
    assert run["status"] == "queued" and run["budget"]["max_steps"] == 400

    from server.models import Run
    with services.session_factory() as s:
        frozen = s.get(Run, __import__("uuid").UUID(run["id"])).checkpoint["frozen"]
    assert "Small-batch hot sauce" in frozen["context_pack"]
    assert frozen["brief_version"]


# ---------- proposals ----------

def test_proposals_accept_and_reject_via_api(client, brand, services) -> None:
    brain = services.brain
    p1 = brain.propose(brand["id"], "Lead with 'made for dal, not for wings'.",
                       section="positioning", kind="idea", rationale="r", origin="run",
                       origin_ref="run-x")
    p2 = brain.propose(brand["id"], "Price at $14.", section="price", kind="decision",
                       rationale="r", origin="run", origin_ref="run-x")
    url = f"/v1/brands/{brand['id']}/proposals"
    listed = client.get(url, headers=brand["headers"]).json()
    assert [p["id"] for p in listed["data"]["proposals"]] == [p1.id, p2.id]
    assert listed["next_actions"][0]["action"] == "proposal.accept"

    acc = client.post(f"{url}/{p1.id}/accept", headers=brand["headers"]).json()
    assert acc["ok"] and "1 proposal(s) left" in acc["agent_instructions"]
    assert client.post(f"{url}/{p1.id}/accept", headers=brand["headers"]).status_code == 409

    no_reason = client.post(f"{url}/{p2.id}/reject", json={}, headers=brand["headers"])
    assert no_reason.status_code == 422
    rej = client.post(f"{url}/{p2.id}/reject", json={"reason": "Too pricey for grocery"},
                      headers=brand["headers"]).json()
    assert rej["ok"] and rej["next_actions"][0]["action"] == "brief.show"

    brief = client.get(f"/v1/brands/{brand['id']}/brief", headers=brand["headers"]).json()
    md = brief["data"]["markdown"]
    assert "made for dal" in md and "Too pricey for grocery" in md
    all_ = client.get(f"{url}?status=all", headers=brand["headers"]).json()["data"]["proposals"]
    assert {p["status"] for p in all_} == {"accepted", "rejected"}
    assert client.post(f"{url}/not-a-uuid/accept", headers=brand["headers"]).status_code == 404
