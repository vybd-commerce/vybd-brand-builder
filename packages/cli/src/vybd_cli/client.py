"""HTTP client. Always returns an envelope dict, even for transport failures or non-JSON replies."""

from __future__ import annotations

from typing import Any

import httpx

from vybd_cli import config


class Unreachable(Exception):
    pass


def make_http() -> httpx.Client:
    """Factory (tests swap this for a TestClient bound to the app)."""
    return httpx.Client(base_url=config.api_url(), timeout=httpx.Timeout(120.0, connect=5.0))


def _error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "agent_instructions": "", "next_actions": [],
            "progress": None, "errors": [{"code": code, "message": message, "field": None}]}


def request(method: str, path: str, *, json: Any = None, params: dict | None = None,
            auth: bool = True) -> dict[str, Any]:
    headers = {}
    if auth:
        token = config.load().get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    try:
        with make_http() as http:
            resp = http.request(method, path, json=json, params=params, headers=headers)
    except httpx.TransportError as e:
        raise Unreachable(f"Can't reach the Vybd server at {config.api_url()} ({e}).") from e
    try:
        body = resp.json()
    except ValueError:
        return _error_envelope(f"http_{resp.status_code}", resp.text[:300] or resp.reason_phrase)
    if not isinstance(body, dict) or "ok" not in body:
        return _error_envelope(f"http_{resp.status_code}", str(body)[:300])
    return body
