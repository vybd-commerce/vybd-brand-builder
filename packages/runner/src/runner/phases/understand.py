from __future__ import annotations

from pydantic import BaseModel, Field

from runner.context import PhaseOutput, RunContext
from runner.phases._common import ROLE, bullets, user_prompt


class Understanding(BaseModel):
    known: list[str] = Field(description="What the brief clearly establishes (3-8 items)")
    unknown: list[str] = Field(description="Important gaps or open questions (3-8 items)")
    focus: str = Field(description="One sentence: what this run should focus on, per the goals")


class Understand:
    name = "understand"

    def run(self, ctx: RunContext) -> PhaseOutput:
        r = ctx.llm.complete_structured(
            ROLE,
            user_prompt(ctx, "Summarize what we know and what we don't know about this brand, "
                             "and restate the founder's goal for this run in one sentence."),
            Understanding,
        ).value
        md = (f"**Focus:** {r.focus}\n\n**What we know**\n{bullets(r.known)}\n\n"
              f"**What we don't know yet**\n{bullets(r.unknown)}")
        return PhaseOutput(summary_md=md, artifacts=r.model_dump())
