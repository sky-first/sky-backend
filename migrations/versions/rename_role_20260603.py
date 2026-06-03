"""Rename User.role 'owner' → 'super_admin'.

Resolves the long-standing ambiguity where the platform-level top role
shared the string ``"owner"`` with the Space / Crew / Page-member
top role. Lucas's 2026-06-03 brief: the customer-facing concept maps
to ``super_admin`` (can do anything at the tenant level, including
billing + delete tenant), whereas ``owner`` stays as the crew/space
membership role.

Scope:
* ``users.role`` only — every other ``role`` column that legitimately
  carries ``"owner"`` (space_members, crew_members, page_members,
  resource_acl …) is intentionally left untouched.
* Renames in place: 9 rows at the time of this migration.
* Also unifies the legacy ``"user"`` alias into ``"member"`` so the
  taxonomy on this table reads ``super_admin / admin / member`` only.

Revision ID: rename_role_20260603
Revises: manually_completed_20260603
"""
from __future__ import annotations

from alembic import op


revision = "rename_role_20260603"
down_revision = "manually_completed_20260603"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrate existing rows BEFORE tightening any CHECK constraint
    # (if one exists). The schema does not currently have a CHECK on
    # users.role — defaults are enforced at the ORM layer — so this is
    # just data movement.
    op.execute(
        """
        UPDATE users SET role = 'super_admin' WHERE role = 'owner';
        """
    )
    op.execute(
        """
        UPDATE users SET role = 'member' WHERE role = 'user';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users SET role = 'owner' WHERE role = 'super_admin';
        """
    )
    # ``user`` was the legacy default before the rewrite; restore that
    # so a rollback lands the rows exactly where they started.
    op.execute(
        """
        UPDATE users SET role = 'user' WHERE role = 'member';
        """
    )
