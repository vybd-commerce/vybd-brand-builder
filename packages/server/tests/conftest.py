from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from brain import BrandBrain
from brain.providers import FakeEmbedder, embed_dim
from brain.testing import fake_llm
from server.config import Settings
from server.main import create_app
from server.services import Services


@pytest.fixture
def services(session_factory) -> Services:
    brain = BrandBrain(session_factory, fake_llm(), FakeEmbedder(dim=embed_dim()))
    settings = Settings(admin_emails=frozenset({"admin@vybd.test"}))
    return Services(settings, session_factory=session_factory, brain=brain)


@pytest.fixture
def client(services) -> TestClient:
    return TestClient(create_app(services=services))


@pytest.fixture
def signup(client):
    def _signup(email: str | None = None) -> dict:
        email = email or f"founder-{uuid.uuid4().hex[:10]}@example.com"
        r = client.post("/v1/auth/signup", json={"email": email})
        assert r.status_code == 201, r.text
        return {"email": email, "headers": {"Authorization": f"Bearer {r.json()['data']['token']}"}}

    return _signup


@pytest.fixture
def brand(client, signup):
    user = signup()
    r = client.post("/v1/brands", json={"name": "Chilli Co"}, headers=user["headers"])
    assert r.status_code == 201, r.text
    return {"id": r.json()["data"]["brand"]["id"], **user}
