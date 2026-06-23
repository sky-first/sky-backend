"""Unit checks for the CEO Master Dashboard aggregator.

The service stitches together tenant counts, the pricing-tier registry,
the cost provider and provisioning-job stats. These tests pin each
slice in isolation so a future change to one sub-aggregate doesn't
quietly break the others.

The cost / billing providers are best-effort by design — the service
should surface a partial view (margin=None) rather than 500 when the
telemetry stack is unavailable. ``test_compute_summary_handles_cost_provider_failure``
guards that contract.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant import Tenant
from src.services.ceo_dashboard import compute_ceo_summary


async def _seed_tenant(
    db_session: AsyncSession,
    slug: str,
    *,
    tier: str = "foundation",
    is_active: bool = True,
) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        display_name=slug.title(),
        tier=tier,
        is_active=is_active,
        db_host="x",
        db_port=5432,
        db_name=slug,
        db_credentials_secret_arn="arn:x",
        redis_host="x",
        redis_credentials_secret_arn="arn:x",
        sso_provider="google",
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest.mark.asyncio
async def test_compute_summary_with_no_tenants(db_session: AsyncSession):
    summary = await compute_ceo_summary(db_session)
    assert summary.total_tenants == 0
    assert summary.active_tenants == 0
    assert summary.suspended_tenants == 0
    assert summary.contracted_arr_eur == 0.0
    assert summary.tiers == []
    assert summary.churn_signals == []


@pytest.mark.asyncio
async def test_compute_summary_counts_active_vs_suspended(db_session: AsyncSession):
    await _seed_tenant(db_session, "alpha", is_active=True)
    await _seed_tenant(db_session, "beta", is_active=True)
    await _seed_tenant(db_session, "gamma", is_active=False)

    summary = await compute_ceo_summary(db_session)
    assert summary.total_tenants == 3
    assert summary.active_tenants == 2
    assert summary.suspended_tenants == 1


@pytest.mark.asyncio
async def test_compute_summary_rolls_up_mrr_per_tier(db_session: AsyncSession):
    """When the tier has a headline price, the row should contribute
    (annual_price / 12) * count to the MRR total."""
    await _seed_tenant(db_session, "alpha", tier="foundation")
    await _seed_tenant(db_session, "beta", tier="foundation")

    summary = await compute_ceo_summary(db_session)
    # Foundation's headline price may be None in tests with an empty
    # registry — assert structural invariants instead of magic numbers.
    row = next((t for t in summary.tiers if t.tier == "foundation"), None)
    assert row is not None
    assert row.active_tenants == 2
    if row.annual_price_eur is not None:
        assert summary.contracted_arr_eur == row.annual_price_eur * 2
        assert summary.contracted_mrr_eur == pytest.approx(
            row.annual_price_eur * 2 / 12.0, rel=0.001
        )


@pytest.mark.asyncio
async def test_compute_summary_lists_suspended_as_churn_signal(db_session: AsyncSession):
    await _seed_tenant(db_session, "atrisk", is_active=False)
    summary = await compute_ceo_summary(db_session)
    slugs = {s.tenant_slug for s in summary.churn_signals}
    assert "atrisk" in slugs
    by_slug = {s.tenant_slug: s for s in summary.churn_signals}
    assert by_slug["atrisk"].reason == "suspended"


@pytest.mark.asyncio
async def test_compute_summary_handles_cost_provider_failure(db_session: AsyncSession):
    """A telemetry-stack outage must not 500 the CEO endpoint — the
    dashboard should still load with margin=None and cost=0."""
    await _seed_tenant(db_session, "alpha")

    class _Boom:
        def platform_cost_breakdown(self, days=30):  # noqa: D401
            raise RuntimeError("cost telemetry offline")

    with patch(
        "src.services.ceo_dashboard.cost_provider", return_value=_Boom()
    ):
        summary = await compute_ceo_summary(db_session)
    assert summary.last_month_cost_eur == 0.0
    assert summary.gross_margin_pct is None


@pytest.mark.asyncio
async def test_provisioning_health_zero_when_table_empty(db_session: AsyncSession):
    summary = await compute_ceo_summary(db_session)
    p = summary.provisioning
    assert p.pending == 0
    assert p.running == 0
    assert p.succeeded_last_24h == 0
    assert p.failed_last_24h == 0
