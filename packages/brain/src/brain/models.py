"""SQLAlchemy models for the `brain` schema. Only `store.py` touches these directly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, MetaData, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from brain.providers import embed_dim

SCHEMA = "brain"


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class BrandSpaceRow(Base):
    __tablename__ = "brand_spaces"
    brand_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RawInputRow(Base):
    __tablename__ = "raw_inputs"
    id: Mapped[uuid.UUID] = _id()
    brand_id: Mapped[str] = mapped_column(ForeignKey("brand_spaces.brand_id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str | None] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(255))
    section_hint: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_raw_inputs_origin", "brand_id", "source_type", "source_ref"),)


class ClaimRow(Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = _id()
    brand_id: Mapped[str] = mapped_column(ForeignKey("brand_spaces.brand_id"))
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    authority: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id"))
    embedding = mapped_column(Vector(embed_dim()), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (Index("ix_claims_brand_status_section", "brand_id", "status", "section"),)


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"), primary_key=True)
    raw_input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_inputs.id"), primary_key=True, index=True
    )
    excerpt: Mapped[str] = mapped_column(Text)


class ProposalRow(Base):
    __tablename__ = "proposals"
    id: Mapped[uuid.UUID] = _id()
    brand_id: Mapped[str] = mapped_column(ForeignKey("brand_spaces.brand_id"))
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(32))
    origin_ref: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decision_note: Mapped[str | None] = mapped_column(Text)
    resulting_claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_proposals_brand_status", "brand_id", "status"),)
