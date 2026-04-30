"""Drop promotion_requests / promotion_request_items / knowledge_conflicts.

The promotion flow (Personal → Crew → Space → Org) has been removed.
Resources now live exclusively inside Spaces / Crews and Personal is a
read-only aggregate. Dropping the three tables that backed the feature
plus the indexes that promotion_tables_20260426.py created.

Revision ID: drop_promotion_tables_20260430
Revises: merge_all_heads_20260428
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "drop_promotion_tables_20260430"
down_revision = "merge_all_heads_20260428"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Drop child first (FK to promotion_requests).
    if "knowledge_conflicts" in existing:
        op.drop_table("knowledge_conflicts")
    if "promotion_request_items" in existing:
        op.drop_table("promotion_request_items")
    if "promotion_requests" in existing:
        op.drop_table("promotion_requests")


def downgrade() -> None:
    # Re-create the tables exactly as promotion_tables_20260426.py did,
    # so a downgrade past this revision lands the schema back in the
    # previous shape. The feature is gone in app code, but the schema
    # round-trip should still work for ops who roll back.
    op.create_table(
        "promotion_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requester_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_scope", sa.String(length=20), nullable=False),
        sa.Column("target_scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="pending"
        ),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_promotion_requests_status", "promotion_requests", ["status"]
    )
    op.create_index(
        "ix_promotion_requests_target",
        "promotion_requests",
        ["target_scope", "target_scope_id"],
    )
    op.create_index(
        "ix_promotion_requests_requester_user_id",
        "promotion_requests",
        ["requester_user_id"],
    )

    op.create_table(
        "promotion_request_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotion_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role", sa.String(length=20), nullable=False, server_default="dependency"
        ),
        sa.Column("label", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_promotion_request_items_request_id",
        "promotion_request_items",
        ["request_id"],
    )

    op.create_table(
        "knowledge_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotion_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proposed_kind",
            sa.String(length=30),
            nullable=False,
            server_default="metric",
        ),
        sa.Column("proposed_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "canonical_kind",
            sa.String(length=30),
            nullable=False,
            server_default="metric",
        ),
        sa.Column("canonical_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("similarity", sa.Numeric(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_knowledge_conflicts_request_id",
        "knowledge_conflicts",
        ["request_id"],
    )
