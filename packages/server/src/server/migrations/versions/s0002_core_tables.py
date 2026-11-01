"""app core tables: users, api_tokens, brands, attempts

Revision ID: s0002
Revises: s0001
Create Date: 2026-11-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "s0002"
down_revision = "s0001"
branch_labels = None
depends_on = None

S = "app"


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        _ts("created_at"),
        schema=S,
    )
    op.create_table(
        "api_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(255), nullable=False),
        _ts("created_at"),
        _ts("last_used_at", nullable=True),
        _ts("revoked_at", nullable=True),
        schema=S,
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"], schema=S)
    op.create_table(
        "brands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        _ts("created_at"),
        schema=S,
    )
    op.create_index("ix_brands_owner_id", "brands", ["owner_id"], schema=S)
    op.create_table(
        "attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.brands.id"), nullable=False),
        sa.Column("challenge_id", sa.String(64), nullable=False),
        sa.Column("challenge_version", sa.Integer, nullable=False),
        sa.Column("answer_text", sa.Text, nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column("feedback", JSONB, nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("ingest_result", JSONB, nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False),
        _ts("created_at"),
        schema=S,
    )
    op.create_index("ix_attempts_brand_current", "attempts",
                    ["brand_id", "is_current", "challenge_id"], schema=S)


def downgrade() -> None:
    for t in ("attempts", "brands", "api_tokens", "users"):
        op.drop_table(t, schema=S)
