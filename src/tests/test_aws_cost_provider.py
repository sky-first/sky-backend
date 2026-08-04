"""Unit tests for ``src/services/aws_cost_provider.py``.

These tests inject a fake boto3 Cost Explorer client directly into
``AwsCostProvider`` so they never touch real AWS and never need the
``boto3`` package's network stack to be reachable. ``moto`` is *not*
required — the surface area we exercise (one ``get_cost_and_usage``
call shape) is small enough that a hand-rolled MagicMock is cleaner.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from src.services import aws_cost_provider, console_telemetry
from src.services.aws_cost_provider import (
    AwsCostProvider,
    TENANT_TAG_KEY,
    reset_provider,
)
from src.services.console_telemetry import CostBreakdown, TelemetryUnavailable


# ── helpers ────────────────────────────────────────────────────────


def _ce_response(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a fake ``get_cost_and_usage`` response.

    ``days`` is a list of ``{"start": "YYYY-MM-DD", "groups":
    [(service_name, amount_usd), ...]}`` dicts. One ResultsByTime entry
    is emitted per ``day`` with the supplied groups.
    """
    results = []
    for d in days:
        results.append(
            {
                "TimePeriod": {"Start": d["start"], "End": d.get("end", d["start"])},
                "Total": {},
                "Groups": [
                    {
                        "Keys": [name],
                        "Metrics": {"UnblendedCost": {"Amount": str(amount), "Unit": "USD"}},
                    }
                    for name, amount in d.get("groups", [])
                ],
                "Estimated": False,
            }
        )
    return {"ResultsByTime": results, "GroupDefinitions": [], "DimensionValueAttributes": []}


def _make_provider(ce_client: Any, *, linked_account_id: str | None = None) -> AwsCostProvider:
    """Build an AwsCostProvider with a fully-mocked CE client.

    cache_ttl is intentionally short (1s) for the cache-eviction test
    but long enough that two consecutive calls inside the same test hit
    the cache.
    """
    return AwsCostProvider(
        cache_ttl_seconds=60,
        linked_account_id=linked_account_id,
        region="eu-west-1",
        ce_client=ce_client,
    )


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_provider()
    yield
    reset_provider()


# ── tests ──────────────────────────────────────────────────────────


def test_platform_cost_breakdown_aggregates_buckets():
    """Service rows are projected onto compute/storage/network/bedrock
    buckets and the totals add up to the response sum."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [
            {
                "start": "2026-04-30",
                "end": "2026-05-01",
                "groups": [
                    ("Amazon Elastic Compute Cloud - Compute", 10.0),
                    ("Amazon Elastic Kubernetes Service", 5.0),
                    ("Amazon Simple Storage Service", 3.0),
                    ("Amazon CloudFront", 1.5),
                    ("Amazon Bedrock", 7.25),
                    # Unmapped — must fold into compute, not crash.
                    ("AWS App Runner", 0.75),
                ],
            },
        ]
    )
    provider = _make_provider(ce)

    breakdown = provider.platform_cost_breakdown(days=30)

    assert isinstance(breakdown, CostBreakdown)
    # EC2 + EKS + App Runner (fallback) → compute
    assert breakdown.compute_usd == pytest.approx(10.0 + 5.0 + 0.75)
    # S3 → storage
    assert breakdown.storage_usd == pytest.approx(3.0)
    # CloudFront → network
    assert breakdown.network_usd == pytest.approx(1.5)
    # Bedrock → bedrock
    assert breakdown.bedrock_usd == pytest.approx(7.25)
    # Sum of buckets == total_usd within rounding tolerance.
    assert breakdown.total_usd == pytest.approx(
        breakdown.compute_usd
        + breakdown.storage_usd
        + breakdown.network_usd
        + breakdown.bedrock_usd
    )


def test_service_to_bucket_mapping_handles_storage_and_network_overlap():
    """EFS and AWS Data Transfer are tricky names — the mapper must put
    EFS in storage and Data Transfer in network."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [
            {
                "start": "2026-05-01",
                "groups": [
                    ("Amazon Elastic File System", 4.0),
                    ("Amazon Elastic Block Store", 6.0),
                    ("AWS Data Transfer", 2.5),
                ],
            },
        ]
    )
    provider = _make_provider(ce)

    b = provider.platform_cost_breakdown(days=7)

    assert b.storage_usd == pytest.approx(10.0)  # EFS + EBS
    assert b.network_usd == pytest.approx(2.5)
    assert b.compute_usd == 0.0
    assert b.bedrock_usd == 0.0


def test_daily_granularity_emits_one_point_per_period():
    """The provider passes Granularity=DAILY and projects each
    ResultsByTime entry into a TimeseriesPoint whose value equals that
    day's sum across all services."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [
            {
                "start": "2026-04-29",
                "groups": [("Amazon Bedrock", 2.0), ("AWS Data Transfer", 1.0)],
            },
            {
                "start": "2026-04-30",
                "groups": [("Amazon Bedrock", 3.5)],
            },
            {
                "start": "2026-05-01",
                "groups": [("Amazon Elastic Compute Cloud - Compute", 4.25)],
            },
        ]
    )
    provider = _make_provider(ce)

    breakdown = provider.platform_cost_breakdown(days=3)

    # The call must have asked for DAILY.
    call_kwargs = ce.get_cost_and_usage.call_args.kwargs
    assert call_kwargs["Granularity"] == "DAILY"
    assert call_kwargs["GroupBy"] == [{"Type": "DIMENSION", "Key": "SERVICE"}]

    assert len(breakdown.daily) == 3
    assert breakdown.daily[0].value == pytest.approx(3.0)
    assert breakdown.daily[1].value == pytest.approx(3.5)
    assert breakdown.daily[2].value == pytest.approx(4.25)
    # ISO timestamps are produced from CE's date.
    assert breakdown.daily[0].t.startswith("2026-04-29T00:00:00")


def test_ttl_cache_avoids_repeated_ce_calls():
    """The second call within the TTL must not hit Cost Explorer again;
    a third call after ``invalidate_cache`` must."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [{"start": "2026-05-01", "groups": [("Amazon Bedrock", 1.0)]}]
    )
    provider = _make_provider(ce)

    provider.platform_cost_breakdown(days=30)
    provider.platform_cost_breakdown(days=30)
    assert ce.get_cost_and_usage.call_count == 1

    provider.invalidate_cache()
    provider.platform_cost_breakdown(days=30)
    assert ce.get_cost_and_usage.call_count == 2

    # Different ``days`` value is a different cache key — must not be a hit.
    provider.platform_cost_breakdown(days=7)
    assert ce.get_cost_and_usage.call_count == 3


def test_ce_errors_become_telemetry_unavailable():
    """boto3 errors (permission denied, network, throttling) must surface
    as ``TelemetryUnavailable`` so the Console route returns 503 rather
    than leaking the original boto3 exception."""
    ce = MagicMock()
    ce.get_cost_and_usage.side_effect = RuntimeError(
        "AccessDeniedException: User ... is not authorized to perform: ce:GetCostAndUsage"
    )
    provider = _make_provider(ce)

    with pytest.raises(TelemetryUnavailable) as exc:
        provider.platform_cost_breakdown(days=30)
    assert "Cost Explorer query failed" in str(exc.value)


def test_tenant_cost_breakdown_filters_by_tag():
    """``tenant_cost_breakdown(slug)`` must add a ``Tags`` filter on the
    cost-allocation tag key ``tenant`` with the slug (lower-cased) as
    its only value."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [
            {
                "start": "2026-05-01",
                "groups": [("Amazon Bedrock", 1.25)],
            },
        ]
    )
    provider = _make_provider(ce)

    breakdown = provider.tenant_cost_breakdown("GBT", days=30)

    assert breakdown.bedrock_usd == pytest.approx(1.25)
    call_kwargs = ce.get_cost_and_usage.call_args.kwargs
    # Credit exclusion is always on, so the tenant tag is combined with the
    # RECORD_TYPE "Not" clause via ``And``.
    f = call_kwargs["Filter"]
    assert "And" in f
    assert {"Tags": {"Key": TENANT_TAG_KEY, "Values": ["gbt"]}} in f["And"]
    assert any("Not" in clause for clause in f["And"])


def test_tenant_with_no_tagged_resources_returns_zero_not_error():
    """A tenant whose infra hasn't been tag-onboarded yet should return
    a zero-filled CostBreakdown — NOT a 503 — so the UI can render the
    "tag onboarding pending" state."""
    ce = MagicMock()
    # Cost Explorer responds with an empty Groups array when the filter
    # matches nothing; Total may also be empty.
    ce.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-05-02"},
                "Total": {"UnblendedCost": {"Amount": "0", "Unit": "USD"}},
                "Groups": [],
                "Estimated": False,
            }
        ],
        "GroupDefinitions": [],
        "DimensionValueAttributes": [],
    }
    provider = _make_provider(ce)

    b = provider.tenant_cost_breakdown("untagged-tenant", days=30)

    assert b.total_usd == 0.0
    assert b.compute_usd == 0.0
    assert b.storage_usd == 0.0
    assert b.network_usd == 0.0
    assert b.bedrock_usd == 0.0


def test_linked_account_filter_is_combined_with_tenant_tag():
    """When AWS_COSTS_LINKED_ACCOUNT_ID is set AND a tenant tag is
    requested, both filters are combined via ``And`` so we don't sum
    spend from a sibling linked account that happens to share the same
    tenant tag value."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [{"start": "2026-05-01", "groups": [("Amazon Bedrock", 2.0)]}]
    )
    provider = _make_provider(ce, linked_account_id="123456789012")

    provider.tenant_cost_breakdown("alpha", days=30)

    call_kwargs = ce.get_cost_and_usage.call_args.kwargs
    f = call_kwargs["Filter"]
    assert "And" in f
    keys = {next(iter(clause)) for clause in f["And"]}
    # "Not" is the always-on credit/refund exclusion.
    assert keys == {"Not", "Dimensions", "Tags"}


def test_cost_provider_factory_returns_aws_when_gated_on(monkeypatch):
    """When CONSOLE_MOCK_INFRA=false and AWS_COSTS_TELEMETRY_ENABLED=true,
    ``cost_provider()`` returns the new AwsCostProvider — not the legacy
    stub in console_telemetry_real and not the mock."""
    monkeypatch.setenv("CONSOLE_MOCK_INFRA", "false")
    monkeypatch.setenv("AWS_COSTS_TELEMETRY_ENABLED", "true")

    provider = console_telemetry.cost_provider()

    assert isinstance(provider, AwsCostProvider)


def test_tenant_cost_provider_resolves_to_same_provider(monkeypatch):
    """The ``tenant_cost_provider`` seam returns the same instance the
    platform-wide ``cost_provider`` returns — they share the AWS CE
    client and TTL cache so per-tenant calls hit the warm cache."""
    monkeypatch.setenv("CONSOLE_MOCK_INFRA", "false")
    monkeypatch.setenv("AWS_COSTS_TELEMETRY_ENABLED", "true")

    a = console_telemetry.cost_provider()
    b = console_telemetry.tenant_cost_provider()

    assert isinstance(a, AwsCostProvider)
    assert isinstance(b, AwsCostProvider)
    # Both come from the same singleton.
    assert a is b


def test_platform_query_excludes_credits_and_refunds():
    """Every platform-wide query must carry a ``Not`` RECORD_TYPE filter
    excluding Credit/Refund so the buckets reflect real usage (no negative
    slice from a credit landing on a single service)."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [{"start": "2026-05-01", "groups": [("Amazon Elastic Kubernetes Service", 8.75)]}]
    )
    provider = _make_provider(ce)

    provider.platform_cost_breakdown(days=30)

    f = ce.get_cost_and_usage.call_args.kwargs["Filter"]
    # No linked account / tenant → the only clause is the credit exclusion.
    assert f == {
        "Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}
    }


def test_networking_services_map_to_network_bucket():
    """NAT gateway, VPC, load balancers and Route 53 must land in the
    network bucket — previously they leaked into compute and made the
    Network slice look artificially tiny."""
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = _ce_response(
        [
            {
                "start": "2026-05-01",
                "groups": [
                    ("Amazon Virtual Private Cloud", 3.0),  # NAT gateway hours
                    ("Elastic Load Balancing", 2.0),
                    ("Amazon Route 53", 0.5),
                    ("Amazon Elastic Kubernetes Service", 4.0),
                ],
            },
        ]
    )
    provider = _make_provider(ce)

    b = provider.platform_cost_breakdown(days=7)

    assert b.network_usd == pytest.approx(3.0 + 2.0 + 0.5)
    assert b.compute_usd == pytest.approx(4.0)


def test_revenue_summary_raises_telemetry_unavailable():
    """Revenue is not sourced from AWS — the provider must surface a
    clear ``TelemetryUnavailable`` rather than fabricating a number."""
    provider = _make_provider(MagicMock())

    with pytest.raises(TelemetryUnavailable):
        provider.revenue_summary()
