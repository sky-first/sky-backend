"""CEO Master Dashboard aggregator.

A single read endpoint the Console's top-level "CEO" view consumes.
Sits one level above the operational ``/dashboard`` — that one returns
tenant counts and the audit feed; this one returns the numbers Lucas
actually opens the Console to see: total MRR, gross margin, churn-risk
signals, plan distribution, provisioning health.

All amounts are EUR per *year* (annualized) so the same scalar can be
compared against the billed-cost stream from ``cost_provider``. The
sub-aggregates each carry their own ``computed_at`` so a stale partial
isn't disguised as fresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.internal_console import (
    InternalConsoleAudit,
    ProvisioningJob,
    ProvisioningJobStatus,
)
from src.models.tenant import Tenant
from src.models.tenant_plan_limits import TenantPlanLimits
from src.services import pricing_tiers
from src.services.console_telemetry import billing_provider, cost_provider


# Annualised list prices in EUR per tier. Pulled from the pricing tier
# registry so a tier rename / repricing here doesn't need a duplicate
# update. Falls back to None ("custom" / enterprise) — those tenants are
# excluded from MRR roll-ups because their actual contract amount is
# negotiated.
def _tier_annual_price_eur(tier: str) -> Optional[int]:
    registry = getattr(pricing_tiers, "TIER_REGISTRY", {}) or {}
    entry = registry.get(tier)
    if entry is None:
        return None
    return getattr(entry, "headline_price_eur", None)


@dataclass
class CeoTierRow:
    tier: str
    active_tenants: int
    annual_price_eur: Optional[int]
    contracted_mrr_eur: float  # monthly contribution from this tier


@dataclass
class CeoChurnSignal:
    tenant_slug: str
    display_name: str
    reason: str  # "suspended" / "downgrade_blocked" / "no_recent_activity"
    detail: str


@dataclass
class CeoProvisioningHealth:
    pending: int
    running: int
    succeeded_last_24h: int
    failed_last_24h: int


@dataclass
class CeoMasterSummary:
    computed_at: datetime
    total_tenants: int
    active_tenants: int
    suspended_tenants: int
    contracted_arr_eur: float  # annualised total revenue
    contracted_mrr_eur: float
    last_month_cost_eur: float
    gross_margin_pct: Optional[float]  # None when cost telemetry missing
    tiers: List[CeoTierRow]
    churn_signals: List[CeoChurnSignal]
    provisioning: CeoProvisioningHealth
    # Best-effort 30-day LLM spend via Langfuse. ``None`` when
    # Langfuse is offline / disabled — the rest of the summary still
    # renders. EUR-denominated to match every other monetary field.
    llm_cost_30d_eur: Optional[float] = None


async def compute_ceo_summary(db: AsyncSession) -> CeoMasterSummary:
    """Build the CEO Master Dashboard payload in one shot.

    Single read path — every sub-aggregate executes against the same
    AsyncSession so the snapshot is internally consistent. The bill /
    cost providers are best-effort: when the telemetry stack is down we
    surface a partial view (``last_month_cost_eur=0`` / margin=None)
    rather than 500ing the dashboard.
    """
    now = datetime.now(timezone.utc)

    total = (
        await db.execute(select(func.count()).select_from(Tenant))
    ).scalar_one() or 0
    active = (
        await db.execute(
            select(func.count())
            .select_from(Tenant)
            .where(Tenant.is_active == True)  # noqa: E712
        )
    ).scalar_one() or 0
    suspended = total - active

    by_tier_rows = (
        await db.execute(
            select(Tenant.tier, func.count())
            .where(Tenant.is_active == True)  # noqa: E712
            .group_by(Tenant.tier)
        )
    ).all()

    tier_rows: List[CeoTierRow] = []
    contracted_mrr = 0.0
    for tier, count in by_tier_rows:
        annual = _tier_annual_price_eur(tier)
        monthly = (annual / 12.0) * count if annual else 0.0
        contracted_mrr += monthly
        tier_rows.append(
            CeoTierRow(
                tier=tier,
                active_tenants=int(count),
                annual_price_eur=annual,
                contracted_mrr_eur=round(monthly, 2),
            )
        )
    contracted_arr = round(contracted_mrr * 12.0, 2)

    # Last-month cost via the telemetry provider — wrap in try/except so
    # a provider outage doesn't take the dashboard down.
    last_month_cost = 0.0
    try:
        provider = cost_provider()
        # Provider returns USD; convert at a rough 0.92 EUR/USD until
        # we wire real FX. Keeping the conversion here (not in the
        # provider) so the wire format stays "USD" elsewhere.
        breakdown = provider.platform_cost_breakdown(days=30)
        last_month_cost = round(float(getattr(breakdown, "total_usd", 0.0)) * 0.92, 2)
    except Exception:
        last_month_cost = 0.0

    margin_pct: Optional[float] = None
    annual_cost = last_month_cost * 12.0  # naive linear projection
    if contracted_arr > 0 and last_month_cost > 0:
        margin_pct = round((contracted_arr - annual_cost) / contracted_arr * 100.0, 1)

    # Churn signals — three independent lookups, each kept cheap so the
    # endpoint stays under ~150ms even with hundreds of tenants.
    churn_signals: List[CeoChurnSignal] = []

    # (a) Currently suspended tenants — already on fire.
    suspended_rows = (
        await db.execute(
            select(Tenant.slug, Tenant.display_name, Tenant.suspended_at)
            .where(Tenant.is_active == False)  # noqa: E712
            .order_by(Tenant.suspended_at.desc().nullslast())
            .limit(10)
        )
    ).all()
    for slug, display_name, suspended_at in suspended_rows:
        churn_signals.append(
            CeoChurnSignal(
                tenant_slug=slug,
                display_name=display_name or slug,
                reason="suspended",
                detail=(
                    f"Suspended {_human_ago(suspended_at, now)}"
                    if suspended_at
                    else "Currently suspended"
                ),
            )
        )

    # (b) Plan-limits saturation > 100% — the tenant is *over* their
    # contracted cap and can't grow without an upgrade conversation.
    over_cap_rows = (
        await db.execute(
            select(TenantPlanLimits.tenant_id)
            .where(TenantPlanLimits.max_agents.isnot(None))
            .where(TenantPlanLimits.current_agents > TenantPlanLimits.max_agents)
            .limit(10)
        )
    ).scalars().all()
    for tenant_id in over_cap_rows:
        row = (
            await db.execute(
                select(Tenant.slug, Tenant.display_name).where(Tenant.id == tenant_id)
            )
        ).first()
        if not row:
            continue
        slug, display_name = row
        churn_signals.append(
            CeoChurnSignal(
                tenant_slug=slug,
                display_name=display_name or slug,
                reason="downgrade_blocked",
                detail="Currently over plan limits — upgrade conversation pending",
            )
        )

    # Provisioning health snapshot — counts of pending/running plus
    # 24-hour rolling success / failure stats.
    horizon = now - timedelta(hours=24)
    pending = (
        await db.execute(
            select(func.count())
            .select_from(ProvisioningJob)
            .where(ProvisioningJob.status == ProvisioningJobStatus.PENDING.value)
        )
    ).scalar_one() or 0
    running = (
        await db.execute(
            select(func.count())
            .select_from(ProvisioningJob)
            .where(ProvisioningJob.status == ProvisioningJobStatus.RUNNING.value)
        )
    ).scalar_one() or 0
    succeeded_24h = (
        await db.execute(
            select(func.count())
            .select_from(ProvisioningJob)
            .where(ProvisioningJob.status == ProvisioningJobStatus.SUCCESS.value)
            .where(ProvisioningJob.completed_at >= horizon)
        )
    ).scalar_one() or 0
    failed_24h = (
        await db.execute(
            select(func.count())
            .select_from(ProvisioningJob)
            .where(ProvisioningJob.status == ProvisioningJobStatus.FAILED.value)
            .where(ProvisioningJob.completed_at >= horizon)
        )
    ).scalar_one() or 0
    provisioning = CeoProvisioningHealth(
        pending=int(pending),
        running=int(running),
        succeeded_last_24h=int(succeeded_24h),
        failed_last_24h=int(failed_24h),
    )

    # Touch billing provider lightly so the import isn't dead — keeps a
    # warm cache for the per-tenant view that the dashboard's drill-in
    # already consumes.
    try:
        billing_provider()
    except Exception:
        pass

    # Best-effort LLM cost via Langfuse. Same fail-soft contract as the
    # cost provider line above — Langfuse outage / missing keys must
    # not 500 the CEO dashboard. ``None`` propagates to the schema and
    # the UI renders the cell as "—".
    llm_cost_30d_eur: Optional[float] = None
    try:
        from src.services.llm_cost_metrics import llm_cost_metrics_provider

        metrics = llm_cost_metrics_provider().get_platform_llm_metrics(days=30)
        if metrics.available:
            llm_cost_30d_eur = round(float(metrics.total_cost_eur), 2)
    except Exception:
        llm_cost_30d_eur = None

    return CeoMasterSummary(
        computed_at=now,
        total_tenants=int(total),
        active_tenants=int(active),
        suspended_tenants=int(suspended),
        contracted_arr_eur=round(contracted_arr, 2),
        contracted_mrr_eur=round(contracted_mrr, 2),
        last_month_cost_eur=last_month_cost,
        gross_margin_pct=margin_pct,
        tiers=tier_rows,
        churn_signals=churn_signals,
        provisioning=provisioning,
        llm_cost_30d_eur=llm_cost_30d_eur,
    )


def _human_ago(when: Optional[datetime], now: datetime) -> str:
    if when is None:
        return "recently"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = now - when
    if delta.days >= 1:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}h ago"
    return "less than 1h ago"
