from __future__ import annotations

from pydantic import BaseModel, Field

from runner.context import PhaseOutput, RunContext
from runner.phases._common import ROLE, user_prompt


class Opportunity(BaseModel):
    title: str
    rationale: str
    impact: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    effort: int = Field(ge=1, le=5, description="1 = easy, 5 = hard")


class OpportunityList(BaseModel):
    opportunities: list[Opportunity] = Field(description="5-10 growth opportunities")


def priority(o: Opportunity) -> float:
    return o.impact * o.confidence / o.effort


class Opportunities:
    name = "opportunities"

    def run(self, ctx: RunContext) -> PhaseOutput:
        r = ctx.llm.complete_structured(
            ROLE,
            user_prompt(ctx, "List 5-10 concrete growth opportunities for the next 90 days. "
                             "Score each 1-5 for impact, confidence and effort.",
                        "understand", "market_scan", "customer_insight"),
            OpportunityList,
        ).value
        ranked = sorted(r.opportunities, key=priority, reverse=True)
        rows = "\n".join(
            f"| {o.title} | {o.impact} | {o.confidence} | {o.effort} | {o.rationale} |"
            for o in ranked
        )
        md = ("| Opportunity | Impact | Confidence | Effort | Why |\n|---|---|---|---|---|\n"
              + (rows or "| (none) | | | | |"))
        return PhaseOutput(summary_md=md,
                           artifacts={"opportunities": [o.model_dump() for o in ranked]})
