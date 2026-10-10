"""Per-tenant pricing plan limits + live usage counters (Pricing Fase 1).

Backs the GBT-pre-deploy pricing model Lucas approved on 2026-05-29.
One row per tenant in ``tenant_registry``. The Tenant.tier field on
``tenant_registry`` is the product-tier (starter/foundation/core/
advanced/strategic) used by the Console pricing-preset UI; this
table holds the *enforced* commercial tier (starter/foundation/scale/
enterprise) along with the live counters the enforcement hooks bump.
The ``starter`` slug intentionally appears in both — the rename of
``pilot`` → ``starter`` on the registry (2026-05-30) brings the two
naming systems closer to alignment.

Why a separate table instead of more JSONB columns on Tenant: the
counters are written from hot paths (every agent create, every AI
query) and have to be atomically incremented without rewriting an
entire JSONB blob. A dedicated row with integer columns lets Postgres
do the atomic ``UPDATE ... SET col = col + 1`` we need.

A NULL ceiling means "unlimited" — used by the Enterprise tier where
the contract caps are negotiated per-customer rather than enforced at
the platform layer.

Single-tenant deployments use ``UUID(int=0)`` (the DEFAULT_TENANT_CONTEXT
sentinel) as the tenant_id, so the table works the same whether
``MULTI_TENANT_ENABLED`` is on or off.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON


# Generic SQLAlchemy ``Uuid`` ships a TypeDecorator that round-trips
# UUID values through CHAR(32) on SQLite — same pattern Tenant uses.
# Lets the test suite ``Base.metadata.create_all`` provision the table
# without hitting the postgres-only dialect path.
_UUID_TYPE = Uuid(as_uuid=True)

from src.config.database import Base


# Same JSONB / SQLite shim used across the codebase.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class PricingTier(str, Enum):
    """Commercial tiers — the source of truth for enforcement.

    Order matches the pricing ladder Lucas approved 2026-05-29.
    Distinct from ``TenantTier`` (legacy product tiers in
    ``src/models/tenant.py``) which the Console still uses for the
    capacity-preset UI. The two will be reconciled in Fase 3.
    """

    STARTER = "starter"
    CORE = "core"
    PLUS = "plus"
    ENTERPRISE = "enterprise"


# Os tectos vêm de `src/services/planos.py` — a ÚNICA tabela (10/10/2026).
# Mantidos com os nomes antigos para quem ainda os importa.
from src.services.planos import PLANOS as _PLANOS  # noqa: E402

TIER_LIMITS: dict[str, dict[str, int | None]] = {
    slug: dict(p.tectos) for slug, p in _PLANOS.items()
}

UPGRADE_HINT: dict[str, str | None] = {slug: p.seguinte for slug, p in _PLANOS.items()}

# Os nomes antigos (foundation, scale, …) continuam a responder, com os
# números do plano para onde apontam.
from src.services.planos import ANTIGOS as _ANTIGOS  # noqa: E402

for _antigo, _novo in _ANTIGOS.items():
    TIER_LIMITS[_antigo] = dict(TIER_LIMITS[_novo])
    UPGRADE_HINT[_antigo] = UPGRADE_HINT[_novo]


class TenantPlanLimits(Base):
    """One row per tenant — enforced commercial tier + live counters."""

    __tablename__ = "tenant_plan_limits"

    tenant_id = Column(
        _UUID_TYPE,
        primary_key=True,
    )

    tier = Column(
        String(32),
        nullable=False,
        server_default="starter",
        default="starter",
    )

    # Ceilings — NULL means "no limit" (Enterprise contract).
    max_agents = Column(Integer, nullable=True)
    max_users = Column(Integer, nullable=True)
    max_storage_gb = Column(Integer, nullable=True)
    max_queries_per_month = Column(Integer, nullable=True)
    #: Fontes de dados ligadas (10/10/2026).
    max_connections = Column(Integer, nullable=True)
    #: O intervalo mínimo entre corridas de um agente: «avisos diários» no
    #: Starter, «imediatos» no Core, «contínuos» no Plus.
    min_agent_interval_minutes = Column(Integer, nullable=True)
    #: A Consola mexeu nos números deste cliente à mão («plano especial»).
    #: Mudar de plano com o preset volta a pô-lo a falso.
    personalizado = Column(Boolean, nullable=False, server_default="false", default=False)

    # Live counters — updated by hot-path hooks and the daily storage job.
    current_agents = Column(Integer, nullable=False, server_default="0", default=0)
    current_users = Column(Integer, nullable=False, server_default="0", default=0)
    current_storage_bytes = Column(BigInteger, nullable=False, server_default="0", default=0)
    current_queries_this_month = Column(Integer, nullable=False, server_default="0", default=0)

    # When the current monthly window opened — pricing_worker rolls
    # this over once a calendar month elapses.
    queries_period_start = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Which thresholds we already alerted on for the current period.
    # Shape: ``{"agents": ["80"], "queries": ["80","95"], ...}``.
    # Reset to {} when the corresponding counter rolls over.
    last_threshold_alerted = Column(
        _JSONB_OR_JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "tier IN ('starter', 'core', 'plus', 'enterprise')",
            name="tenant_plan_limits_tier_check",
        ),
        CheckConstraint("current_agents >= 0", name="tenant_plan_limits_agents_nonneg"),
        CheckConstraint("current_users >= 0", name="tenant_plan_limits_users_nonneg"),
        CheckConstraint(
            "current_storage_bytes >= 0",
            name="tenant_plan_limits_storage_nonneg",
        ),
        CheckConstraint(
            "current_queries_this_month >= 0",
            name="tenant_plan_limits_queries_nonneg",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<TenantPlanLimits tenant={self.tenant_id} "
            f"tier={self.tier!r} agents={self.current_agents}"
            f"/{self.max_agents} users={self.current_users}"
            f"/{self.max_users}>"
        )


__all__ = [
    "PricingTier",
    "TIER_LIMITS",
    "TenantPlanLimits",
    "UPGRADE_HINT",
]
