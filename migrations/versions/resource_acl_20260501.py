"""resource_acl table — per-resource sharing for the new RBAC model

Phase 2 of the RBAC rewrite. Introduces explicit per-resource grants:

  • resource_type   — connection | dashboard | agent | knowledge_file | space
  • resource_id     — UUID of the resource
  • principal_type  — user | space | tenant
  • principal_id    — UUID of the principal (user.id, space.id, or NULL for tenant)
  • level           — viewer | editor | owner
  • granted_by      — user.id of who created the grant
  • granted_at      — timestamp

Resolution rule (used by Authorization.can in Phase 2+ code):

  effective_level(user, resource) = max(
      space_member_level(user, resource.space),
      explicit_user_grant(user, resource),
      explicit_space_grant(any space the user is in, resource),
      tenant_default_grant(resource),
  )

Idempotent. Safe to re-run.

Revision ID: resource_acl_20260501
Revises: drop_promotion_tables_20260430
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import inspect


revision = "resource_acl_20260501"
down_revision = "drop_promotion_tables_20260430"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    return name in inspect(bind).get_table_names()


def _index_exists(bind, table: str, name: str) -> bool:
    if not _table_exists(bind, table):
        return False
    return any(ix["name"] == name for ix in inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "resource_acl"):
        op.create_table(
            "resource_acl",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("resource_type", sa.String(32), nullable=False),
            sa.Column("resource_id", UUID(as_uuid=True), nullable=False),
            sa.Column("principal_type", sa.String(16), nullable=False),
            # principal_id is nullable: a tenant-wide grant has NULL principal_id.
            sa.Column("principal_id", UUID(as_uuid=True), nullable=True),
            sa.Column("level", sa.String(16), nullable=False),
            sa.Column(
                "granted_by",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "granted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "resource_type IN ('connection','dashboard','agent','knowledge_file','space','widget','page')",
                name="ck_resource_acl_resource_type",
            ),
            sa.CheckConstraint(
                "principal_type IN ('user','space','tenant')",
                name="ck_resource_acl_principal_type",
            ),
            sa.CheckConstraint(
                "level IN ('viewer','editor','owner')",
                name="ck_resource_acl_level",
            ),
            sa.CheckConstraint(
                "(principal_type = 'tenant' AND principal_id IS NULL) "
                "OR (principal_type IN ('user','space') AND principal_id IS NOT NULL)",
                name="ck_resource_acl_principal_consistency",
            ),
        )

    # Lookup index: every authorisation check filters by (resource_type, resource_id).
    if not _index_exists(bind, "resource_acl", "ix_resource_acl_resource"):
        op.create_index(
            "ix_resource_acl_resource",
            "resource_acl",
            ["resource_type", "resource_id"],
        )

    # Reverse lookup: "which resources can this user see?" filters by principal.
    if not _index_exists(bind, "resource_acl", "ix_resource_acl_principal"):
        op.create_index(
            "ix_resource_acl_principal",
            "resource_acl",
            ["principal_type", "principal_id"],
        )

    # Uniqueness: (resource, principal) is unique — only one grant per pair.
    # Tenant-wide grants (principal_id IS NULL) are unique on (resource, type)
    # via a partial index because UNIQUE NULL semantics differ.
    if not _index_exists(bind, "resource_acl", "uq_resource_acl_grant"):
        op.create_index(
            "uq_resource_acl_grant",
            "resource_acl",
            ["resource_type", "resource_id", "principal_type", "principal_id"],
            unique=True,
            postgresql_where=sa.text("principal_id IS NOT NULL"),
        )
    if not _index_exists(bind, "resource_acl", "uq_resource_acl_tenant_grant"):
        op.create_index(
            "uq_resource_acl_tenant_grant",
            "resource_acl",
            ["resource_type", "resource_id"],
            unique=True,
            postgresql_where=sa.text(
                "principal_type = 'tenant' AND principal_id IS NULL"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    for ix in (
        "uq_resource_acl_tenant_grant",
        "uq_resource_acl_grant",
        "ix_resource_acl_principal",
        "ix_resource_acl_resource",
    ):
        if _index_exists(bind, "resource_acl", ix):
            op.drop_index(ix, table_name="resource_acl")
    if _table_exists(bind, "resource_acl"):
        op.drop_table("resource_acl")
