from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import create_app


def test_healthz_needs_no_db() -> None:
    resp = TestClient(create_app()).get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["next_actions"][0]["action"] == "auth.signup"
