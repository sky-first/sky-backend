"""Create promotion_requests / promotion_request_items / knowledge_conflicts.

Knowledge refactor Phase 4. Ships the tables that back Personal→Crew→
Space→Org promotion with dependency resolver + conflict detection.

Revision ID: promotion_tables_20260426
Revises: user_permission_grants_20260426
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "promotion_tables_20260426"
down_revision = "user_permission_grants_20260426"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "promotion_requests" not in existing:
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

    if "promotion_request_items" not in existing:
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

    if "knowledge_conflicts" not in existing:
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
            sa.Column(
                "proposed_entity_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column(
                "canonical_kind",
                sa.String(length=30),
                nullable=False,
                server_default="metric",
            ),
            sa.Column(
                "canonical_entity_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
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


def downgrade() -> None:
    op.drop_table("knowledge_conflicts")
    op.drop_table("promotion_request_items")
    op.drop_table("promotion_requests")
