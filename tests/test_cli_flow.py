"""Full brief through the real `vybd` CLI against the real app (in-process), fake providers."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from brain import BrandBrain
from brain.providers import FakeEmbedder, embed_dim
from brain.testing import fake_llm
from server.config import Settings
from server.main import create_app
from server.services import Services
from vybd_cli import client, config
from vybd_cli.main import app as cli

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


@pytest.fixture
def run(session_factory, tmp_path, monkeypatch):
    brain = BrandBrain(session_factory, fake_llm(), FakeEmbedder(dim=embed_dim()))
    services = Services(Settings(), session_factory=session_factory, brain=brain)
    api = create_app(services=services)
    monkeypatch.setenv("VYBD_HOME", str(tmp_path / "vybd"))
    monkeypatch.setattr(client, "make_http", lambda: TestClient(api))
    runner = CliRunner()

    def _run(*args: str, ok: bool = True) -> dict:
        result = runner.invoke(cli, ["--json", *args])
        body = json.loads(result.output)
        assert (result.exit_code == 0) == ok, result.output
        return body

    return _run


def test_full_brief_via_cli(run) -> None:
    email = f"cli-{uuid.uuid4().hex[:8]}@example.com"
    assert run("signup", "--email", email)["data"]["user"]["email"] == email
    assert config.load()["token"].startswith("vybd_")
    assert run("whoami")["data"]["user"]["brand_count"] == 0

    brand = run("brand", "create", "Chilli Co")["data"]["brand"]
    assert config.load()["current_brand"] == brand["id"]
    assert run("brand", "list")["data"]["brands"][0]["id"] == brand["id"]

    # drive it the way an agent would: follow challenge.next until done
    seen = []
    while True:
        nxt = run("challenge", "next")
        ch = nxt["data"]["challenge"]
        if ch is None:
            break
        if ch["id"] == "competitors":
            assert "run.submit" in [a["action"] for a in nxt["next_actions"]]
            answer = "Diaspora Co., Brooklyn Delhi."
        else:
            answer = ANSWERS[ch["id"]]
        res = run("challenge", "answer", ch["id"], "--text", answer)
        assert res["data"]["claims"], res
        seen.append(ch["id"])
    assert seen == [*ANSWERS, "competitors"]  # required in order, then the optional one

    run("note", "We sell 40 bottles a month at a farmers market.")
    brief = run("brief")["data"]
    assert brief["claim_count"] >= 10
    assert run("brief", "--section", "goals")["data"]["sections"][0]["key"] == "goals"
    statuses = {c["id"]: c["status"] for c in run("challenge", "list")["data"]["challenges"]}
    assert set(statuses.values()) == {"answered"}

    # error envelope passes through with exit 1
    err = run("challenge", "answer", "customer", "--text", "everyone", ok=False)
    assert err["errors"][0]["code"] == "answer_too_short"

    # brand use rejects ids you don't own
    assert run("brand", "use", str(uuid.uuid4()), ok=False)["errors"][0]["code"] == "not_found"
    assert run("brand", "use", brand["id"])["data"]["current_brand"] == brand["id"]
