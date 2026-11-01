"""Shared prompt scaffolding for phases."""

from __future__ import annotations

from runner.context import RunContext

ROLE = (
    "You are the Vybd Brand Brain, a pragmatic early-stage brand strategist working for a "
    "founder. Ground everything in their brand brief. Never invent facts about the brand; "
    "label assumptions as assumptions. Be concrete and brief. Respect decisions already in the "
    "brief, including rejected suggestions: never re-propose something the founder rejected."
)

PROPOSAL_RULES = (
    "`proposals`: 0-2 suggested additions or sharper versions of brief statements, only when "
    "you have a genuinely better line grounded in the brief. Each is one sentence in the "
    "founder's voice, with a section key, a kind, and a short rationale. Empty list is fine."
)


def user_prompt(ctx: RunContext, task: str, *prior: str, extra: str = "") -> str:
    parts = [f"TASK: {task}", f"BRAND: {ctx.brand_name}", "BRAND BRIEF:", ctx.brief]
    if prior:
        parts += ["EARLIER RESEARCH IN THIS RUN:", ctx.prior(*prior)]
    if extra:
        parts.append(extra)
    parts.append("Now do the TASK above, grounded in the brief.")
    return "\n\n".join(parts)


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"
