"""Console CSM notes — per-tenant relationship state (Projeto B It3 B#17).

One row per tenant. Carries the CSM's perspective on the customer:
free-form markdown notes, lightweight tags (at_risk, expansion, …),
last-contact timestamp, optional NPS score, and the next renewal
date for the renewal calendar.

Foreign-key-less by design — the registry slug is the join key and
the row stays around if the tenant is soft-destroyed so CSM history
isn't lost.

Revision ID: console_csm_notes_20260527
Revises: internal_console_20260527
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "console_csm_notes_20260527"
down_revision = "internal_console_20260527"
branch_labels = None
depends_on = None


_TAGS = ARRAY(sa.String(length=64)).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("console_tenant_csm_notes"):
        return

    op.create_table(
        "console_tenant_csm_notes",
        sa.Column(
            "tenant_slug",
            sa.String(length=50),
            primary_key=True,
        ),
        sa.Column("notes_markdown", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            _TAGS,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "last_contact_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("nps_score", sa.Integer(), nullable=True),
        sa.Column(
            "next_renewal_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "nps_score IS NULL OR (nps_score >= -100 AND nps_score <= 100)",
            name="console_csm_notes_nps_range",
        ),
    )
    op.create_index(
        "idx_console_csm_renewal",
        "console_tenant_csm_notes",
        ["next_renewal_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_console_csm_renewal",
        table_name="console_tenant_csm_notes",
    )
    op.drop_table("console_tenant_csm_notes")
