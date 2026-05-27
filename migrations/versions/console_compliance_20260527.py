"""Console compliance — DPA + data residency per tenant (Projeto B It6).

Tracks the Data Processing Agreement signature state, data residency
choice, and compliance flags for each tenant. The DPO reads / writes
this; everyone else can read.

Revision ID: console_compliance_20260527
Revises: console_role_grants_20260527
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "console_compliance_20260527"
down_revision = "console_role_grants_20260527"
branch_labels = None
depends_on = None


_TAGS = ARRAY(sa.String(length=64)).with_variant(sa.JSON(), "sqlite")
_JSONB_OR_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("console_tenant_compliance"):
        return
    op.create_table(
        "console_tenant_compliance",
        sa.Column(
            "tenant_slug", sa.String(length=50), primary_key=True
        ),
        sa.Column(
            "dpa_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("dpa_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dpa_signed_by", sa.String(length=255), nullable=True),
        sa.Column("dpa_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "data_residency",
            sa.String(length=32),
            nullable=False,
            server_default="eu-west-1",
        ),
        sa.Column(
            "compliance_flags",
            _JSONB_OR_JSON,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("subprocessors_approved", _TAGS, nullable=False, server_default=sa.text("'{}'")),
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
            "dpa_status IN ('pending', 'signed', 'expired', 'na')",
            name="console_compliance_dpa_status_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("console_tenant_compliance")
