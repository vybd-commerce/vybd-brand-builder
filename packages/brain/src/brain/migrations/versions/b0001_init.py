"""brain schema init: pgvector extension (tables arrive in Milestone 2)

Revision ID: b0001
Revises:
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op

revision = "b0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Extension is shared DB-wide; leave it in place.
    pass
