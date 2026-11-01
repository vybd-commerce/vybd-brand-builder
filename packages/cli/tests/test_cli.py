from __future__ import annotations

import json
import os
import stat

import pytest
from typer.testing import CliRunner

from vybd_cli import config
from vybd_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("VYBD_HOME", str(tmp_path / "vybd"))
    monkeypatch.setenv("VYBD_API_URL", "http://127.0.0.1:9")  # nothing listens here


def test_help_lists_all_spec_commands() -> None:
    out = runner.invoke(app, ["--help"]).output
    for cmd in ("signup", "whoami", "brand", "brief", "challenge", "note", "score", "run",
                "proposals", "admin"):
        assert cmd in out
    assert "answer" in runner.invoke(app, ["challenge", "--help"]).output
    sub = runner.invoke(app, ["run", "--help"]).output
    assert all(c in sub for c in ("submit", "status", "events", "report"))
    sub = runner.invoke(app, ["admin", "--help"]).output
    assert all(c in sub for c in ("runs", "approve", "cancel"))


def test_unreachable_server_exits_2_with_json_error() -> None:
    result = runner.invoke(app, ["health", "--json"])
    assert result.exit_code == 2
    body = json.loads(result.output)
    assert body["ok"] is False and body["errors"][0]["code"] == "unreachable"


def test_no_current_brand_is_a_clear_local_error() -> None:
    result = runner.invoke(app, ["--json", "challenge", "next"])
    assert result.exit_code == 2
    assert json.loads(result.output)["errors"][0]["code"] == "no_brand"


def test_config_file_is_private() -> None:
    config.update(token="vybd_secret", current_brand="b1")
    assert config.load() == {"token": "vybd_secret", "current_brand": "b1"}
    mode = stat.S_IMODE(os.stat(config.path()).st_mode)
    assert mode == 0o600
    config.update(current_brand=None)
    assert "current_brand" not in config.load()


def test_api_url_precedence(monkeypatch) -> None:
    monkeypatch.delenv("VYBD_API_URL")
    assert config.api_url() == "http://localhost:8000"
    config.update(api_url="http://cfg:1/")
    assert config.api_url() == "http://cfg:1"
    monkeypatch.setenv("VYBD_API_URL", "http://env:2")
    assert config.api_url() == "http://env:2"
