"""Add role column to space_members (two-axis RBAC Phase 1).

Before: membership was all-or-nothing — every member of a Space had the
same powers, while their platform-wide `users.role` decided what they
could do across every Space. Now: per-space role (admin / navigator /
explorer), matching the pattern in Jira / Miro / Atlassian / GitHub.

Backfill:
  - The `space.created_by` user becomes that Space's `admin`.
  - Every other existing member becomes `navigator`.
  - New members default to `navigator` unless the inviter overrides.

See docs/rbac-two-axis-design.md for the full design.

Revision ID: space_member_role_20260421
Revises: 54e29443ecbd
Create Date: 2026-04-21 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "space_member_role_20260421"
down_revision = "54e29443ecbd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "space_members",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="navigator",
        ),
    )

    # Backfill: space creators become commander of their own space.
    # (Earlier drafts used 'admin' here; see rename migration 20260421b
    # for the vocabulary fix. Keeping 'commander' on fresh installs so
    # they don't need the rename at all.)
    op.execute(
        """
        UPDATE space_members sm
        SET role = 'commander'
        FROM spaces s
        WHERE sm.space_id = s.id
          AND sm.user_id = s.created_by
        """
    )


def downgrade() -> None:
    op.drop_column("space_members", "role")
