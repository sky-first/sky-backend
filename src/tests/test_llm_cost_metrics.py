"""Tests for the Langfuse-backed LLM cost metrics service.

Five scenarios pin the contract the rest of the platform relies on:

1. ``LLM_METRICS_ENABLED=false`` → service returns
   ``available=False`` without hitting the network. Guarantees the
   feature flag actually gates outbound HTTP — no accidental
   Langfuse calls in CI / staging-without-keys.

2. Happy path: when Langfuse returns valid daily rows, the provider
   sums tokens + cost across days and groups by model.

3. Network / HTTP failure → ``available=False``, same shape, no 500.
   Anchors the "Langfuse outage must not break the Console" contract.

4. TTL cache: a second call within the window returns the cached
   payload without a second HTTP fetch. Anchors the Langfuse
   rate-limit-friendly behaviour.

5. CEO dashboard extension: the ``llm_cost_30d_eur`` field is
   populated when the provider returns ``available=True`` and
   stays ``None`` on failure.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.llm_cost_metrics import (
    LlmCostMetricsProvider,
    LlmMetrics,
    reset_provider,
)


# ─── helpers ──────────────────────────────────────────────────────────


def _sample_daily_payload():
    """Two days of plausible Langfuse output. Cost / tokens are
    contrived so the assertions can use exact equality."""
    return [
        {
            "date": "2026-05-29",
            "countTraces": 10,
            "avgLatency": 1.5,  # seconds
            "cacheHitRate": 0.2,
            "usage": [
                {
                    "model": "qwen2.5-coder:32b",
                    "inputUsage": 5000,
                    "outputUsage": 1000,
                    "countObservations": 8,
                    "totalCost": 0.012,
                },
                {
                    "model": "gpt-4o-mini",
                    "inputUsage": 800,
                    "outputUsage": 200,
                    "countObservations": 2,
                    "totalCost": 0.0008,
                },
            ],
        },
        {
            "date": "2026-05-30",
            "countTraces": 5,
            "avgLatency": 2.0,
            "cacheHitRate": 0.4,
            "usage": [
                {
                    "model": "qwen2.5-coder:32b",
                    "inputUsage": 2000,
                    "outputUsage": 500,
                    "countObservations": 5,
                    "totalCost": 0.005,
                },
            ],
        },
    ]


# ─── 1. Disabled flag short-circuits ──────────────────────────────────


def test_disabled_returns_unavailable_without_http():
    reset_provider()
    provider = LlmCostMetricsProvider(
        host="https://cloud.langfuse.com",
        public_key="pk",
        secret_key="sk",
        enabled=False,
        cache_ttl_seconds=300,
        eur_per_usd=0.92,
    )

    # If the provider tries to hit the network when disabled, the
    # patched httpx.Client below will assert-fail.
    with patch("src.services.llm_cost_metrics.httpx.Client") as client_mock:
        out = provider.get_tenant_llm_metrics("gbt", days=30)
    assert out.available is False
    assert out.unavailable_reason == "langfuse_disabled"
    assert out.total_cost_usd == 0.0
    assert client_mock.call_count == 0


# ─── 2. Happy-path aggregation ────────────────────────────────────────


def test_aggregates_tokens_cost_and_models():
    reset_provider()
    provider = LlmCostMetricsProvider(
        host="https://cloud.langfuse.com",
        public_key="pk",
        secret_key="sk",
        enabled=True,
        cache_ttl_seconds=300,
        eur_per_usd=0.92,
    )
    payload = _sample_daily_payload()

    with patch.object(
        provider, "_fetch_daily_metrics", return_value=payload
    ):
        out = provider.get_tenant_llm_metrics("gbt", days=30)

    # 5_000 + 800 + 2_000 = 7_800 input tokens.
    assert out.total_input_tokens == 7_800
    # 1_000 + 200 + 500 = 1_700 output tokens.
    assert out.total_output_tokens == 1_700
    # 0.012 + 0.0008 + 0.005 = 0.0178 USD.
    assert out.total_cost_usd == pytest.approx(0.0178, rel=0.001)
    # EUR = USD * 0.92, rounded to 4 decimals at the service layer.
    assert out.total_cost_eur == pytest.approx(0.0178 * 0.92, abs=0.001)
    # 10 + 5 = 15 traces.
    assert out.total_requests == 15
    assert out.available is True
    # Two models in the breakdown.
    assert set(out.by_model.keys()) == {"qwen2.5-coder:32b", "gpt-4o-mini"}
    # qwen got 5000+2000 input across both days.
    assert out.by_model["qwen2.5-coder:32b"]["input_tokens"] == 7_000
    # qwen cost = 0.012 + 0.005 = 0.017.
    assert out.by_model["qwen2.5-coder:32b"]["cost_usd"] == pytest.approx(
        0.017, rel=0.001
    )


# ─── 3. Network failure → unavailable, no exception ──────────────────


def test_network_failure_degrades_gracefully():
    reset_provider()
    provider = LlmCostMetricsProvider(
        host="https://cloud.langfuse.com",
        public_key="pk",
        secret_key="sk",
        enabled=True,
        cache_ttl_seconds=300,
        eur_per_usd=0.92,
    )

    def _boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("simulated langfuse outage")

    with patch.object(provider, "_fetch_daily_metrics", side_effect=_boom):
        out = provider.get_tenant_llm_metrics("gbt", days=30)
    assert out.available is False
    assert out.unavailable_reason == "langfuse_unreachable"
    # Zeros, not None — schema contract.
    assert out.total_cost_usd == 0.0
    assert out.total_requests == 0


# ─── 4. TTL cache avoids second HTTP fetch ────────────────────────────


def test_ttl_cache_avoids_second_fetch():
    reset_provider()
    provider = LlmCostMetricsProvider(
        host="https://cloud.langfuse.com",
        public_key="pk",
        secret_key="sk",
        enabled=True,
        cache_ttl_seconds=300,
        eur_per_usd=0.92,
    )
    payload = _sample_daily_payload()
    call_count = {"n": 0}

    def _fetch(**kwargs):  # noqa: ANN003
        call_count["n"] += 1
        return payload

    with patch.object(provider, "_fetch_daily_metrics", side_effect=_fetch):
        first = provider.get_tenant_llm_metrics("gbt", days=30)
        second = provider.get_tenant_llm_metrics("gbt", days=30)

    assert call_count["n"] == 1  # second call served from cache
    assert first.total_cost_usd == second.total_cost_usd
    assert first.total_requests == second.total_requests


# ─── 5. CEO dashboard llm_cost_30d_eur extension ──────────────────────


async def _seed_tenant(db_session, slug, *, is_active=True):
    from src.models.tenant import Tenant

    t = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        display_name=slug.title(),
        tier="foundation",
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
async def test_ceo_summary_includes_llm_cost_when_available(
    db_session: AsyncSession,
):
    from src.services.ceo_dashboard import compute_ceo_summary

    await _seed_tenant(db_session, "gbt")

    now = datetime.now(timezone.utc)
    available_metrics = LlmMetrics(
        tenant_id=None,
        window_days=30,
        from_ts=now,
        to_ts=now,
        total_cost_usd=10.0,
        total_cost_eur=9.2,
        available=True,
    )

    class _Stub:
        def get_platform_llm_metrics(self, days=30):
            return available_metrics

    with patch(
        "src.services.llm_cost_metrics.llm_cost_metrics_provider",
        return_value=_Stub(),
    ):
        summary = await compute_ceo_summary(db_session)

    assert summary.llm_cost_30d_eur == pytest.approx(9.2, rel=0.01)


@pytest.mark.asyncio
async def test_ceo_summary_llm_cost_is_none_on_provider_failure(
    db_session: AsyncSession,
):
    from src.services.ceo_dashboard import compute_ceo_summary

    await _seed_tenant(db_session, "alpha")

    class _Boom:
        def get_platform_llm_metrics(self, days=30):
            raise RuntimeError("langfuse offline")

    with patch(
        "src.services.llm_cost_metrics.llm_cost_metrics_provider",
        return_value=_Boom(),
    ):
        summary = await compute_ceo_summary(db_session)

    # The CEO endpoint must still return — None propagates.
    assert summary.llm_cost_30d_eur is None
