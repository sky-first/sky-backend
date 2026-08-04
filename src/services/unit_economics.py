"""Tenant unit economics — per-tenant fully-loaded cost, margin, and the
platform "margin vs N tenants" curve.

See ``docs/tenant-unit-economics.md`` for the model and its rationale.

Two layers, deliberately separated:

* :func:`compute_unit_economics` — pure arithmetic over plain inputs. No
  DB, no AWS, no Langfuse, so the maths is unit-tested directly.
* :func:`build_unit_economics` — composition: reads the tenant registry,
  the persisted LLM snapshots, billing, and platform cost, then delegates
  to the pure function.

Why there is no ``Dedicated(tenant)`` term
------------------------------------------
The original design assumed each tenant owned a dedicated RDS instance
and Redis, billable via a ``tenant`` cost-allocation tag. The onboarding
workflow does not work that way: ``onboard-client.yml`` provisions
"Option A — shared Postgres, schema-per-tenant", and every tenant is
served by the *shared* platform backend pod (the tenant is resolved from
the Host header). Redis is shared too.

So the only AWS resource that is genuinely per-tenant and taggable is the
Secrets Manager entry — roughly 0.40 USD/month. Activating the cost
allocation tag would buy a rounding error, so the dedicated term is
dropped entirely and everything shared is allocated instead. If Option B
(per-tenant RDS) ever ships, reintroduce it here.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)

# How far the "margin vs N tenants" sweep runs when the caller doesn't
# say. Enough to show the curve flattening without a huge payload.
DEFAULT_CURVE_MAX_N = 25


# ── Inputs ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantInput:
    """One tenant's raw figures for the window."""

    slug: str
    display_name: str
    tier: str
    mrr_usd: float
    llm_usd: float
    # Weight for the "weighted" allocation. Any non-negative measure of
    # real consumption; :func:`build_unit_economics` uses LLM request
    # count because it is per-tenant and already aligned to the same
    # window as the cost figures.
    activity: float = 0.0
    llm_available: bool = True


# ── Outputs ────────────────────────────────────────────────────────


@dataclass
class TenantEconomics:
    slug: str
    display_name: str
    tier: str
    mrr_usd: float
    llm_usd: float
    activity_share_pct: float
    shared_equal_usd: float
    shared_weighted_usd: float
    cost_equal_usd: float
    cost_weighted_usd: float
    margin_equal_usd: float
    margin_weighted_usd: float
    margin_equal_pct: float
    margin_weighted_pct: float
    llm_available: bool = True


@dataclass
class MarginCurvePoint:
    n: int
    blended_margin_pct: float


@dataclass
class UnitEconomics:
    window_days: int
    n_active: int
    platform_total_usd: float
    bedrock_usd: float
    llm_total_usd: float
    shared_total_usd: float
    mrr_total_usd: float
    blended_margin_equal_pct: float
    blended_margin_weighted_pct: float
    break_even_n: Optional[int]
    marginal_cost_next_usd: float
    marginal_margin_next_usd: float
    tenants: List[TenantEconomics] = field(default_factory=list)
    curve: List[MarginCurvePoint] = field(default_factory=list)
    # Set when the weighted split had nothing to weight by and silently
    # degraded to the equal split — the UI should say so rather than
    # present two identical columns as if they were independent.
    weighted_fell_back_to_equal: bool = False


# ── Pure computation ───────────────────────────────────────────────


def _pct(numerator: float, denominator: float) -> float:
    """Percentage, guarding division by zero.

    A tenant with no MRR has no meaningful margin *percentage* (the
    absolute margin is still reported and is simply negative), so 0.0 is
    returned rather than an infinity that would wreck the chart axis.
    """
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


def _blended_margin_pct_at(
    n: int, *, shared_total: float, avg_mrr: float, avg_llm: float
) -> float:
    """Blended margin if the platform had ``n`` tenants of average shape.

    Holds SharedTotal fixed (the whole point: shared infra does not grow
    per tenant) and scales MRR and LLM linearly.
    """
    if n <= 0 or avg_mrr <= 0:
        return 0.0
    revenue = n * avg_mrr
    cost = shared_total + n * avg_llm
    return round((revenue - cost) / revenue * 100, 2)


def compute_unit_economics(
    *,
    platform_total_usd: float,
    bedrock_usd: float,
    tenants: Sequence[TenantInput],
    window_days: int = 30,
    curve_max_n: int = DEFAULT_CURVE_MAX_N,
) -> UnitEconomics:
    """Per-tenant cost/margin plus the platform scale view.

    ``bedrock_usd`` is subtracted from the shared pool: LLM spend is
    taken from Langfuse per tenant, so leaving Bedrock in the shared
    total would charge the same tokens twice.
    """
    n = len(tenants)

    # Bedrock out of the shared pool (double-count guard). Clamp at 0 —
    # credits and refunds can push a bucket negative, and a negative
    # shared pool would hand every tenant a fictitious profit.
    shared_total = platform_total_usd - bedrock_usd
    if shared_total < 0:
        logger.warning(
            "unit_economics: shared pool negative (total=%.2f bedrock=%.2f) — "
            "clamped to 0",
            platform_total_usd,
            bedrock_usd,
        )
        shared_total = 0.0

    mrr_total = round(sum(t.mrr_usd for t in tenants), 2)
    llm_total = round(sum(t.llm_usd for t in tenants), 2)

    if n == 0:
        # No tenants: the shared infra is pure overhead. Report it
        # honestly instead of dividing by zero.
        return UnitEconomics(
            window_days=window_days,
            n_active=0,
            platform_total_usd=round(platform_total_usd, 2),
            bedrock_usd=round(bedrock_usd, 2),
            llm_total_usd=0.0,
            shared_total_usd=round(shared_total, 2),
            mrr_total_usd=0.0,
            blended_margin_equal_pct=0.0,
            blended_margin_weighted_pct=0.0,
            break_even_n=None,
            marginal_cost_next_usd=0.0,
            marginal_margin_next_usd=0.0,
        )

    equal_share = shared_total / n

    total_activity = sum(max(0.0, t.activity) for t in tenants)
    fell_back = total_activity <= 0

    rows: List[TenantEconomics] = []
    for t in tenants:
        share = (1.0 / n) if fell_back else (max(0.0, t.activity) / total_activity)
        weighted_share = shared_total * share

        cost_equal = equal_share + t.llm_usd
        cost_weighted = weighted_share + t.llm_usd
        margin_equal = t.mrr_usd - cost_equal
        margin_weighted = t.mrr_usd - cost_weighted

        rows.append(
            TenantEconomics(
                slug=t.slug,
                display_name=t.display_name,
                tier=t.tier,
                mrr_usd=round(t.mrr_usd, 2),
                llm_usd=round(t.llm_usd, 2),
                activity_share_pct=round(share * 100, 2),
                shared_equal_usd=round(equal_share, 2),
                shared_weighted_usd=round(weighted_share, 2),
                cost_equal_usd=round(cost_equal, 2),
                cost_weighted_usd=round(cost_weighted, 2),
                margin_equal_usd=round(margin_equal, 2),
                margin_weighted_usd=round(margin_weighted, 2),
                margin_equal_pct=_pct(margin_equal, t.mrr_usd),
                margin_weighted_pct=_pct(margin_weighted, t.mrr_usd),
                llm_available=t.llm_available,
            )
        )

    cost_equal_total = sum(r.cost_equal_usd for r in rows)
    cost_weighted_total = sum(r.cost_weighted_usd for r in rows)

    avg_mrr = mrr_total / n
    avg_llm = llm_total / n

    # Marginal tenant N+1: no new shared infra, so its cost is just its
    # own LLM spend. That is the whole SaaS argument, quantified.
    marginal_cost_next = avg_llm
    marginal_margin_next = avg_mrr - avg_llm

    # Break-even N: smallest N where blended margin >= 0.
    #   N*avg_mrr >= shared_total + N*avg_llm
    #   N >= shared_total / (avg_mrr - avg_llm)
    # If an average tenant's LLM spend already exceeds its MRR, scale
    # never rescues it — no amount of tenants closes the gap.
    if marginal_margin_next <= 0:
        break_even_n: Optional[int] = None
    elif shared_total <= 0:
        break_even_n = 1
    else:
        break_even_n = max(1, math.ceil(shared_total / marginal_margin_next))

    curve = [
        MarginCurvePoint(
            n=k,
            blended_margin_pct=_blended_margin_pct_at(
                k, shared_total=shared_total, avg_mrr=avg_mrr, avg_llm=avg_llm
            ),
        )
        for k in range(1, max(1, curve_max_n) + 1)
    ]

    return UnitEconomics(
        window_days=window_days,
        n_active=n,
        platform_total_usd=round(platform_total_usd, 2),
        bedrock_usd=round(bedrock_usd, 2),
        llm_total_usd=llm_total,
        shared_total_usd=round(shared_total, 2),
        mrr_total_usd=mrr_total,
        blended_margin_equal_pct=_pct(mrr_total - cost_equal_total, mrr_total),
        blended_margin_weighted_pct=_pct(mrr_total - cost_weighted_total, mrr_total),
        break_even_n=break_even_n,
        marginal_cost_next_usd=round(marginal_cost_next, 2),
        marginal_margin_next_usd=round(marginal_margin_next, 2),
        tenants=rows,
        curve=curve,
        weighted_fell_back_to_equal=fell_back,
    )


# ── Composition ────────────────────────────────────────────────────


async def _llm_by_tenant(db: Any, tenant_ids: Sequence[Any], days: int) -> dict:
    """Sum the persisted daily LLM snapshots per tenant over the window.

    Preferred over calling Langfuse live: the snapshots are already
    written daily by ``snapshot_tenant_llm_costs``, they survive Langfuse
    being down, and they are aligned to whole days like the AWS figures.

    Returns ``{tenant_id: (cost_usd, requests)}``; tenants with no rows
    are simply absent.
    """
    from sqlalchemy import func, select

    from src.models.tenant_llm_daily_snapshot import TenantLlmDailySnapshot

    if not tenant_ids:
        return {}

    since = date.today() - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                TenantLlmDailySnapshot.tenant_id,
                func.coalesce(func.sum(TenantLlmDailySnapshot.total_cost_usd), 0.0),
                func.coalesce(func.sum(TenantLlmDailySnapshot.total_requests), 0),
            )
            .where(
                TenantLlmDailySnapshot.tenant_id.in_(list(tenant_ids)),
                TenantLlmDailySnapshot.snapshot_date >= since,
            )
            .group_by(TenantLlmDailySnapshot.tenant_id)
        )
    ).all()

    return {tid: (float(cost or 0.0), int(reqs or 0)) for tid, cost, reqs in rows}


def _platform_cost(provider: Any, days: int):
    """Platform cost for the window.

    The CostProvider protocol only guarantees ``platform_cost()`` (30d);
    the real AWS provider also exposes a windowed variant. Prefer the
    windowed call so a caller asking for 7 days doesn't silently get 30.
    """
    windowed = getattr(provider, "platform_cost_breakdown", None)
    if callable(windowed):
        return windowed(days=days)
    return provider.platform_cost()


async def build_unit_economics(db: Any, *, days: int = 30) -> UnitEconomics:
    """Assemble :func:`compute_unit_economics` inputs from live sources."""
    from sqlalchemy import select

    from src.config.settings import settings
    from src.models.tenant import Tenant
    from src.services.console_telemetry import billing_provider, cost_provider

    tenants = (
        (await db.execute(select(Tenant).where(Tenant.is_active.is_(True))))
        .scalars()
        .all()
    )

    cost = _platform_cost(cost_provider(), days)
    llm_map = await _llm_by_tenant(db, [t.id for t in tenants], days)

    billing = billing_provider()
    eur_usd = float(getattr(settings, "EUR_USD_RATE", 1.08) or 1.08)

    inputs: List[TenantInput] = []
    for t in tenants:
        llm_usd, requests = llm_map.get(t.id, (0.0, 0))

        # MRR is billed in EUR (Moloni); costs are USD (AWS). Convert so
        # the margin subtraction is apples-to-apples.
        try:
            mrr_eur = billing.tenant_billing(t.slug, t.tier).mrr_contribution_eur
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "unit_economics: billing lookup failed for %s: %s", t.slug, exc
            )
            mrr_eur = 0.0

        inputs.append(
            TenantInput(
                slug=t.slug,
                display_name=t.display_name,
                tier=t.tier,
                mrr_usd=float(mrr_eur or 0.0) * eur_usd,
                llm_usd=llm_usd,
                activity=float(requests),
                llm_available=t.id in llm_map,
            )
        )

    return compute_unit_economics(
        platform_total_usd=float(cost.total_usd),
        bedrock_usd=float(cost.bedrock_usd),
        tenants=inputs,
        window_days=days,
    )


__all__ = [
    "DEFAULT_CURVE_MAX_N",
    "MarginCurvePoint",
    "TenantEconomics",
    "TenantInput",
    "UnitEconomics",
    "build_unit_economics",
    "compute_unit_economics",
]
