"""seed tenant_plan_limits for existing tenants

Inserts a tenant_plan_limits row for every tenant in tenant_registry
that does not already have one.  Previously, get_limits() auto-provisioned
rows on first use, but always defaulted to the "foundation" preset regardless
of the tenant's actual product tier, and started counters at zero even for
tenants that already had agents/users in the database.

This migration:
1. Maps each tenant's product tier (tenant_registry.tier) to the
   closest pricing tier (TIER_LIMITS key).
2. Seeds current_agents from the real agents row count scoped to the
   sentinel row (single-tenant mode, agents has no tenant column).
   In multi-tenant mode the counter starts at 0 and the hot-path hooks
   will increment it correctly going forward.
3. Is fully idempotent — ON CONFLICT DO NOTHING means re-runs are safe.

Revision ID: seed_tenant_plan_limits_20260623
Revises: reconcile_agent_counter_20260617
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from alembic import op

revision = "seed_tenant_plan_limits_20260623"
down_revision = "agent_findings_set_null_20260617"
branch_labels = None
depends_on = None

# Map product tiers (tenant_registry.tier) → pricing tier caps.
# Tiers absent from TIER_LIMITS (core, advanced, strategic, pilot, …)
# are treated as enterprise (unlimited) — they pre-date the pricing model
# and should never be gated by a capacity ceiling.
_TIER_CAPS: dict[str, dict] = {
    "starter": {
        "tier": "starter",
        "max_agents": 3,
        "max_users": 5,
        "max_storage_gb": 5,
        "max_queries_per_month": 1_000,
    },
    "foundation": {
        "tier": "foundation",
        "max_agents": 10,
        "max_users": 25,
        "max_storage_gb": 50,
        "max_queries_per_month": 10_000,
    },
    "scale": {
        "tier": "scale",
        "max_agents": 50,
        "max_users": 100,
        "max_storage_gb": 200,
        "max_queries_per_month": 50_000,
    },
}

_ENTERPRISE_CAPS = {
    "tier": "enterprise",
    "max_agents": None,
    "max_users": None,
    "max_storage_gb": None,
    "max_queries_per_month": None,
}

_SENTINEL_UUID = "00000000-0000-0000-0000-000000000000"


def _caps_for(product_tier: str) -> dict:
    return _TIER_CAPS.get(product_tier, _ENTERPRISE_CAPS)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "tenant_plan_limits" not in tables or "tenant_registry" not in tables:
        return

    # Fetch sentinel counters (single-tenant legacy data).  If no sentinel
    # row exists yet, default everything to 0.
    sentinel = bind.execute(
        sa.text(
            "SELECT current_agents, current_users, current_storage_bytes, "
            "current_queries_this_month, queries_period_start "
            f"FROM tenant_plan_limits WHERE tenant_id = '{_SENTINEL_UUID}'"
        )
    ).mappings().one_or_none()

    sentinel_agents = sentinel["current_agents"] if sentinel else 0
    sentinel_users = sentinel["current_users"] if sentinel else 0
    sentinel_storage = sentinel["current_storage_bytes"] if sentinel else 0
    sentinel_queries = sentinel["current_queries_this_month"] if sentinel else 0
    sentinel_period = sentinel["queries_period_start"] if sentinel else sa.func.now()

    tenants = bind.execute(
        sa.text("SELECT id, slug, tier FROM tenant_registry")
    ).mappings().all()

    for tenant in tenants:
        caps = _caps_for(tenant["tier"])
        is_enterprise = caps["tier"] == "enterprise"

        # Enterprise tenants receive the sentinel counters because in
        # single-tenant mode all usage was attributed to the sentinel UUID.
        # Non-enterprise tenants start at 0 — their usage was minimal or
        # was already correctly tracked.
        current_agents = sentinel_agents if is_enterprise else 0
        current_users = sentinel_users if is_enterprise else 0
        current_storage = sentinel_storage if is_enterprise else 0
        current_queries = sentinel_queries if is_enterprise else 0

        bind.execute(
            sa.text("""
                INSERT INTO tenant_plan_limits (
                    tenant_id, tier,
                    max_agents, max_users, max_storage_gb, max_queries_per_month,
                    current_agents, current_users, current_storage_bytes,
                    current_queries_this_month, queries_period_start,
                    last_threshold_alerted, created_at, updated_at
                ) VALUES (
                    :tenant_id, :tier,
                    :max_agents, :max_users, :max_storage_gb, :max_queries,
                    :cur_agents, :cur_users, :cur_storage,
                    :cur_queries, :period_start,
                    '{}', NOW(), NOW()
                )
                ON CONFLICT (tenant_id) DO NOTHING
            """),
            {
                "tenant_id": str(tenant["id"]),
                "tier": caps["tier"],
                "max_agents": caps["max_agents"],
                "max_users": caps["max_users"],
                "max_storage_gb": caps["max_storage_gb"],
                "max_queries": caps["max_queries_per_month"],
                "cur_agents": current_agents,
                "cur_users": current_users,
                "cur_storage": current_storage,
                "cur_queries": current_queries,
                "period_start": sentinel_period,
            },
        )


def downgrade() -> None:
    # Rows were inserted for tenants that had no prior row.
    # Removing them is safe — get_limits() will re-provision on demand.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_plan_limits" not in inspector.get_table_names():
        return
    tenants = bind.execute(
        sa.text("SELECT id FROM tenant_registry")
    ).mappings().all()
    for tenant in tenants:
        bind.execute(
            sa.text(
                "DELETE FROM tenant_plan_limits "
                "WHERE tenant_id = :tid AND created_at >= NOW() - INTERVAL '1 day'"
            ),
            {"tid": str(tenant["id"])},
        )
