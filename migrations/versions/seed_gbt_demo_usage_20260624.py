"""seed realistic demo usage counters for gbtsolutions in tenant_plan_limits

gbtsolutions is the staging demo tenant on the foundation tier (max_agents=10,
max_queries_per_month=10000). After the seed_tenant_plan_limits_20260623
migration, its counters are all zero because it has no real usage in the
single-tenant sentinel row. Zero counters produce health_score=0 in the Console,
making the tenant list look broken during demos.

This migration upserts realistic counters (7 agents, 5000 queries) so the
Console renders a meaningful health score (~58/100) for gbtsolutions.

Revision ID: seed_gbt_demo_usage_20260624
Revises: seed_tenant_plan_limits_20260623
Create Date: 2026-06-24
"""

import sqlalchemy as sa
from alembic import op

revision = "seed_gbt_demo_usage_20260624"
down_revision = "seed_tenant_plan_limits_20260623"
branch_labels = None
depends_on = None

_GBT_SLUG = "gbtsolutions"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_plan_limits" not in inspector.get_table_names():
        return
    if "tenant_registry" not in inspector.get_table_names():
        return

    result = bind.execute(
        sa.text("SELECT id FROM tenant_registry WHERE slug = :slug"),
        {"slug": _GBT_SLUG},
    ).one_or_none()
    if result is None:
        return  # tenant doesn't exist in this environment

    tenant_id = str(result[0])
    bind.execute(
        sa.text(
            """
            UPDATE tenant_plan_limits
               SET current_agents = 7,
                   current_users  = 4,
                   current_queries_this_month = 5000,
                   updated_at = NOW()
             WHERE tenant_id = :tid
               AND current_agents = 0
               AND current_queries_this_month = 0
            """
        ),
        {"tid": tenant_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_plan_limits" not in inspector.get_table_names():
        return
    if "tenant_registry" not in inspector.get_table_names():
        return

    result = bind.execute(
        sa.text("SELECT id FROM tenant_registry WHERE slug = :slug"),
        {"slug": _GBT_SLUG},
    ).one_or_none()
    if result is None:
        return

    tenant_id = str(result[0])
    bind.execute(
        sa.text(
            """
            UPDATE tenant_plan_limits
               SET current_agents = 0,
                   current_users  = 0,
                   current_queries_this_month = 0,
                   updated_at = NOW()
             WHERE tenant_id = :tid
            """
        ),
        {"tid": tenant_id},
    )
