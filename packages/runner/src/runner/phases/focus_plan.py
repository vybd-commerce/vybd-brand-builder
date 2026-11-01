from __future__ import annotations

from pydantic import BaseModel, Field

from runner.context import PhaseOutput, ProposalDraft, RunContext
from runner.phases._common import PROPOSAL_RULES, ROLE, bullets, user_prompt


class Week(BaseModel):
    week: int = Field(ge=1, le=5)
    steps: list[str]


class PlanOut(BaseModel):
    top3: list[str] = Field(description="The 3 opportunities to focus on, by title")
    why: str
    weeks: list[Week] = Field(description="A 30-day plan, week by week, concrete next steps")
    proposals: list[ProposalDraft]


class FocusPlan:
    name = "focus_plan"

    def run(self, ctx: RunContext) -> PhaseOutput:
        r = ctx.llm.complete_structured(
            ROLE,
            user_prompt(ctx, "Pick the top 3 opportunities and write a 30-day focus plan with "
                             "concrete weekly steps a small team can actually do. "
                             + PROPOSAL_RULES, "understand", "customer_insight", "opportunities"),
            PlanOut,
        ).value
        weeks = "\n\n".join(f"**Week {w.week}**\n{bullets(w.steps)}"
                            for w in sorted(r.weeks, key=lambda w: w.week))
        md = f"**Top 3**\n{bullets(r.top3)}\n\n{r.why}\n\n{weeks}"
        return PhaseOutput(summary_md=md, proposals=r.proposals,
                           artifacts=r.model_dump(exclude={"proposals"}))
