"""Device registry for push notifications (BE-06).

Push is 100% greenfield: a ``push`` channel enum existed but nothing
ever sent one. Before a dispatcher can fan a notification out to a
phone, the backend has to know which phones a user owns. This table is
that registry — one row per (user, push_token), upserted on register.

Isolation is by database (one DB per tenant), so ``tenant_id`` is stored
for auditing but the DB boundary — not this column — is what keeps a
device in tenant A from ever receiving tenant B's pushes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "device_registry_20260805"
down_revision = "tenant_domains_20260804"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)

    op.create_table(
        "devices",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", uuid_type, nullable=True),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("push_token", sa.String(512), nullable=False),
        sa.Column("provider", sa.String(10), nullable=False, server_default="expo"),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "push_token", name="uq_device_user_token"),
        sa.CheckConstraint("platform IN ('ios','android')", name="ck_device_platform"),
    )
    op.create_index("idx_devices_user_id", "devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_devices_user_id", table_name="devices")
    op.drop_table("devices")
