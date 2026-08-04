"""Rename tenant_registry tier ``pilot`` → ``starter``.

GBT pre-deploy cleanup (2026-05-30). The Console UI previously
displayed the cheapest tier as "Pilot"; the rename aligns the
``tenant_registry.tier`` enum with the ``starter`` label used
everywhere else (marketing site, tenant_plan_limits.plan_tier,
upgrade prompts). Two-step operation:

1. Drop the existing CHECK constraint so the UPDATE doesn't trip
   the old enum.
2. ``UPDATE tenant_registry SET tier = 'starter' WHERE tier = 'pilot'``.
3. Re-add the CHECK constraint with the new enum.

The downgrade reverses each step. Existing tenants with non-pilot
tiers (foundation/core/advanced/strategic) are untouched.

Revision ID: rename_pilot_to_starter_20260530
Revises: tenant_plan_limits_20260530
Create Date: 2026-05-30

Originally pointed at ``sky_role_owner_20260529`` because it was
authored in parallel with the pricing-Fase-1 migration (PR #466).
Both landed with the same parent, producing two alembic heads and
freezing the migrate Job on staging with
``Multiple head revisions are present for given argument 'head'``.
Chain to ``tenant_plan_limits_20260530`` so there's a single head.
The UPDATE this migration runs is unaffected by the order.
"""

from __future__ import annotations

from alembic import op

revision = "rename_pilot_to_starter_20260530"
down_revision = "tenant_plan_limits_20260530"
branch_labels = None
depends_on = None


# Keep literal in the migration so it remains self-contained even if
# ``src.models.tenant.TenantTier`` is refactored later.
OLD_ALLOWED_TIERS = ("pilot", "foundation", "core", "advanced", "strategic")
NEW_ALLOWED_TIERS = ("starter", "foundation", "core", "advanced", "strategic")
CHECK_NAME = "tenant_registry_tier_check"
TABLE = "tenant_registry"


def _drop_check(name: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite has no DROP CONSTRAINT — the column-level check is
        # baked into the CREATE TABLE. The test suite uses
        # ``Base.metadata.create_all`` and never reaches this migration
        # so the SQLite path is a no-op intentionally.
        return
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {name}")


def _add_check(name: str, allowed: tuple[str, ...]) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    enum_sql = ", ".join(f"'{t}'" for t in allowed)
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {name} CHECK (tier IN ({enum_sql}))"
    )


def upgrade() -> None:
    _drop_check(CHECK_NAME)
    # Bulk rename of existing rows. Idempotent — re-running is harmless
    # because the WHERE filters down to the legacy value.
    op.execute(
        f"UPDATE {TABLE} SET tier = 'starter' WHERE tier = 'pilot'"
    )
    _add_check(CHECK_NAME, NEW_ALLOWED_TIERS)


def downgrade() -> None:
    _drop_check(CHECK_NAME)
    op.execute(
        f"UPDATE {TABLE} SET tier = 'pilot' WHERE tier = 'starter'"
    )
    _add_check(CHECK_NAME, OLD_ALLOWED_TIERS)
