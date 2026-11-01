"""All DB access for the brain. Nothing else in the package issues SQL."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from brain.models import BrandSpaceRow, ClaimEvidenceRow, ClaimRow, ProposalRow, RawInputRow
from brain.types import (
    BrandSpaceNotFound,
    Claim,
    Evidence,
    Proposal,
    ProposalAlreadyDecided,
    ProposalNotFound,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as e:
        raise ProposalNotFound(value) from e


def claim_from_row(row: ClaimRow, evidence: Sequence[ClaimEvidenceRow] = ()) -> Claim:
    return Claim(
        id=str(row.id),
        brand_id=row.brand_id,
        text=row.text,
        section=row.section,
        kind=row.kind,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        authority=row.authority,
        confidence=row.confidence,
        supersedes_id=str(row.supersedes_id) if row.supersedes_id else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        evidence=[Evidence(raw_input_id=str(e.raw_input_id), excerpt=e.excerpt) for e in evidence],
    )


def proposal_from_row(row: ProposalRow) -> Proposal:
    return Proposal(
        id=str(row.id),
        brand_id=row.brand_id,
        text=row.text,
        section=row.section,
        kind=row.kind,  # type: ignore[arg-type]
        rationale=row.rationale,
        origin=row.origin,
        origin_ref=row.origin_ref,
        status=row.status,  # type: ignore[arg-type]
        decided_by=row.decided_by,
        decision_note=row.decision_note,
        resulting_claim_id=str(row.resulting_claim_id) if row.resulting_claim_id else None,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@dataclass(kw_only=True)
class NewClaim:
    """A claim about to be inserted."""

    text: str
    section: str
    kind: str
    confidence: float
    excerpt: str
    embedding: list[float] | None
    authority: str
    status: str = "accepted"


class Store:
    def __init__(self, session_factory: sessionmaker[Session], embed_model: str):
        self.sf = session_factory
        self.embed_model = embed_model

    # ---------- tenancy ----------

    def create_brand_space(self, brand_id: str) -> None:
        with self.sf.begin() as s:
            s.execute(
                pg_insert(BrandSpaceRow)
                .values(brand_id=brand_id, created_at=_now())
                .on_conflict_do_nothing()
            )

    def _require_brand(self, s: Session, brand_id: str) -> None:
        if s.get(BrandSpaceRow, brand_id) is None:
            raise BrandSpaceNotFound(brand_id)

    def require_brand(self, brand_id: str) -> None:
        with self.sf() as s:
            self._require_brand(s, brand_id)

    # ---------- raw inputs + claims ----------

    def add_raw_input(self, brand_id: str, *, content: str, source_type: str, author: str,
                      section_hint: str | None, source_ref: str | None) -> str:
        with self.sf.begin() as s:
            self._require_brand(s, brand_id)
            row = RawInputRow(
                id=uuid.uuid4(), brand_id=brand_id, content=content, source_type=source_type,
                author=author, section_hint=section_hint, source_ref=source_ref,
                created_at=_now(),
            )
            s.add(row)
        return str(row.id)

    def commit_claims(self, brand_id: str, raw_input_id: str, claims: Iterable[NewClaim], *,
                      supersede_origin: tuple[str, str] | None = None
                      ) -> tuple[list[Claim], list[str]]:
        """Insert claims + evidence, optionally superseding earlier claims from the same origin
        (source_type, source_ref), and mark the raw input processed. One transaction."""
        raw_id = uuid.UUID(raw_input_id)
        superseded: list[str] = []
        with self.sf.begin() as s:
            if supersede_origin:
                source_type, source_ref = supersede_origin
                old_ids = s.scalars(
                    select(ClaimRow.id)
                    .join(ClaimEvidenceRow, ClaimEvidenceRow.claim_id == ClaimRow.id)
                    .join(RawInputRow, RawInputRow.id == ClaimEvidenceRow.raw_input_id)
                    .where(
                        ClaimRow.brand_id == brand_id,
                        ClaimRow.status == "accepted",
                        RawInputRow.source_type == source_type,
                        RawInputRow.source_ref == source_ref,
                        RawInputRow.id != raw_id,
                    )
                    .distinct()
                ).all()
                if old_ids:
                    s.execute(
                        update(ClaimRow)
                        .where(ClaimRow.id.in_(old_ids))
                        .values(status="superseded", updated_at=_now())
                    )
                    superseded = [str(i) for i in old_ids]

            out: list[Claim] = []
            for c in claims:
                now = _now()
                row = ClaimRow(
                    id=uuid.uuid4(), brand_id=brand_id, text=c.text, section=c.section,
                    kind=c.kind, status=c.status, authority=c.authority,
                    confidence=c.confidence, embedding=c.embedding,
                    embed_model=self.embed_model if c.embedding is not None else None,
                    created_at=now, updated_at=now,
                )
                ev = ClaimEvidenceRow(claim_id=row.id, raw_input_id=raw_id, excerpt=c.excerpt)
                s.add(row)
                s.flush()
                s.add(ev)
                out.append(claim_from_row(row, [ev]))

            s.execute(
                update(RawInputRow).where(RawInputRow.id == raw_id).values(processed_at=_now())
            )
        return out, superseded

    def claims(self, brand_id: str, *, statuses: Sequence[str] = ("accepted",),
               sections: Sequence[str] | None = None) -> list[Claim]:
        with self.sf() as s:
            self._require_brand(s, brand_id)
            q = select(ClaimRow).where(
                ClaimRow.brand_id == brand_id, ClaimRow.status.in_(list(statuses))
            )
            if sections:
                q = q.where(ClaimRow.section.in_(list(sections)))
            rows = s.scalars(q.order_by(ClaimRow.created_at, ClaimRow.id)).all()
            ev = self._evidence(s, [r.id for r in rows])
            return [claim_from_row(r, ev.get(r.id, [])) for r in rows]

    def search(self, brand_id: str, query_vec: list[float], *, statuses: Sequence[str],
               sections: Sequence[str] | None, k: int) -> list[Claim]:
        with self.sf() as s:
            self._require_brand(s, brand_id)
            dist = ClaimRow.embedding.cosine_distance(query_vec)
            q = select(ClaimRow, dist.label("dist")).where(
                ClaimRow.brand_id == brand_id,
                ClaimRow.status.in_(list(statuses)),
                ClaimRow.embedding.is_not(None),
            )
            if sections:
                q = q.where(ClaimRow.section.in_(list(sections)))
            rows = s.execute(q.order_by(dist).limit(k)).all()
            ev = self._evidence(s, [r.ClaimRow.id for r in rows])
            out = []
            for r in rows:
                c = claim_from_row(r.ClaimRow, ev.get(r.ClaimRow.id, []))
                c.score = 1.0 - float(r.dist)
                out.append(c)
            return out

    @staticmethod
    def _evidence(s: Session, claim_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
        if not claim_ids:
            return {}
        rows = s.scalars(
            select(ClaimEvidenceRow).where(ClaimEvidenceRow.claim_id.in_(claim_ids))
        ).all()
        out: dict[uuid.UUID, list] = {}
        for e in rows:
            out.setdefault(e.claim_id, []).append(e)
        return out

    # ---------- proposals ----------

    def add_proposal(self, brand_id: str, *, text: str, section: str, kind: str, rationale: str,
                     origin: str, origin_ref: str | None) -> Proposal:
        with self.sf.begin() as s:
            self._require_brand(s, brand_id)
            row = ProposalRow(
                id=uuid.uuid4(), brand_id=brand_id, text=text, section=section, kind=kind,
                rationale=rationale, origin=origin, origin_ref=origin_ref, status="pending",
                created_at=_now(),
            )
            s.add(row)
            s.flush()
            return proposal_from_row(row)

    def proposals(self, brand_id: str, status: str | None) -> list[Proposal]:
        with self.sf() as s:
            self._require_brand(s, brand_id)
            q = select(ProposalRow).where(ProposalRow.brand_id == brand_id)
            if status:
                q = q.where(ProposalRow.status == status)
            return [proposal_from_row(r) for r in s.scalars(q.order_by(ProposalRow.created_at))]

    def get_pending_proposal(self, brand_id: str, proposal_id: str) -> Proposal:
        with self.sf() as s:
            row = s.get(ProposalRow, _uuid(proposal_id))
            if row is None or row.brand_id != brand_id:
                raise ProposalNotFound(proposal_id)
            if row.status != "pending":
                raise ProposalAlreadyDecided(f"{proposal_id} is {row.status}")
            return proposal_from_row(row)

    def decide_proposal(self, brand_id: str, proposal_id: str, *, status: str, by: str,
                        note: str | None, raw_input: dict, claim: NewClaim) -> Claim:
        """Atomically: lock proposal (must be pending), store raw input + claim + evidence,
        mark proposal decided. Used by both accept (claim = the proposal text) and reject
        (claim = a decision recording why)."""
        with self.sf.begin() as s:
            row = s.execute(
                select(ProposalRow).where(ProposalRow.id == _uuid(proposal_id)).with_for_update()
            ).scalar_one_or_none()
            if row is None or row.brand_id != brand_id:
                raise ProposalNotFound(proposal_id)
            if row.status != "pending":
                raise ProposalAlreadyDecided(f"{proposal_id} is {row.status}")

            raw = RawInputRow(id=uuid.uuid4(), brand_id=brand_id, created_at=_now(),
                              processed_at=_now(), **raw_input)
            s.add(raw)
            now = _now()
            crow = ClaimRow(
                id=uuid.uuid4(), brand_id=brand_id, text=claim.text, section=claim.section,
                kind=claim.kind, status=claim.status, authority=claim.authority,
                confidence=claim.confidence, embedding=claim.embedding,
                embed_model=self.embed_model if claim.embedding is not None else None,
                created_at=now, updated_at=now,
            )
            s.add(crow)
            s.flush()
            ev = ClaimEvidenceRow(claim_id=crow.id, raw_input_id=raw.id, excerpt=claim.excerpt)
            s.add(ev)

            row.status = status
            row.decided_by = by
            row.decision_note = note
            row.decided_at = now
            if status == "accepted":
                row.resulting_claim_id = crow.id
            return claim_from_row(crow, [ev])
