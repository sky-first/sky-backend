"""Refresh-token families for reuse detection (BE-05, Sky Mobile).

Adds ``refresh_tokens.family_id`` — the login lineage a token belongs to.
A fresh login opens a new family; every rotation inherits it. When a revoked
token is replayed (reuse = theft) the whole family is revoked at once.

Additive and backward-compatible: existing rows are backfilled so each is its
own family (``family_id = id``), which is exactly how ``family_id or id`` in
the service treats a NULL anyway — the backfill just makes it explicit.

Revision ID: refresh_token_family_20260730
Revises: message_origin_20260730
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "refresh_token_family_20260730"
down_revision = "message_origin_20260730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Backfill: each pre-existing token is its own family so a legacy token
    # that gets rotated from here on carries a well-defined lineage.
    op.execute("UPDATE refresh_tokens SET family_id = id WHERE family_id IS NULL")
    op.create_index("idx_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade() -> None:
    op.drop_index("idx_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "family_id")
