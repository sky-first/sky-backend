"""Rename space_members.role 'admin' → 'commander' (two-axis RBAC vocabulary fix).

Phase 1 shipped with `admin` as the top space role, but `admin` is
already the top platform role — customers read "admin of Finance"
and "admin of the tenant" as the same thing, which is confusing.

Space vocabulary stays commander / navigator / explorer (aligns with
the old permission matrix and the crew-role vocabulary). Platform
stays owner / admin. No sharing of role names across the two axes.

Revision ID: space_member_role_rename_20260421b
Revises: space_member_role_20260421
Create Date: 2026-04-21 00:00:00.000000
"""

from alembic import op

revision = "space_member_role_rename_20260421b"
down_revision = "space_member_role_20260421"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE space_members SET role = 'commander' WHERE role = 'admin'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE space_members SET role = 'admin' WHERE role = 'commander'"
    )
