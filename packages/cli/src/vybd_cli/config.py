"""CLI config at ~/.vybd/config.toml (override dir with VYBD_HOME). Holds the token, so 0600."""

from __future__ import annotations

import os
import pathlib
import tomllib
from typing import Any

import tomli_w

DEFAULT_API_URL = "http://localhost:8000"


def home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VYBD_HOME", pathlib.Path.home() / ".vybd"))


def path() -> pathlib.Path:
    return home() / "config.toml"


def load() -> dict[str, Any]:
    p = path()
    if not p.exists():
        return {}
    try:
        return tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def save(cfg: dict[str, Any]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    clean = {k: v for k, v in cfg.items() if v is not None}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(tomli_w.dumps(clean))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def update(**values: Any) -> dict[str, Any]:
    cfg = load()
    cfg.update(values)
    save(cfg)
    return cfg


def api_url() -> str:
    return (os.environ.get("VYBD_API_URL") or load().get("api_url") or DEFAULT_API_URL).rstrip("/")
