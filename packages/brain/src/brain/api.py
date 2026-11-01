"""BrandBrain — the only interface the rest of the system uses (spec §5)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from brain import curator
from brain.brief import build_brief
from brain.providers import Embedder, LLMProvider
from brain.retrieval import Retriever
from brain.store import NewClaim, Store
from brain.types import (
    CLAIM_KINDS,
    USER_SOURCE_TYPES,
    BriefView,
    Claim,
    IngestResult,
    Proposal,
)

DEFAULT_STATUSES = ("accepted",)


class BrandBrain:
    def __init__(self, session_factory: sessionmaker[Session], llm: LLMProvider,
                 embedder: Embedder):
        self.llm = llm
        self.embedder = embedder
        self.store = Store(session_factory, embed_model=embedder.model)
        self.retriever = Retriever(self.store, embedder)

    # --- tenancy ---
    def create_brand_space(self, brand_id: str) -> None:
        self.store.create_brand_space(brand_id)

    # --- ingestion ---
    def ingest(self, brand_id: str, content: str, *, source_type: str, author: str,
               section_hint: str | None = None, source_ref: str | None = None) -> IngestResult:
        """Store raw input, run the curator, return claims created.

        User-authored sources (challenge_answer, note, import) become `accepted` claims.
        Run output must go through propose(), never ingest().
        Re-answering a challenge (source_type=challenge_answer + same source_ref) supersedes the
        claims from the earlier answer to that challenge.
        """
        if source_type not in USER_SOURCE_TYPES:
            raise ValueError(
                f"source_type {source_type!r} cannot write claims directly; "
                f"allowed: {sorted(USER_SOURCE_TYPES)} (run output must use propose())"
            )
        if not content.strip():
            raise ValueError("content is empty")

        raw_id = self.store.add_raw_input(
            brand_id, content=content, source_type=source_type, author=author,
            section_hint=section_hint, source_ref=source_ref,
        )
        # LLM + embedding calls happen outside any DB transaction.
        extracted, llm_result = curator.extract(self.llm, content, section_hint)
        vectors = self.embedder.embed([c.text for c in extracted])
        new = [
            NewClaim(
                text=c.text, section=c.section, kind=c.kind, confidence=c.confidence,
                excerpt=c.excerpt or content.strip()[:500], embedding=v, authority="user",
            )
            for c, v in zip(extracted, vectors, strict=True)
        ]
        supersede = (
            (source_type, source_ref)
            if source_type == "challenge_answer" and source_ref
            else None
        )
        claims, superseded = self.store.commit_claims(
            brand_id, raw_id, new, supersede_origin=supersede
        )
        return IngestResult(
            raw_input_id=raw_id, claims=claims, superseded_claim_ids=superseded,
            model=llm_result.model, input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
        )

    # --- reading ---
    def brief(self, brand_id: str) -> BriefView:
        return build_brief(brand_id, self.store.claims(brand_id))

    def search(self, brand_id: str, query: str, *, sections: list[str] | None = None,
               statuses: list[str] | None = None, k: int = 10) -> list[Claim]:
        return self.retriever.search(
            brand_id, query, sections=sections, statuses=list(statuses or DEFAULT_STATUSES), k=k
        )

    def context_pack(self, brand_id: str, purpose: str, max_tokens: int = 4000) -> str:
        return self.retriever.context_pack(brand_id, purpose, max_tokens)

    # --- proposals ---
    def propose(self, brand_id: str, text: str, *, section: str, kind: str, rationale: str,
                origin: str, origin_ref: str | None = None) -> Proposal:
        if kind not in CLAIM_KINDS:
            raise ValueError(f"kind must be one of {CLAIM_KINDS}")
        if not text.strip():
            raise ValueError("proposal text is empty")
        return self.store.add_proposal(
            brand_id, text=text.strip(), section=curator.normalize_section(section, None),
            kind=kind, rationale=rationale, origin=origin, origin_ref=origin_ref,
        )

    def list_proposals(self, brand_id: str, status: str | None = "pending") -> list[Proposal]:
        """status=None lists all."""
        return self.store.proposals(brand_id, status)

    def accept_proposal(self, brand_id: str, proposal_id: str, by: str) -> Claim:
        p = self.store.get_pending_proposal(brand_id, proposal_id)
        [vec] = self.embedder.embed([p.text])
        return self.store.decide_proposal(
            brand_id, proposal_id, status="accepted", by=by, note=None,
            raw_input={"source_type": "proposal_accept", "source_ref": proposal_id,
                       "author": by, "section_hint": p.section, "content": p.text},
            claim=NewClaim(text=p.text, section=p.section, kind=p.kind, confidence=1.0,
                           excerpt=p.text, embedding=vec, authority="user_approved"),
        )

    def reject_proposal(self, brand_id: str, proposal_id: str, by: str, reason: str) -> None:
        """Rejection reason is stored as an accepted `decision` claim so it isn't re-proposed."""
        p = self.store.get_pending_proposal(brand_id, proposal_id)
        reason = reason.strip() or "no reason given"
        text = f'Rejected suggestion "{p.text}". Reason: {reason}'
        [vec] = self.embedder.embed([text])
        self.store.decide_proposal(
            brand_id, proposal_id, status="rejected", by=by, note=reason,
            raw_input={"source_type": "proposal_reject", "source_ref": proposal_id,
                       "author": by, "section_hint": p.section, "content": reason},
            claim=NewClaim(text=text, section=p.section, kind="decision", confidence=1.0,
                           excerpt=reason, embedding=vec, authority="user"),
        )
