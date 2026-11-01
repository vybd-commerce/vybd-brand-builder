"""score_snapshots, runs, run_events

Revision ID: s0003
Revises: s0002
Create Date: 2026-11-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "s0003"
down_revision = "s0002"
branch_labels = None
depends_on = None

S = "app"


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "score_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.brands.id"), nullable=False),
        sa.Column("scorer_version", sa.String(64), nullable=False),
        sa.Column("total", sa.Float, nullable=False),
        sa.Column("by_section", JSONB, nullable=False),
        sa.Column("eligible", sa.Boolean, nullable=False),
        sa.Column("details", JSONB, nullable=False),
        _ts("created_at"),
        schema=S,
    )
    op.create_index("ix_score_snapshots_brand_id", "score_snapshots", ["brand_id"], schema=S)
    op.create_table(
        "runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.brands.id"), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey(f"{S}.users.id"),
                  nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("budget", JSONB, nullable=False),
        sa.Column("spent", JSONB, nullable=False),
        sa.Column("current_phase", sa.String(64)),
        sa.Column("checkpoint", JSONB, nullable=False),
        sa.Column("report_md", sa.Text),
        sa.Column("error", sa.Text),
        _ts("created_at"),
        _ts("approved_at", nullable=True),
        sa.Column("approved_by", sa.String(320)),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        _ts("lease_expires_at", nullable=True),
        schema=S,
    )
    op.create_index("ix_runs_brand_id", "runs", ["brand_id"], schema=S)
    op.create_index("ix_runs_status_created", "runs", ["status", "created_at"], schema=S)
    op.create_table(
        "run_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey(f"{S}.runs.id"), nullable=False),
        sa.Column("phase", sa.String(64)),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        _ts("created_at"),
        schema=S,
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"], schema=S)


def downgrade() -> None:
    for t in ("run_events", "runs", "score_snapshots"):
        op.drop_table(t, schema=S)
