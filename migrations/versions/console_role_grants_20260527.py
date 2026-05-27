"""Console role grants — real RBAC (Projeto B It4).

One row per (email, role) tuple. Roles are the 9 defined in
docs/projeto-b-roles-and-use-cases.md. ``CONSOLE_ADMIN_EMAILS`` env
var still works as bootstrap (the first user grants themselves admin
that way) but every subsequent grant goes through the DB.

Revision ID: console_role_grants_20260527
Revises: console_csm_notes_20260527
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "console_role_grants_20260527"
down_revision = "console_csm_notes_20260527"
branch_labels = None
depends_on = None

ALLOWED_ROLES = (
    "ceo",
    "cto",
    "tech_lead",
    "devops",
    "backend_eng",
    "ai_eng",
    "csm",
    "sales",
    "finance",
    "support",
    "dpo",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("console_role_grants"):
        return
    op.create_table(
        "console_role_grants",
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("granted_by", sa.String(length=255), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint(
            "user_email", "role", name="console_role_grants_pk"
        ),
        sa.CheckConstraint(
            f"role IN {ALLOWED_ROLES}",
            name="console_role_grants_role_check",
        ),
    )
    op.create_index(
        "idx_console_role_grants_user",
        "console_role_grants",
        ["user_email"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_console_role_grants_user", table_name="console_role_grants"
    )
    op.drop_table("console_role_grants")
