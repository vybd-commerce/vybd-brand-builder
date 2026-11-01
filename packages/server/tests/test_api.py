"""Server core API (Milestone 3) against real Postgres + fake providers."""

from __future__ import annotations

import pytest

from brain.providers import ProviderError
from server.challenges import ChallengeCatalog
from server.config import Settings

pytestmark = pytest.mark.db

ANSWERS = {
    "one_liner": "Small-batch hot sauce made with Kerala chillies.",
    "customer": "Indian-American home cooks in their 30s who cook dal every week and shop at "
                "Patel Brothers.",
    "problem": "Supermarket hot sauces taste sweet and vinegary. They don't suit Indian food.",
    "alternative": "They use Sriracha or bring chilli pickle back from India. Neither is right.",
    "positioning": "The only hot sauce built for Indian home cooking.",
    "product_price": "A 5oz bottle of green chilli sauce at $9.",
    "channels": "Our own website and Indian grocery stores.",
    "competitors": "Diaspora Co., Brooklyn Delhi.",
    "goals": "Decide between grocery wholesale and online for the first six months.",
}


def _envelope_ok(body: dict) -> None:
    assert set(body) == {"ok", "data", "agent_instructions", "next_actions", "progress", "errors"}
    for a in body["next_actions"]:
        assert set(a) == {"action", "cli", "description"}


def _answer(client, brand, cid, text=None):
    return client.post(f"/v1/brands/{brand['id']}/challenges/{cid}/answer",
                       json={"text": text or ANSWERS[cid]}, headers=brand["headers"])


# ---------- content ----------

def test_challenge_catalog_matches_spec() -> None:
    cat = ChallengeCatalog.load(Settings().content_dir / "challenges" / "brief_v1")
    assert [c.id for c in cat.challenges] == list(ANSWERS)
    assert len(cat.required) == 8 and not cat.get("competitors").required
    assert 9 <= sum(c.est_minutes for c in cat.challenges) <= 11
    assert all(len(c.lesson.split()) < 60 for c in cat.challenges)
    assert cat.get("product_price").section == "product"


# ---------- auth ----------

def test_signup_me_and_auth_errors(client, signup) -> None:
    user = signup("Ash@Example.com")
    r = client.get("/v1/me", headers=user["headers"])
    assert r.status_code == 200
    body = r.json()
    _envelope_ok(body)
    assert body["data"]["user"]["email"] == "ash@example.com"
    assert body["next_actions"][0]["action"] == "brand.create"

    dup = client.post("/v1/auth/signup", json={"email": "ash@example.com"})
    assert dup.status_code == 409 and dup.json()["errors"][0]["code"] == "email_taken"

    assert client.get("/v1/me").status_code == 401
    bad = client.get("/v1/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.json()["ok"] is False

    assert client.post("/v1/auth/signup", json={"email": "not-an-email"}).status_code == 422


def test_admin_flag(client, signup) -> None:
    admin = signup("admin@vybd.test")
    assert client.get("/v1/me", headers=admin["headers"]).json()["data"]["user"]["is_admin"]


# ---------- brands ----------

def test_brand_create_list_and_isolation(client, brand, signup) -> None:
    r = client.get("/v1/brands", headers=brand["headers"])
    assert [b["id"] for b in r.json()["data"]["brands"]] == [brand["id"]]

    other = signup()
    assert client.get("/v1/brands", headers=other["headers"]).json()["data"]["brands"] == []
    r = client.get(f"/v1/brands/{brand['id']}/brief", headers=other["headers"])
    assert r.status_code == 404
    assert client.get("/v1/brands/not-a-uuid/brief", headers=other["headers"]).status_code == 404


# ---------- challenges ----------

def test_next_starts_at_first_required(client, brand) -> None:
    r = client.get(f"/v1/brands/{brand['id']}/challenges/next", headers=brand["headers"])
    body = r.json()
    _envelope_ok(body)
    assert body["data"]["challenge"]["id"] == "one_liner"
    assert body["progress"]["completed"] == 0 and body["progress"]["required"] == 8
    assert "Ask, don't answer for them" in body["agent_instructions"]
    assert body["next_actions"][0]["cli"].startswith("vybd challenge answer one_liner")


def test_answer_too_short_and_unknown_challenge(client, brand) -> None:
    r = _answer(client, brand, "customer", "everyone")
    assert r.status_code == 422
    body = r.json()
    assert body["errors"][0]["code"] == "answer_too_short"
    assert body["next_actions"][0]["action"] == "challenge.answer"
    assert _answer(client, brand, "nope", "x" * 50).status_code == 404


def test_answer_saves_claims_and_advances(client, brand) -> None:
    r = _answer(client, brand, "problem")
    assert r.status_code == 200, r.text
    body = r.json()
    _envelope_ok(body)
    assert [c["section"] for c in body["data"]["claims"]] == ["problem", "problem"]
    assert body["data"]["next_challenge"]["id"] == "one_liner"  # still first unanswered required
    assert body["progress"]["completed"] == 1

    brief = client.get(f"/v1/brands/{brand['id']}/brief?section=problem",
                       headers=brand["headers"]).json()["data"]
    assert [s["key"] for s in brief["sections"]] == ["problem"]
    assert len(brief["sections"][0]["claims"]) == 2


def test_reanswer_replaces_previous(client, brand) -> None:
    _answer(client, brand, "positioning", "Cheaper than everything else on the shelf.")
    r = _answer(client, brand, "positioning", "The only hot sauce built for Indian home cooking.")
    assert len(r.json()["data"]["superseded_claim_ids"]) == 1
    assert "replaces the earlier answer" in r.json()["agent_instructions"]

    brief = client.get(f"/v1/brands/{brand['id']}/brief?section=positioning",
                       headers=brand["headers"]).json()["data"]
    assert [c["text"] for c in brief["sections"][0]["claims"]] == [
        "The only hot sauce built for Indian home cooking."
    ]
    items = client.get(f"/v1/brands/{brand['id']}/challenges",
                       headers=brand["headers"]).json()["data"]["challenges"]
    pos = next(i for i in items if i["id"] == "positioning")
    assert pos["status"] == "answered" and pos["answer"].startswith("The only")


def test_full_brief_flow_required_then_optional_then_done(client, brand) -> None:
    required = [c for c in ANSWERS if c != "competitors"]
    for cid in required:
        body = _answer(client, brand, cid).json()
        assert body["ok"], body
    # all required done → optional competitors offered, run.submit available
    assert body["data"]["next_challenge"]["id"] == "competitors"
    assert body["progress"]["completed"] == 8
    assert "run.submit" in [a["action"] for a in body["next_actions"]]

    body = _answer(client, brand, "competitors").json()
    assert body["data"]["next_challenge"] is None
    assert body["next_actions"][0]["action"] == "run.submit"

    nxt = client.get(f"/v1/brands/{brand['id']}/challenges/next", headers=brand["headers"]).json()
    assert nxt["data"]["challenge"] is None

    brief = client.get(f"/v1/brands/{brand['id']}/brief", headers=brand["headers"]).json()["data"]
    filled = {s["key"] for s in brief["sections"] if s["claims"]}
    assert filled == {"one_liner", "customer", "problem", "alternative", "positioning",
                      "product", "channels", "competitors", "goals"}
    assert brief["empty_sections"] == ["price"]  # fake curator doesn't split product/price
    assert "## Positioning" in brief["markdown"]


# ---------- notes ----------

def test_note_goes_into_brain(client, brand) -> None:
    r = client.post(f"/v1/brands/{brand['id']}/notes",
                    json={"text": "We already sell 40 bottles a month at a farmers market."},
                    headers=brand["headers"])
    assert r.status_code == 201
    assert r.json()["data"]["claims"][0]["section"] == "other"
    brief = client.get(f"/v1/brands/{brand['id']}/brief", headers=brand["headers"]).json()["data"]
    assert brief["claim_count"] == 1
    empty = client.post(f"/v1/brands/{brand['id']}/notes", json={"text": "  "},
                        headers=brand["headers"])
    assert empty.status_code == 422


# ---------- failure modes ----------

def test_provider_failure_returns_retryable_envelope_and_records_nothing(client, brand,
                                                                         services) -> None:
    def boom(*_a, **_k):
        raise ProviderError("upstream 503")

    services.brain.llm.complete_structured = boom
    r = _answer(client, brand, "one_liner")
    assert r.status_code == 502
    body = r.json()
    assert body["errors"][0]["code"] == "provider_unavailable"
    assert "Retry" in body["agent_instructions"]
    nxt = client.get(f"/v1/brands/{brand['id']}/challenges/next", headers=brand["headers"])
    assert nxt.json()["progress"]["completed"] == 0


def test_validation_error_is_enveloped(client, brand) -> None:
    r = client.post(f"/v1/brands/{brand['id']}/challenges/one_liner/answer", json={},
                    headers=brand["headers"])
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "invalid_request"
    assert r.json()["errors"][0]["field"] == "text"


def test_ui_page_and_brand_runs(client, brand) -> None:
    r = client.get("/ui")
    assert r.status_code == 200 and "Vybd Brand View" in r.text
    runs = client.get(f"/v1/brands/{brand['id']}/runs", headers=brand["headers"]).json()
    assert runs["ok"] and runs["data"]["runs"] == []
