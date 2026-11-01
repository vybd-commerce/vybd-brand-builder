from __future__ import annotations

from pydantic import BaseModel, Field

from runner.context import PhaseOutput, ProposalDraft, RunContext
from runner.phases._common import PROPOSAL_RULES, ROLE, user_prompt

MAX_QUERIES = 4


class Queries(BaseModel):
    queries: list[str] = Field(description="2-4 web searches about competitors and the category")


class Competitor(BaseModel):
    name: str
    note: str = Field(description="How they compare, one sentence")
    url: str | None = None


class Scan(BaseModel):
    summary: str = Field(description="Category and competitor landscape, 3-6 sentences")
    competitors: list[Competitor]
    proposals: list[ProposalDraft]


class MarketScan:
    name = "market_scan"

    def run(self, ctx: RunContext) -> PhaseOutput:
        q = ctx.llm.complete_structured(
            ROLE, user_prompt(ctx, "Write 2-4 web search queries to map this brand's category "
                                   "and closest competitors.", "understand"),
            Queries,
        ).value
        results = []
        for query in q.queries[:MAX_QUERIES]:
            hits = ctx.search.query(query)
            ctx.log("search", query, provider=ctx.search.name, results=len(hits))
            results += [h.model_dump() for h in hits]
        sources = "\n".join(f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in results)
        scan = ctx.llm.complete_structured(
            ROLE,
            user_prompt(ctx, "Summarize the competitive landscape using the search results "
                             "(cite source links inline where you use them; say so if the "
                             "results are thin). " + PROPOSAL_RULES, "understand",
                        extra=f"SEARCH RESULTS ({ctx.search.name}):\n{sources or '(none)'}"),
            Scan,
        ).value
        comp = "\n".join(
            f"- **{c.name}**: {c.note}" + (f" ([link]({c.url}))" if c.url else "")
            for c in scan.competitors
        ) or "- (none identified)"
        md = f"{scan.summary}\n\n**Competitors**\n{comp}"
        if ctx.search.name == "fake":
            md += "\n\n_Note: search used the fake provider; results are placeholders._"
        return PhaseOutput(summary_md=md, proposals=scan.proposals,
                           artifacts={"queries": q.queries, "sources": results,
                                      "competitors": [c.model_dump() for c in scan.competitors]})
