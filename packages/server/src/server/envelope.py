"""Agent-facing response envelope (spec §8). Every API response uses it.

`next_actions[].action` names are stable identifiers; they become MCP tool names later
(`challenge.answer` → `challenge_answer`). Keep ACTIONS in sync with the CLI.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# action -> (cli template, description)
ACTIONS: dict[str, tuple[str, str]] = {
    "auth.signup": ('vybd signup --email "{email}"', "Create an account and store the token."),
    "auth.whoami": ("vybd whoami", "Show the signed-in user."),
    "brand.create": ('vybd brand create "{name}"', "Create a brand and make it current."),
    "brand.list": ("vybd brand list", "List your brands."),
    "brand.use": ("vybd brand use {brand_id}", "Switch the current brand (client-side)."),
    "brief.show": ("vybd brief", "Show the brand brief built so far."),
    "challenge.next": ("vybd challenge next", "Get the next challenge to work on."),
    "challenge.list": ("vybd challenge list", "List all challenges and their status."),
    "challenge.answer": (
        'vybd challenge answer {challenge_id} --text "..."',
        "Submit the founder's answer to this challenge, in their own words.",
    ),
    "note.add": ('vybd note "..."', "Add a free-form note to the brand brain."),
    "score.show": ("vybd score", "Show the brief score and run eligibility."),
    "run.submit": ("vybd run submit", "Submit the brief for a Brand Brain run."),
    "run.status": ("vybd run status {run_id}", "Check a run's status."),
    "run.events": ("vybd run events {run_id}", "Show a run's event log."),
    "run.report": ("vybd run report {run_id}", "Show a finished run's report."),
    "proposal.list": ("vybd proposals", "List proposed brief changes."),
    "proposal.accept": ("vybd proposals accept {proposal_id}", "Accept a proposal."),
    "proposal.reject": (
        'vybd proposals reject {proposal_id} --reason "..."',
        "Reject a proposal with a reason.",
    ),
    "admin.runs": ("vybd admin runs", "List runs awaiting approval."),
    "admin.approve": ("vybd admin approve {run_id}", "Approve a requested run."),
    "admin.cancel": ("vybd admin cancel {run_id}", "Cancel a run."),
}


class NextAction(BaseModel):
    action: str
    cli: str
    description: str


class Progress(BaseModel):
    completed: int
    required: int
    est_minutes_left: float
    score: float | None = None
    eligible: bool | None = None


class ErrorItem(BaseModel):
    code: str
    message: str
    field: str | None = None


class Envelope(BaseModel):
    ok: bool = True
    data: Any = Field(default_factory=dict)
    agent_instructions: str = ""
    next_actions: list[NextAction] = Field(default_factory=list)
    progress: Progress | None = None
    errors: list[ErrorItem] = Field(default_factory=list)


def action(action_id: str, /, description: str | None = None, **fmt: str) -> NextAction:
    cli, default_desc = ACTIONS[action_id]
    for k, v in fmt.items():
        cli = cli.replace("{" + k + "}", str(v))
    return NextAction(action=action_id, cli=cli, description=description or default_desc)


def ok(data: Any = None, *, instructions: str = "", next_actions: list[NextAction] | None = None,
       progress: Progress | dict | None = None) -> dict:
    if isinstance(progress, dict):
        progress = Progress(**progress)
    return Envelope(
        ok=True, data=data if data is not None else {}, agent_instructions=instructions,
        next_actions=next_actions or [], progress=progress,
    ).model_dump(mode="json")


def error(code: str, message: str, *, field: str | None = None, instructions: str = "",
          next_actions: list[NextAction] | None = None) -> dict:
    return Envelope(
        ok=False, data=None, agent_instructions=instructions, next_actions=next_actions or [],
        errors=[ErrorItem(code=code, message=message, field=field)],
    ).model_dump(mode="json")
