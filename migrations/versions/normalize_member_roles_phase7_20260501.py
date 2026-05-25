"""Phase 7 — normalize SpaceMember/CrewMember.role to owner/editor/viewer

Backfills two generations of legacy role enums onto the Phase-7 canonical
vocabulary (owner / editor / viewer):

  Pre-A1 (original two-axis design)
    admin   → owner
    member  → viewer
    guest   → viewer

  A1-era triple (commander / navigator / explorer)
    commander → owner
    navigator → editor
    explorer  → viewer

Idempotent: the CASE expression is a no-op on rows that already use the
new vocabulary. Safe to rerun.

Revision ID: normalize_member_roles_phase7_20260501
Revises: connection_tier_agent_auditable_20260501
"""

from alembic import op
import sqlalchemy as sa


revision = "normalize_member_roles_phase7_20260501"
down_revision = "connection_tier_agent_auditable_20260501"
branch_labels = None
depends_on = None


_CASE = """
CASE role
    WHEN 'admin'     THEN 'owner'
    WHEN 'member'    THEN 'viewer'
    WHEN 'guest'     THEN 'viewer'
    WHEN 'commander' THEN 'owner'
    WHEN 'navigator' THEN 'editor'
    WHEN 'explorer'  THEN 'viewer'
    ELSE role
END
"""


def upgrade() -> None:
    op.execute(f"UPDATE space_members SET role = {_CASE}")
    op.execute(f"UPDATE crew_members  SET role = {_CASE}")


def downgrade() -> None:
    # Lossy by design — multiple legacy values collapsed onto each
    # canonical, so we can't reverse without an audit log we don't keep.
    # Migration is left as a no-op on downgrade.
    pass
