"""Telemetry providers for the Internal Console (Projeto B B#7).

The Console UI needs four classes of telemetry that the platform cannot
synthesise from the registry alone:

* **Infra** — pod status, restarts, last deploy SHA. Real source is the
  kubectl API of each cluster (stg + prd).
* **Cost** — AWS Cost Allocation Tags + Bedrock Application Inference
  Profile cost. Real source is the AWS Cost Explorer API.
* **Activity** — queries / agents / sessions per tenant per day. Real
  source is the platform's own audit + Prometheus counters.
* **Logs** — live ``kubectl logs --follow`` per pod, multiplexed back
  to the browser via WebSocket.

Each lives behind a Protocol so the production wiring (boto3 / k8s
client / websocket) can drop in next sprint without rewriting routes.
The default implementation in this module is the **mock** path —
realistic-looking dummies that let the Console UI feel populated while
the runtime side ships.

Switch:
    CONSOLE_MOCK_INFRA=true  → mocks (default; safe everywhere)
    CONSOLE_MOCK_INFRA=false → real providers (production only)

When the flag is False but a real provider is unavailable, the call
raises ``TelemetryUnavailable`` and the route returns 503 — never
silently falls back to mocks in production.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)


# ── Switch ─────────────────────────────────────────────────────────


def _mock_mode_enabled() -> bool:
    raw = (os.getenv("CONSOLE_MOCK_INFRA") or "true").lower()
    return raw in {"true", "1", "yes", "on"}


class TelemetryUnavailable(RuntimeError):
    """Raised when the real provider was asked for but is unreachable."""


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
    last_incident: Optional[str] = None  # human-readable timestamp


@dataclass
class TimeseriesPoint:
    t: str  # ISO timestamp
    value: float
    label: Optional[str] = None  # for stacked series (tenant slug)


@dataclass
class PodInfo:
    name: str
    namespace: str
    component: str  # sky-be / sky-fe / sky-ai / sky-ai-worker / postgres / redis
    status: str  # running / pending / crashlooping / unknown
    restarts: int
    cpu_pct: float
    memory_pct: float
    age_hours: int
    image_sha: str  # short SHA


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
    payment_status: str  # paid / pending / overdue
    last_invoice_at: str
    next_invoice_at: str
    mrr_contribution_eur: float


@dataclass
class Alert:
    severity: str  # info / warning / critical
    title: str
    detail: str
    tenant_slug: Optional[str]
    fired_at: str
    suggested_action: str


@dataclass
class ClusterNode:
    name: str
    cluster: str  # stg / prd
    role: str
    cpu_pct: float
    memory_pct: float
    pods_count: int
    status: str  # ready / not_ready


@dataclass
class IncidentEntry:
    id: str
    severity: str
    title: str
    started_at: str
    resolved_at: Optional[str]
    affected_tenants: List[str]


# ── Protocols (real providers must satisfy these) ────────────────


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
    def tenant_billing(self, slug: str, tier: str) -> TenantBilling: ...
    def alerts(self) -> List[Alert]: ...
    def incidents(self) -> List[IncidentEntry]: ...


# ── Mock implementations ─────────────────────────────────────────


def _seeded(slug: str, salt: str = "") -> random.Random:
    """Deterministic random by tenant slug so the UI doesn't flicker
    every refresh."""
    h = hashlib.sha256(f"{slug}:{salt}".encode()).hexdigest()
    seed = int(h[:16], 16)
    return random.Random(seed)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MockInfraProvider:
    def platform_health(self) -> PlatformHealth:
        r = random.Random(int(_now().timestamp() // 60))  # changes per minute
        return PlatformHealth(
            api_uptime_pct=99.95,
            api_latency_p95_ms=r.randint(180, 280),
            api_error_rate_pct=round(r.uniform(0.05, 0.4), 2),
            pods_running=r.randint(28, 38),
            pods_pending=r.randint(0, 1),
            pods_crashlooping=0,
            db_connections_used=r.randint(15, 45),
            db_connections_max=200,
            last_incident="9 days ago",
        )

    def tenant_health(self, slug: str) -> TenantHealth:
        r = _seeded(slug, "health")
        components = [
            ("sky-be", 2, "running"),
            ("sky-fe", 2, "running"),
            ("sky-ai", 1, "running"),
            ("sky-ai-worker", 1, "running"),
            ("postgres", 1, "running"),
            ("redis", 1, "running"),
        ]
        pods: List[PodInfo] = []
        # Make one component look slightly stressed for the second tenant
        # to give the UI something to render.
        stressed_component = "sky-ai" if slug == "beta" else None
        for component, replicas, status in components:
            for i in range(replicas):
                cpu = r.uniform(8, 35)
                mem = r.uniform(20, 55)
                if component == stressed_component:
                    cpu = r.uniform(60, 85)
                    mem = r.uniform(65, 80)
                pods.append(
                    PodInfo(
                        name=f"{component}-{slug}-{r.randint(1000, 9999):04x}{i}",
                        namespace=f"{slug}-prd",
                        component=component,
                        status=status,
                        restarts=r.randint(0, 2),
                        cpu_pct=round(cpu, 1),
                        memory_pct=round(mem, 1),
                        age_hours=r.randint(8, 480),
                        image_sha=f"sha-{r.randint(0x100000, 0xFFFFFF):06x}",
                    )
                )
        return TenantHealth(
            pods=pods,
            last_deploy_at=_iso(_now() - timedelta(hours=r.randint(2, 72))),
            last_deploy_sha=f"sha-{r.randint(0x100000, 0xFFFFFF):06x}",
            argocd_url=f"https://argocd.skyfirstlabs.com/applications/{slug}-prd",
            grafana_url=f"https://grafana.skyfirstlabs.com/d/tenant/{slug}?var-tenant={slug}",
        )

    def cluster_nodes(self) -> List[ClusterNode]:
        r = random.Random(int(_now().timestamp() // 300))
        out: List[ClusterNode] = []
        for cluster in ("stg", "prd"):
            for i in range(3 if cluster == "prd" else 2):
                out.append(
                    ClusterNode(
                        name=f"ip-10-0-{r.randint(0, 255)}-{r.randint(0, 255)}.{cluster}",
                        cluster=cluster,
                        role="apps" if i > 0 else "infra",
                        cpu_pct=round(r.uniform(20, 70), 1),
                        memory_pct=round(r.uniform(40, 75), 1),
                        pods_count=r.randint(8, 22),
                        status="ready",
                    )
                )
        return out


class MockCostProvider:
    def platform_cost(self) -> CostBreakdown:
        # 30-day daily series with weekly seasonality.
        r = random.Random(int(_now().timestamp() // 86400))  # changes per day
        end = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=30)
        daily: List[TimeseriesPoint] = []
        total = 0.0
        for i in range(30):
            day = start + timedelta(days=i)
            base = 26.5 + 4.2 * math.sin(i / 7 * math.pi)
            v = round(base + r.uniform(-2.5, 2.5), 2)
            daily.append(TimeseriesPoint(t=_iso(day), value=v))
            total += v
        compute = round(total * 0.58, 2)
        storage = round(total * 0.09, 2)
        network = round(total * 0.12, 2)
        bedrock = round(total * 0.21, 2)
        return CostBreakdown(
            period_start=_iso(start),
            period_end=_iso(end),
            compute_usd=compute,
            storage_usd=storage,
            network_usd=network,
            bedrock_usd=bedrock,
            total_usd=round(total, 2),
            daily=daily,
        )

    def tenant_cost(self, slug: str) -> CostBreakdown:
        r = _seeded(slug, "cost")
        end = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=30)
        # Per-tenant baseline varies by slug
        baseline = 3.5 + r.uniform(0, 12.0)
        daily = []
        total = 0.0
        for i in range(30):
            day = start + timedelta(days=i)
            v = round(baseline + r.uniform(-1.2, 1.2) + math.sin(i / 4) * 0.7, 2)
            v = max(0.1, v)
            daily.append(TimeseriesPoint(t=_iso(day), value=v))
            total += v
        compute = round(total * 0.62, 2)
        storage = round(total * 0.07, 2)
        network = round(total * 0.10, 2)
        bedrock = round(total * 0.21, 2)
        return CostBreakdown(
            period_start=_iso(start),
            period_end=_iso(end),
            compute_usd=compute,
            storage_usd=storage,
            network_usd=network,
            bedrock_usd=bedrock,
            total_usd=round(total, 2),
            daily=daily,
        )

    def revenue_summary(self) -> Dict[str, float]:
        # MRR mocked from a tier-priced ladder, returned in EUR.
        return {
            "mrr_eur": 2500.0,
            "this_month_spend_usd": 280.0,
            "gross_margin_pct": round((2500.0 - 280.0 * 0.92) / 2500.0 * 100, 1),
            "projection_eom_usd": 380.0,
        }


class MockActivityProvider:
    def platform_activity_24h(
        self, tenant_slugs: Sequence[str]
    ) -> List[TimeseriesPoint]:
        # 24 hourly buckets, with one point per (hour, tenant).
        end = _now().replace(minute=0, second=0, microsecond=0)
        out: List[TimeseriesPoint] = []
        for slug in tenant_slugs:
            r = _seeded(slug, "activity24")
            for h in range(24):
                bucket = end - timedelta(hours=23 - h)
                # Diurnal pattern: more activity 8h-18h UTC.
                hour_local = (bucket.hour) % 24
                day_factor = 0.4 + 0.8 * max(0, math.sin((hour_local - 6) / 12 * math.pi))
                base = r.uniform(3, 18) * day_factor
                out.append(
                    TimeseriesPoint(
                        t=_iso(bucket),
                        value=round(base, 1),
                        label=slug,
                    )
                )
        return out

    def tenant_activity_7d(self, slug: str) -> List[TimeseriesPoint]:
        r = _seeded(slug, "activity7d")
        end = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        out: List[TimeseriesPoint] = []
        for d in range(7):
            day = end - timedelta(days=6 - d)
            base = r.uniform(80, 250)
            # Weekend dip
            if day.weekday() >= 5:
                base *= 0.55
            out.append(
                TimeseriesPoint(
                    t=_iso(day),
                    value=round(base, 0),
                )
            )
        return out

    def top_tenants_by_queries(self) -> List[Dict[str, Any]]:
        # The route layer fills the slugs from the registry; we return
        # the metric shape only.
        return []


class MockBillingProvider:
    _PRICE_BY_TIER = {
        "starter": 1250.0,
        "foundation": 3500.0,
        "core": 7500.0,
        "advanced": 15000.0,
        "strategic": 35000.0,
    }

    def tenant_billing(self, slug: str, tier: str) -> TenantBilling:
        r = _seeded(slug, "billing")
        monthly = self._PRICE_BY_TIER.get(tier, 1250.0)
        start = _now() - timedelta(days=r.randint(20, 200))
        end = start + timedelta(days=365)
        statuses = ["paid", "paid", "paid", "pending"]
        return TenantBilling(
            tier=tier,
            subscription_start=_iso(start),
            subscription_end=_iso(end),
            monthly_amount_eur=monthly,
            payment_status=r.choice(statuses),
            last_invoice_at=_iso(_now() - timedelta(days=r.randint(1, 28))),
            next_invoice_at=_iso(_now() + timedelta(days=r.randint(2, 30))),
            mrr_contribution_eur=monthly,
        )

    def alerts(self) -> List[Alert]:
        # Mock alert center. Routes filter by tenant existence.
        now = _now()
        return [
            Alert(
                severity="warning",
                title="Capacity > 80%",
                detail="beta is using 83% of indexed_context limit (42/50 GB).",
                tenant_slug="beta",
                fired_at=_iso(now - timedelta(hours=2)),
                suggested_action="Suggest upgrading to Core or raising indexed_gb in capacity_limits.",
            ),
            Alert(
                severity="info",
                title="Subscription renewal due in 21 days",
                detail="alpha renewal at 2026-06-17.",
                tenant_slug="alpha",
                fired_at=_iso(now - timedelta(hours=18)),
                suggested_action="Open Billing tab to send renewal proposal.",
            ),
        ]

    def incidents(self) -> List[IncidentEntry]:
        now = _now()
        return [
            IncidentEntry(
                id="inc-0042",
                severity="warning",
                title="Elevated p95 latency on sky-ai (resolved)",
                started_at=_iso(now - timedelta(days=9, hours=2)),
                resolved_at=_iso(now - timedelta(days=9, hours=1)),
                affected_tenants=["beta"],
            ),
            IncidentEntry(
                id="inc-0041",
                severity="info",
                title="Scheduled deploy — sky-be v1.42",
                started_at=_iso(now - timedelta(days=11)),
                resolved_at=_iso(now - timedelta(days=11)),
                affected_tenants=["alpha", "beta"],
            ),
        ]


# ── Real provider stubs ───────────────────────────────────────────
# These raise TelemetryUnavailable until implemented. The Console
# routes catch the exception and surface a 503 with a helpful note
# so operators know the integration is still wiring.


class _NotYetImplementedInfra:
    def platform_health(self) -> PlatformHealth:
        raise TelemetryUnavailable(
            "Real InfraProvider not yet implemented — set CONSOLE_MOCK_INFRA=true "
            "or wire up kubernetes-client in src/services/console_telemetry_real.py"
        )

    def tenant_health(self, slug: str) -> TenantHealth:
        raise TelemetryUnavailable("Real InfraProvider not yet implemented")

    def cluster_nodes(self) -> List[ClusterNode]:
        raise TelemetryUnavailable("Real InfraProvider not yet implemented")


class _NotYetImplementedCost:
    def platform_cost(self) -> CostBreakdown:
        raise TelemetryUnavailable(
            "Real CostProvider not yet implemented — set CONSOLE_MOCK_INFRA=true "
            "or wire up AWS Cost Explorer in src/services/console_telemetry_real.py"
        )

    def tenant_cost(self, slug: str) -> CostBreakdown:
        raise TelemetryUnavailable("Real CostProvider not yet implemented")

    def revenue_summary(self) -> Dict[str, float]:
        raise TelemetryUnavailable("Real CostProvider not yet implemented")


# ── Factories ──────────────────────────────────────────────────────


def _k8s_telemetry_enabled() -> bool:
    """Gate the real K8s provider behind both the existing mock flag
    *and* the new ``K8S_TELEMETRY_ENABLED`` setting (issue #39).

    Read lazily from settings *and* from env so tests using
    ``monkeypatch.setenv`` flip behaviour without rebuilding the
    Pydantic Settings instance.
    """
    env_raw = os.getenv("K8S_TELEMETRY_ENABLED")
    if env_raw is not None:
        return env_raw.lower() in {"true", "1", "yes", "on"}
    try:
        from src.config.settings import settings as _settings

        return bool(getattr(_settings, "K8S_TELEMETRY_ENABLED", False))
    except Exception:  # noqa: BLE001
        return False


def infra_provider() -> InfraProvider:
    if _mock_mode_enabled():
        return MockInfraProvider()
    # New path: live Kubernetes telemetry behind K8S_TELEMETRY_ENABLED.
    # Returns a provider whose ``platform_health`` / ``tenant_health``
    # satisfy the InfraProvider Protocol (see KubernetesTelemetryProvider
    # in ``src/services/k8s_telemetry.py``).
    if _k8s_telemetry_enabled():
        try:
            from src.services.k8s_telemetry import get_provider

            return get_provider()
        except TelemetryUnavailable:
            return _NotYetImplementedInfra()
    try:
        from src.services.console_telemetry_real import KubernetesInfraProvider

        return KubernetesInfraProvider()
    except TelemetryUnavailable:
        return _NotYetImplementedInfra()


def _aws_costs_telemetry_enabled() -> bool:
    """Gate the real AWS Cost Explorer provider behind both the existing
    mock flag *and* the new ``AWS_COSTS_TELEMETRY_ENABLED`` setting
    (issue #40).

    Read lazily from settings *and* from env so tests using
    ``monkeypatch.setenv`` flip behaviour without rebuilding the
    Pydantic Settings instance — mirrors ``_k8s_telemetry_enabled``.
    """
    env_raw = os.getenv("AWS_COSTS_TELEMETRY_ENABLED")
    if env_raw is not None:
        return env_raw.lower() in {"true", "1", "yes", "on"}
    try:
        from src.config.settings import settings as _settings

        return bool(getattr(_settings, "AWS_COSTS_TELEMETRY_ENABLED", False))
    except Exception:  # noqa: BLE001
        return False


def cost_provider() -> CostProvider:
    if _mock_mode_enabled():
        return MockCostProvider()
    # New path: live AWS Cost Explorer behind AWS_COSTS_TELEMETRY_ENABLED.
    # Returns a provider whose ``platform_cost`` / ``tenant_cost`` /
    # ``platform_cost_breakdown`` / ``tenant_cost_breakdown`` satisfy
    # both the legacy CostProvider Protocol and the new days-aware shape
    # consumed by the CEO Master Dashboard (PR #477).
    if _aws_costs_telemetry_enabled():
        try:
            from src.services.aws_cost_provider import get_provider as _get_aws_cost

            return _get_aws_cost()
        except TelemetryUnavailable:
            return _NotYetImplementedCost()
    try:
        from src.services.console_telemetry_real import AwsCostProvider

        return AwsCostProvider()
    except TelemetryUnavailable:
        return _NotYetImplementedCost()


def tenant_cost_provider() -> CostProvider:
    """Provider used for per-tenant cost queries.

    Today this resolves to the same provider as ``cost_provider`` — the
    AWS path uses cost-allocation tags so a single provider can answer
    both platform-wide and per-tenant queries. The function exists as a
    seam so a future split (e.g. EKS Karpenter cost model per tenant)
    does not require reaching into ``cost_provider`` callers.
    """
    return cost_provider()


def activity_provider() -> ActivityProvider:
    # Activity always uses the audit log (real) for the "platform" view,
    # but the synthetic per-tenant timeline is mocked until we ship a
    # Prometheus exporter. Mock-only for now in both branches.
    return MockActivityProvider()


def billing_provider() -> BillingProvider:
    # Billing mock today; production wires Moloni's API.
    return MockBillingProvider()
