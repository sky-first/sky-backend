"""resource_acl: allow 'crew' as principal_type

Phase 2.5 of the RBAC rewrite. Lucas's review surfaced that Crews
are a first-class citizen below Space (Space=department, Crew=team
inside the department). The resolver now walks crew_id and a Crew
membership can grant access to a resource — so the `resource_acl`
table must accept `principal_type='crew'` for explicit grants
targeting an entire Crew.

Idempotent: drops + recreates the principal_type CHECK constraint.

Revision ID: resource_acl_crew_principal_20260501
Revises: resource_acl_20260501
"""

from alembic import op
import sqlalchemy as sa


revision = "resource_acl_crew_principal_20260501"
down_revision = "resource_acl_20260501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old CHECK and replace with one that accepts 'crew'.
    op.execute(
        "ALTER TABLE resource_acl "
        "DROP CONSTRAINT IF EXISTS ck_resource_acl_principal_type"
    )
    op.create_check_constraint(
        "ck_resource_acl_principal_type",
        "resource_acl",
        "principal_type IN ('user','space','crew','tenant')",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE resource_acl "
        "DROP CONSTRAINT IF EXISTS ck_resource_acl_principal_type"
    )
    op.create_check_constraint(
        "ck_resource_acl_principal_type",
        "resource_acl",
        "principal_type IN ('user','space','tenant')",
    )
