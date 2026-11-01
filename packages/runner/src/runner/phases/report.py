"""Assembles phase summaries into the report and collects proposals. No LLM call, so it can
always run — including after a budget stop."""

from __future__ import annotations

from datetime import UTC, datetime

from runner.context import PhaseOutput, ProposalDraft, RunContext

SECTIONS = [
    ("understand", "What we know"),
    ("market_scan", "Market scan"),
    ("customer_insight", "Customer insight"),
    ("opportunities", "Opportunities"),
    ("focus_plan", "30-day focus plan"),
]


class Report:
    name = "report"

    def run(self, ctx: RunContext) -> PhaseOutput:
        spent = ctx.spent()
        lines = [
            f"# Brand Brain report: {ctx.brand_name}",
            "",
            f"_Run `{ctx.run_id}` · brief v{ctx.frozen.get('brief_version', '?')} · "
            f"{datetime.now(UTC):%Y-%m-%d} · {spent.get('steps', 0)} model calls, "
            f"{spent.get('tokens', 0)} tokens, ${spent.get('cost_usd', 0):.2f}_",
            "",
        ]
        if ctx.stopped_by:
            lines += [f"> **Stopped early:** the run hit its `{ctx.stopped_by}` budget limit. "
                      "Sections below cover what was finished.", ""]
        for key, title in SECTIONS:
            out = ctx.outputs.get(key)
            lines += [f"## {title}", "", out.summary_md if out else "_Not reached in this run._",
                      ""]

        proposals: list[ProposalDraft] = []
        seen: set[str] = set()
        for key, _ in SECTIONS:
            for p in (ctx.outputs[key].proposals if key in ctx.outputs else []):
                norm = " ".join(p.text.lower().split())
                if norm and norm not in seen:
                    seen.add(norm)
                    proposals.append(p)
        lines += ["## Proposed brief changes", ""]
        if proposals:
            lines += [f"{i}. **{p.text}** ({p.section}, {p.kind}): {p.rationale}"
                      for i, p in enumerate(proposals, 1)]
            lines += ["", "_Review with `vybd proposals`. Nothing changes until you accept._"]
        else:
            lines.append("_No changes proposed._")
        return PhaseOutput(summary_md="\n".join(lines).strip() + "\n", proposals=proposals)
