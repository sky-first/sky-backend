"""Add logo_url to tenant_registry — operator-controlled customer logo.

Lucas's 2026-06-03 brief: the customer's logo + company name on the
/login page should come from the platform Console, not from the
tenant's own platform_branding table. Operators upload it once when
provisioning the tenant (or edit later on the tenant detail page);
``/api/v1/branding/public`` then serves it back without auth.

Stored as a data URL (base64) directly on the registry row so the
read path stays a single point lookup. Future migration to S3 +
signed URLs is straightforward — swap the column comment + the
operator UI upload path.

Revision ID: tenant_logo_url_20260603
Revises: rename_role_20260603
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "tenant_logo_url_20260603"
down_revision = "rename_role_20260603"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_registry",
        sa.Column("logo_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_registry", "logo_url")
