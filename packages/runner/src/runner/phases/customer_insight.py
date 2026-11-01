from __future__ import annotations

from pydantic import BaseModel, Field

from runner.context import PhaseOutput, ProposalDraft, RunContext
from runner.phases._common import PROPOSAL_RULES, ROLE, bullets, user_prompt


class Hypothesis(BaseModel):
    hypothesis: str
    test: str = Field(description="A cheap way to test it within two weeks")


class Insight(BaseModel):
    hypotheses: list[Hypothesis] = Field(description="3-5 hypotheses about the customer")
    objections: list[str] = Field(description="Likely reasons they would not buy")
    summary: str
    proposals: list[ProposalDraft]


class CustomerInsight:
    name = "customer_insight"

    def run(self, ctx: RunContext) -> PhaseOutput:
        r = ctx.llm.complete_structured(
            ROLE,
            user_prompt(ctx, "Form hypotheses about the first customer, the alternatives they "
                             "use and their objections, each with a cheap test. "
                             + PROPOSAL_RULES, "understand", "market_scan"),
            Insight,
        ).value
        hyp = "\n".join(f"- {h.hypothesis}  \n  _Test:_ {h.test}" for h in r.hypotheses)
        md = (f"{r.summary}\n\n**Hypotheses**\n{hyp or '- (none)'}\n\n"
              f"**Likely objections**\n{bullets(r.objections)}")
        return PhaseOutput(summary_md=md, proposals=r.proposals,
                           artifacts=r.model_dump(exclude={"proposals"}))
