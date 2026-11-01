"""SQLAlchemy models for the `app` schema.

users, api_tokens, brands, attempts, score_snapshots, runs, run_events.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "app"


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(255), default="cli")
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[uuid.UUID] = _pk()  # str(id) is the brain's brand_id
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[uuid.UUID] = _pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id"))
    challenge_id: Mapped[str] = mapped_column(String(64))
    challenge_version: Mapped[int] = mapped_column(Integer)
    answer_text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    score: Mapped[float | None] = mapped_column(Float)
    ingest_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_attempts_brand_current", "brand_id", "is_current", "challenge_id"),)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    id: Mapped[uuid.UUID] = _pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id"), index=True)
    scorer_version: Mapped[str] = mapped_column(String(64))
    total: Mapped[float] = mapped_column(Float)
    by_section: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    eligible: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


ACTIVE_RUN_STATUSES = ("requested", "approved", "queued", "running", "paused")
TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = _pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id"), index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="requested")
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    spent: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    current_phase: Mapped[str | None] = mapped_column(String(64))
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    report_md: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(320))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_runs_status_created", "status", "created_at"),)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    phase: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = _created()
