"""brain core tables: brand_spaces, raw_inputs, claims, claim_evidence, proposals

Vector size comes from EMBED_DIM at migration time (default 1024). Changing the
embedding model's dimension later needs a new migration + re-embed (see IDEAS).

Revision ID: b0002
Revises: b0001
Create Date: 2026-11-01
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision = "b0002"
down_revision = "b0001"
branch_labels = None
depends_on = None

S = "brain"


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    dim = int(os.environ.get("EMBED_DIM", "1024"))

    op.create_table(
        "brand_spaces",
        sa.Column("brand_id", sa.String(64), primary_key=True),
        _ts("created_at"),
        schema=S,
    )
    op.create_table(
        "raw_inputs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", sa.String(64), sa.ForeignKey(f"{S}.brand_spaces.brand_id"),
                  nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(255)),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("section_hint", sa.String(64)),
        sa.Column("content", sa.Text, nullable=False),
        _ts("created_at"),
        _ts("processed_at", nullable=True),
        schema=S,
    )
    op.create_index("ix_raw_inputs_brand_id", "raw_inputs", ["brand_id"], schema=S)
    op.create_index("ix_raw_inputs_origin", "raw_inputs",
                    ["brand_id", "source_type", "source_ref"], schema=S)

    op.create_table(
        "claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", sa.String(64), sa.ForeignKey(f"{S}.brand_spaces.brand_id"),
                  nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("authority", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("supersedes_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.claims.id")),
        sa.Column("embedding", Vector(dim)),
        sa.Column("embed_model", sa.String(255)),
        _ts("created_at"),
        _ts("updated_at"),
        schema=S,
    )
    op.create_index("ix_claims_brand_status_section", "claims",
                    ["brand_id", "status", "section"], schema=S)
    op.execute(
        f"CREATE INDEX ix_claims_embedding_hnsw ON {S}.claims "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "claim_evidence",
        sa.Column("claim_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.claims.id"),
                  primary_key=True),
        sa.Column("raw_input_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.raw_inputs.id"),
                  primary_key=True),
        sa.Column("excerpt", sa.Text, nullable=False),
        schema=S,
    )
    op.create_index("ix_claim_evidence_raw_input_id", "claim_evidence", ["raw_input_id"],
                    schema=S)

    op.create_table(
        "proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", sa.String(64), sa.ForeignKey(f"{S}.brand_spaces.brand_id"),
                  nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("origin_ref", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_by", sa.String(255)),
        sa.Column("decision_note", sa.Text),
        sa.Column("resulting_claim_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.claims.id")),
        _ts("created_at"),
        _ts("decided_at", nullable=True),
        schema=S,
    )
    op.create_index("ix_proposals_brand_status", "proposals", ["brand_id", "status"], schema=S)


def downgrade() -> None:
    for t in ("proposals", "claim_evidence", "claims", "raw_inputs", "brand_spaces"):
        op.drop_table(t, schema=S)
