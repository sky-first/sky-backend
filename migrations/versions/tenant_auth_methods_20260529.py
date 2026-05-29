"""Per-tenant auth methods (GBT pilot — email/password gating).

Adds the ``auth_methods`` JSONB column to ``tenant_registry`` so the
``/login`` page can render different authentication options per tenant.

Shape: ``{"password": bool, "google": bool, "azure": bool, "okta": bool}``.

Default reflects the production status quo: Google only. Existing rows
are backfilled with the same default so behaviour does not change on
deploy.

Revision ID: tenant_auth_methods_20260529
Revises: console_support_20260527
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "tenant_auth_methods_20260529"
down_revision = "console_support_20260527"
branch_labels = None
depends_on = None


_DEFAULT_METHODS = (
    "'{\"password\": false, \"google\": true, "
    "\"azure\": false, \"okta\": false}'"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tenant_registry"):
        return

    cols = {c["name"] for c in inspector.get_columns("tenant_registry")}
    if "auth_methods" in cols:
        return

    op.add_column(
        "tenant_registry",
        sa.Column(
            "auth_methods",
            JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text(_DEFAULT_METHODS),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tenant_registry"):
        return
    cols = {c["name"] for c in inspector.get_columns("tenant_registry")}
    if "auth_methods" not in cols:
        return
    op.drop_column("tenant_registry", "auth_methods")
