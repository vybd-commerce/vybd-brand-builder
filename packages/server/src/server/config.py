"""Server settings from env. Read once per app instance (create_app)."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


@dataclass
class Settings:
    content_dir: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(
            os.environ.get("CONTENT_DIR", REPO_ROOT / "content")
        )
    )
    challenge_set: str = field(default_factory=lambda: os.environ.get("CHALLENGE_SET", "brief_v1"))
    admin_emails: frozenset[str] = field(
        default_factory=lambda: frozenset(
            e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
        )
    )
    auto_approve_runs: bool = field(default_factory=lambda: _bool("AUTO_APPROVE_RUNS"))
    scorer: str = field(default_factory=lambda: os.environ.get("SCORER", "completeness_v0"))
    run_budget: dict = field(default_factory=lambda: default_run_budget())


def default_run_budget() -> dict:
    """RUN_BUDGET_* env → budget stored on each run at approval time. $ values are placeholders."""
    e = os.environ.get
    return {
        "max_wall_seconds": int(e("RUN_BUDGET_MAX_WALL_SECONDS", "36000")),
        "max_tokens": int(e("RUN_BUDGET_MAX_TOKENS", "2000000")),
        "max_cost_usd": float(e("RUN_BUDGET_MAX_COST_USD", "25")),
        "max_steps": int(e("RUN_BUDGET_MAX_STEPS", "400")),
    }
