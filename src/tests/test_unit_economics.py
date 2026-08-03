"""Tests for the tenant unit-economics maths.

Targets ``compute_unit_economics`` directly — it is deliberately pure, so
none of this needs a DB, AWS, or Langfuse. Covers the edge cases listed
in docs/tenant-unit-economics.md §7.
"""

from __future__ import annotations

import pytest

from src.services.unit_economics import (
    TenantInput,
    compute_unit_economics,
)


def _t(slug, *, mrr=1000.0, llm=0.0, activity=0.0, tier="pro"):
    return TenantInput(
        slug=slug,
        display_name=slug.upper(),
        tier=tier,
        mrr_usd=mrr,
        llm_usd=llm,
        activity=activity,
    )


# ── shared pool ────────────────────────────────────────────────────


def test_bedrock_is_excluded_from_shared_pool():
    """LLM is attributed per tenant from Langfuse; leaving Bedrock in the
    shared pool would bill the same tokens twice."""
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=200.0,
        tenants=[_t("a"), _t("b")],
    )
    assert r.shared_total_usd == 800.0
    assert r.tenants[0].shared_equal_usd == 400.0


def test_negative_shared_pool_is_clamped():
    """Credits/refunds can push a bucket negative; a negative shared pool
    would hand every tenant a fictitious profit."""
    r = compute_unit_economics(
        platform_total_usd=100.0,
        bedrock_usd=250.0,
        tenants=[_t("a")],
    )
    assert r.shared_total_usd == 0.0
    assert r.tenants[0].shared_equal_usd == 0.0


# ── allocation ─────────────────────────────────────────────────────


def test_equal_split_divides_shared_by_n():
    r = compute_unit_economics(
        platform_total_usd=900.0,
        bedrock_usd=0.0,
        tenants=[_t("a"), _t("b"), _t("c")],
    )
    assert [t.shared_equal_usd for t in r.tenants] == [300.0, 300.0, 300.0]


def test_single_tenant_carries_the_whole_shared_pool():
    r = compute_unit_economics(
        platform_total_usd=500.0, bedrock_usd=0.0, tenants=[_t("solo")]
    )
    assert r.tenants[0].shared_equal_usd == 500.0
    assert r.tenants[0].shared_weighted_usd == 500.0


def test_weighted_split_follows_activity():
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("heavy", activity=75.0), _t("light", activity=25.0)],
    )
    heavy, light = r.tenants
    assert heavy.shared_weighted_usd == 750.0
    assert light.shared_weighted_usd == 250.0
    assert heavy.activity_share_pct == 75.0
    assert r.weighted_fell_back_to_equal is False


def test_zero_activity_falls_back_to_equal_and_says_so():
    """Two identical columns presented as independent would mislead —
    the flag lets the UI label it."""
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("a"), _t("b")],
    )
    assert r.weighted_fell_back_to_equal is True
    for t in r.tenants:
        assert t.shared_weighted_usd == t.shared_equal_usd == 500.0


def test_negative_activity_is_treated_as_zero():
    r = compute_unit_economics(
        platform_total_usd=100.0,
        bedrock_usd=0.0,
        tenants=[_t("a", activity=-5.0), _t("b", activity=10.0)],
    )
    a, b = r.tenants
    assert a.shared_weighted_usd == 0.0
    assert b.shared_weighted_usd == 100.0


# ── cost + margin ──────────────────────────────────────────────────


def test_cost_is_shared_plus_llm_and_margin_is_mrr_minus_cost():
    r = compute_unit_economics(
        platform_total_usd=200.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=500.0, llm=30.0), _t("b", mrr=500.0, llm=70.0)],
    )
    a, b = r.tenants
    assert a.cost_equal_usd == 130.0  # 100 shared + 30 llm
    assert a.margin_equal_usd == 370.0
    assert b.cost_equal_usd == 170.0
    assert b.margin_equal_usd == 330.0


def test_margin_pct_is_zero_when_tenant_has_no_mrr():
    """A free tenant has no meaningful margin *percentage*; the absolute
    margin is still reported (and negative)."""
    r = compute_unit_economics(
        platform_total_usd=100.0,
        bedrock_usd=0.0,
        tenants=[_t("free", mrr=0.0, llm=5.0)],
    )
    t = r.tenants[0]
    assert t.margin_equal_pct == 0.0
    assert t.margin_equal_usd == -105.0


def test_blended_margin_uses_totals():
    r = compute_unit_economics(
        platform_total_usd=400.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=1000.0), _t("b", mrr=1000.0)],
    )
    # revenue 2000, cost 400 → 80%
    assert r.blended_margin_equal_pct == 80.0


# ── scale view ─────────────────────────────────────────────────────


def test_marginal_tenant_costs_only_its_own_llm():
    """The SaaS argument: tenant N+1 adds no shared infra."""
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=600.0, llm=40.0), _t("b", mrr=400.0, llm=60.0)],
    )
    assert r.marginal_cost_next_usd == 50.0   # avg llm
    assert r.marginal_margin_next_usd == 450.0  # avg mrr 500 - 50


def test_break_even_n_is_the_smallest_profitable_n():
    # shared 1000, avg mrr 300, avg llm 100 → 1000/200 = 5
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=300.0, llm=100.0)],
    )
    assert r.break_even_n == 5

    at_break_even = next(c for c in r.curve if c.n == 5)
    assert at_break_even.blended_margin_pct >= 0
    just_below = next(c for c in r.curve if c.n == 4)
    assert just_below.blended_margin_pct < 0


def test_break_even_rounds_up():
    # shared 1000, margin per tenant 300 → 3.33 → 4
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=400.0, llm=100.0)],
    )
    assert r.break_even_n == 4


def test_no_break_even_when_llm_exceeds_mrr():
    """If an average tenant burns more on tokens than it pays, scale
    never rescues it — must not report a finite break-even."""
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=50.0, llm=80.0)],
    )
    assert r.break_even_n is None


def test_break_even_is_one_when_there_is_no_shared_cost():
    r = compute_unit_economics(
        platform_total_usd=0.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=100.0, llm=10.0)],
    )
    assert r.break_even_n == 1


def test_margin_curve_rises_with_n():
    """The whole point of the chart: shared cost amortises."""
    r = compute_unit_economics(
        platform_total_usd=1000.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=500.0, llm=50.0)],
        curve_max_n=10,
    )
    pcts = [c.blended_margin_pct for c in r.curve]
    assert len(pcts) == 10
    assert pcts == sorted(pcts), "margin must improve monotonically with N"
    assert pcts[0] < pcts[-1]


# ── degenerate input ───────────────────────────────────────────────


def test_no_tenants_reports_overhead_without_dividing_by_zero():
    r = compute_unit_economics(
        platform_total_usd=750.0, bedrock_usd=50.0, tenants=[]
    )
    assert r.n_active == 0
    assert r.shared_total_usd == 700.0
    assert r.break_even_n is None
    assert r.tenants == []
    assert r.blended_margin_equal_pct == 0.0


def test_all_tenants_without_mrr_does_not_blow_up():
    r = compute_unit_economics(
        platform_total_usd=100.0,
        bedrock_usd=0.0,
        tenants=[_t("a", mrr=0.0), _t("b", mrr=0.0)],
    )
    assert r.blended_margin_equal_pct == 0.0
    assert r.break_even_n is None
    assert all(c.blended_margin_pct == 0.0 for c in r.curve)


@pytest.mark.parametrize("days", [1, 7, 30, 90])
def test_window_is_echoed_back(days):
    r = compute_unit_economics(
        platform_total_usd=10.0, bedrock_usd=0.0, tenants=[_t("a")], window_days=days
    )
    assert r.window_days == days
