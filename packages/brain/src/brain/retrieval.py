"""Retrieval: vector search over claims + context packs for LLM prompts."""

from __future__ import annotations

from brain.brief import build_brief
from brain.providers import Embedder
from brain.store import Store
from brain.types import BriefView, Claim


def approx_tokens(text: str) -> int:
    return len(text) // 4 + 1


class Retriever:
    def __init__(self, store: Store, embedder: Embedder):
        self.store = store
        self.embedder = embedder

    def search(self, brand_id: str, query: str, *, sections: list[str] | None,
               statuses: list[str], k: int) -> list[Claim]:
        [vec] = self.embedder.embed([query])
        return self.store.search(brand_id, vec, statuses=statuses, sections=sections, k=k)

    def context_pack(self, brand_id: str, purpose: str, max_tokens: int) -> str:
        """Brief first. If the whole brief fits the budget, return all of it; otherwise keep the
        claims most relevant to `purpose` (decisions/constraints always first) in brief order.

        # STUB: crude chars/4 token estimate and no summarization of dropped sections.
        """
        claims = self.store.claims(brand_id)
        brief = build_brief(brand_id, claims)
        header = f"# Brand brief (version {brief.version})\nPurpose: {purpose}\n\n"
        full = header + (brief.to_markdown() or "_(brief is empty)_")
        if approx_tokens(full) <= max_tokens:
            return full

        ranked = self.search(brand_id, purpose, sections=None, statuses=["accepted"],
                             k=len(claims))
        by_id = {c.id: c for c in claims}
        priority = [c.id for c in claims if c.kind in ("decision", "constraint")]
        priority += [c.id for c in ranked if c.id not in priority]
        priority += [cid for cid in by_id if cid not in priority]  # claims without embeddings

        budget = max_tokens - approx_tokens(header) - 20
        keep: set[str] = set()
        for cid in priority:
            cost = approx_tokens(by_id[cid].text) + 2
            if cost > budget:
                continue
            keep.add(cid)
            budget -= cost

        trimmed = [c for c in claims if c.id in keep]
        dropped = len(claims) - len(trimmed)
        body = _pack_markdown(build_brief(brand_id, trimmed))
        note = f"\n\n_({dropped} less relevant claims omitted for length)_" if dropped else ""
        return header + body + note


def _pack_markdown(brief: BriefView) -> str:
    return brief.to_markdown() or "_(brief is empty)_"
