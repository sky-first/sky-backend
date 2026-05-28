"""Telemetry providers for the Internal Console.

Four classes of telemetry that the platform cannot synthesise from the
registry alone:

* **Infra** — pod status, restarts, last deploy SHA (Kubernetes API).
* **Cost** — AWS Cost Allocation Tags + Bedrock spend (AWS Cost Explorer).
* **Activity** — ai_queries per tenant per day, queried directly from each
  tenant's database via ``query_platform_activity_24h`` /
  ``query_tenant_activity_7d`` in ``console_telemetry_real``.
* **Billing** — subscription amounts and payment status (Moloni REST API).

Each lives behind a Protocol so the production wiring can be swapped
without rewriting routes.

When a real provider is not yet configured, its factory returns an empty/
zero fallback — the route still returns 200 with empty data rather than
503, so the Console UI renders gracefully while integrations are set up.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)


class TelemetryUnavailable(RuntimeError):
    """Raised when a real provider is configured but unreachable."""


# ── Data classes ───────────────────────────────────────────────────


@dataclass
class PlatformHealth:
    api_uptime_pct: float
    api_latency_p95_ms: int
    api_error_rate_pct: float
    pods_running: int
    pods_pending: int
    pods_crashlooping: int
    db_connections_used: int
    db_connections_max: int
    last_incident: Optional[str] = None


@dataclass
class TimeseriesPoint:
    t: str  # ISO timestamp
    value: float
    label: Optional[str] = None  # tenant slug for stacked series


@dataclass
class PodInfo:
    name: str
    namespace: str
    component: str
    status: str
    restarts: int
    cpu_pct: float
    memory_pct: float
    age_hours: int
    image_sha: str


@dataclass
class TenantHealth:
    pods: List[PodInfo]
    last_deploy_at: str
    last_deploy_sha: str
    argocd_url: str
    grafana_url: str


@dataclass
class CostBreakdown:
    period_start: str
    period_end: str
    compute_usd: float
    storage_usd: float
    network_usd: float
    bedrock_usd: float
    total_usd: float
    daily: List[TimeseriesPoint]


@dataclass
class TenantBilling:
    tier: str
    subscription_start: str
    subscription_end: str
    monthly_amount_eur: float
    payment_status: str
    last_invoice_at: Optional[str]
    next_invoice_at: Optional[str]
    mrr_contribution_eur: float


@dataclass
class Alert:
    severity: str
    title: str
    detail: str
    tenant_slug: Optional[str]
    fired_at: str
    suggested_action: str


@dataclass
class ClusterNode:
    name: str
    cluster: str
    role: str
    cpu_pct: float
    memory_pct: float
    pods_count: int
    status: str


@dataclass
class IncidentEntry:
    id: str
    severity: str
    title: str
    started_at: str
    resolved_at: Optional[str]
    affected_tenants: List[str]


# ── Protocols ──────────────────────────────────────────────────────


class InfraProvider(Protocol):
    def platform_health(self) -> PlatformHealth: ...
    def tenant_health(self, slug: str) -> TenantHealth: ...
    def cluster_nodes(self) -> List[ClusterNode]: ...


class CostProvider(Protocol):
    def platform_cost(self) -> CostBreakdown: ...
    def tenant_cost(self, slug: str) -> CostBreakdown: ...
    def revenue_summary(self) -> Dict[str, float]: ...


class ActivityProvider(Protocol):
    def platform_activity_24h(self, tenant_slugs: Sequence[str]) -> List[TimeseriesPoint]: ...
    def tenant_activity_7d(self, slug: str) -> List[TimeseriesPoint]: ...
    def top_tenants_by_queries(self) -> List[Dict[str, Any]]: ...


class BillingProvider(Protocol):
    def tenant_billing(self, slug: str, tier: str, created_at: Optional[datetime] = None) -> TenantBilling: ...
    def alerts(self) -> List[Alert]: ...
    def incidents(self) -> List[IncidentEntry]: ...


# ── Helpers ────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _empty_cost_breakdown() -> CostBreakdown:
    end = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    return CostBreakdown(
        period_start=_iso(start),
        period_end=_iso(end),
        compute_usd=0.0, storage_usd=0.0, network_usd=0.0,
        bedrock_usd=0.0, total_usd=0.0,
        daily=[
            TimeseriesPoint(t=_iso(start + timedelta(days=i)), value=0.0)
            for i in range(30)
        ],
    )


# ── Empty fallback providers ────────────────────────────────────────
# Return zero/empty data when the real integration is not yet configured.
# The Console UI renders gracefully with empty states instead of crashing.


class _EmptyInfraProvider:
    def platform_health(self) -> PlatformHealth:
        return PlatformHealth(
            api_uptime_pct=0.0, api_latency_p95_ms=0, api_error_rate_pct=0.0,
            pods_running=0, pods_pending=0, pods_crashlooping=0,
            db_connections_used=0, db_connections_max=0, last_incident=None,
        )

    def tenant_health(self, slug: str) -> TenantHealth:
        return TenantHealth(
            pods=[], last_deploy_at="", last_deploy_sha="",
            argocd_url=f"https://argocd.skyfirstlabs.com/applications/{slug}-prd",
            grafana_url=f"https://grafana.skyfirstlabs.com/d/tenant/{slug}",
        )

    def cluster_nodes(self) -> List[ClusterNode]:
        return []


class _EmptyCostProvider:
    def platform_cost(self) -> CostBreakdown:
        return _empty_cost_breakdown()

    def tenant_cost(self, slug: str) -> CostBreakdown:
        return _empty_cost_breakdown()

    def revenue_summary(self) -> Dict[str, float]:
        return {
            "mrr_eur": 0.0, "this_month_spend_usd": 0.0,
            "gross_margin_pct": 0.0, "projection_eom_usd": 0.0,
        }


_PRICE_BY_TIER: Dict[str, float] = {
    "pilot": 1_250.0, "foundation": 3_500.0, "core": 7_500.0,
    "advanced": 15_000.0, "strategic": 35_000.0,
}


class _RegistryBillingProvider:
    """Derives billing amounts from the tenant_registry tier field.

    Used until Moloni is configured. Alerts and incidents return empty
    lists — wire Sentry/PagerDuty in ``console_telemetry_real`` to
    populate those.
    """

    def tenant_billing(self, slug: str, tier: str, created_at: Optional[datetime] = None) -> TenantBilling:
        monthly = _PRICE_BY_TIER.get(tier, 0.0)
        now = created_at or _now()
        try:
            sub_end = now.replace(year=now.year + 1)
        except ValueError:
            sub_end = now.replace(year=now.year + 1, day=28)
        return TenantBilling(
            tier=tier,
            subscription_start=_iso(now),
            subscription_end=_iso(sub_end),
            monthly_amount_eur=monthly,
            payment_status="unknown",
            last_invoice_at=None,
            next_invoice_at=None,
            mrr_contribution_eur=monthly,
        )

    def alerts(self) -> List[Alert]:
        return []

    def incidents(self) -> List[IncidentEntry]:
        return []


# ── Factories ──────────────────────────────────────────────────────


def infra_provider() -> InfraProvider:
    """KubernetesInfraProvider + PrometheusHealthProvider when configured, else empty.

    With both KUBECONFIG_* and PROMETHEUS_URL set: returns CompositeInfraProvider
    that merges pod data (K8s) with SLI data (Prometheus).
    With only KUBECONFIG_*: KubernetesInfraProvider alone (Prometheus fields = 0).
    With neither: _EmptyInfraProvider (all zeros).
    """
    stg = os.getenv("KUBECONFIG_STAGING")
    prd = os.getenv("KUBECONFIG_PROD")
    if not stg or not prd:
        return _EmptyInfraProvider()
    try:
        from src.services.telemetry.kubernetes_provider import KubernetesInfraProvider
        k8s = KubernetesInfraProvider()
        if os.getenv("PROMETHEUS_URL"):
            from src.services.telemetry.prometheus_provider import PrometheusHealthProvider
            from src.services.telemetry.composite_infra_provider import CompositeInfraProvider
            return CompositeInfraProvider(k8s=k8s, prometheus=PrometheusHealthProvider())
        return k8s
    except Exception:  # noqa: BLE001
        return _EmptyInfraProvider()


def cost_provider() -> CostProvider:
    """Return AwsCostProvider when AWS credentials are present, else empty."""
    try:
        import boto3
        session = boto3.Session()
        if session.get_credentials() is None:
            return _EmptyCostProvider()
        from src.services.console_telemetry_real import AwsCostProvider
        return AwsCostProvider()
    except Exception:  # noqa: BLE001
        return _EmptyCostProvider()


def billing_provider() -> BillingProvider:
    """Return MoloniBillingProvider when MOLONI_API_KEY is set, else registry fallback."""
    if not os.getenv("MOLONI_API_KEY"):
        return _RegistryBillingProvider()
    try:
        from src.services.telemetry.moloni_billing_provider import MoloniBillingProvider
        return MoloniBillingProvider()
    except Exception:  # noqa: BLE001
        return _RegistryBillingProvider()


def alerts_provider():
    """Return Sentry, PagerDuty, or empty provider based on available env vars."""
    from src.services.telemetry.alerts_provider import get_alerts_provider
    return get_alerts_provider()
