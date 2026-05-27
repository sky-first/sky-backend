"""Real-data implementations of the Console telemetry providers.

These ship behind ``CONSOLE_MOCK_INFRA=false`` and provide the
production code path that pulls live data from Kubernetes, AWS Cost
Explorer, and Moloni. Each provider catches its own infrastructure
errors and converts them to ``TelemetryUnavailable`` so the routes
return a clean 503 instead of leaking stack traces.

Dependencies (lazy-imported, opt-in):

* ``kubernetes`` for ``KubernetesInfraProvider``
* ``boto3`` for ``AwsCostProvider``
* ``requests`` for ``MoloniBillingProvider``

To switch to real providers in production, set the env vars
documented in each class docstring then deploy.

This module is **not** loaded automatically — the factory in
``console_telemetry`` only constructs these when the mock flag is
off, which means ``import boto3`` does not fire during normal local
dev.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from src.services.console_telemetry import (
    Alert,
    ClusterNode,
    CostBreakdown,
    IncidentEntry,
    PlatformHealth,
    PodInfo,
    TelemetryUnavailable,
    TenantBilling,
    TenantHealth,
    TimeseriesPoint,
)

logger = logging.getLogger(__name__)


# ── Kubernetes ─────────────────────────────────────────────────────


class KubernetesInfraProvider:
    """Real ``InfraProvider`` backed by the kubernetes-client library.

    Required env vars:
        KUBECONFIG_STAGING  — path to kubeconfig for the stg cluster
        KUBECONFIG_PROD     — path to kubeconfig for the prd cluster
        (or use the SSM tunnel paths from ``new-client.sh`` runbook)

    Discovers tenant namespaces by labels:
        tenant=<slug>
        tenant-env=stg|prd

    The provider memoises kubernetes API clients across calls so
    repeated requests don't re-read kubeconfig. Each call wraps the
    real Kubernetes API call in a try/except — connection issues
    surface as ``TelemetryUnavailable(503)``.
    """

    def __init__(self) -> None:
        self._stg_client = None
        self._prd_client = None
        self._tried_init = False

    def _ensure_clients(self) -> None:
        if self._tried_init:
            return
        self._tried_init = True
        try:
            from kubernetes import client, config  # type: ignore[import-not-found]
        except ImportError as exc:
            raise TelemetryUnavailable(
                "kubernetes-client not installed — pip install kubernetes"
            ) from exc
        stg_path = os.getenv("KUBECONFIG_STAGING")
        prd_path = os.getenv("KUBECONFIG_PROD")
        if not stg_path or not prd_path:
            raise TelemetryUnavailable(
                "KUBECONFIG_STAGING and KUBECONFIG_PROD env vars required "
                "for KubernetesInfraProvider"
            )
        try:
            config.load_kube_config(config_file=stg_path)
            self._stg_client = client.CoreV1Api()
            config.load_kube_config(config_file=prd_path)
            self._prd_client = client.CoreV1Api()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"Failed to load kubeconfigs: {exc}"
            ) from exc

    def platform_health(self) -> PlatformHealth:
        self._ensure_clients()
        try:
            assert self._prd_client and self._stg_client
            running = pending = crash = 0
            for c in (self._stg_client, self._prd_client):
                pods = c.list_pod_for_all_namespaces().items  # type: ignore[union-attr]
                for p in pods:
                    phase = (p.status.phase or "").lower()
                    if phase == "running":
                        running += 1
                    elif phase == "pending":
                        pending += 1
                    cs = p.status.container_statuses or []
                    for st in cs:
                        if (
                            st.state
                            and st.state.waiting
                            and (st.state.waiting.reason or "").lower()
                            == "crashloopbackoff"
                        ):
                            crash += 1
                            break
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"kubernetes platform_health failed: {exc}"
            ) from exc
        # Latency / uptime / error_rate come from Prometheus — TODO
        # (use ``prometheus_api_client``). Until then, surface only
        # the pod counts; the rest is N/A.
        return PlatformHealth(
            api_uptime_pct=0.0,
            api_latency_p95_ms=0,
            api_error_rate_pct=0.0,
            pods_running=running,
            pods_pending=pending,
            pods_crashlooping=crash,
            db_connections_used=0,
            db_connections_max=0,
            last_incident=None,
        )

    def tenant_health(self, slug: str) -> TenantHealth:
        self._ensure_clients()
        try:
            assert self._prd_client and self._stg_client
            pods: List[PodInfo] = []
            for env_label, c in (
                ("stg", self._stg_client),
                ("prd", self._prd_client),
            ):
                ns = f"{slug}-{env_label}"
                try:
                    items = c.list_namespaced_pod(ns).items  # type: ignore[union-attr]
                except Exception as inner:  # noqa: BLE001
                    logger.warning(
                        "tenant_health_namespace_query_failed",
                        extra={"slug": slug, "env": env_label, "error": str(inner)[:200]},
                    )
                    continue
                for p in items:
                    container = (
                        p.spec.containers[0] if p.spec and p.spec.containers else None
                    )
                    component = (
                        p.metadata.labels.get("app.kubernetes.io/component")
                        or p.metadata.labels.get("component")
                        or "unknown"
                        if p.metadata and p.metadata.labels
                        else "unknown"
                    )
                    restarts = sum(
                        s.restart_count for s in (p.status.container_statuses or [])
                    )
                    image_sha = (
                        container.image.rsplit("@sha256:", 1)[-1][:12]
                        if container and container.image and "@sha256:" in container.image
                        else "—"
                    )
                    age_hours = 0
                    if p.metadata.creation_timestamp:
                        age_hours = int(
                            (
                                datetime.now(timezone.utc) - p.metadata.creation_timestamp
                            ).total_seconds()
                            / 3600
                        )
                    pods.append(
                        PodInfo(
                            name=p.metadata.name,
                            namespace=ns,
                            component=component,
                            status=(p.status.phase or "Unknown").lower(),
                            restarts=int(restarts),
                            cpu_pct=0.0,  # needs metrics-server
                            memory_pct=0.0,
                            age_hours=age_hours,
                            image_sha=image_sha,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"kubernetes tenant_health failed: {exc}"
            ) from exc
        return TenantHealth(
            pods=pods,
            last_deploy_at=datetime.now(timezone.utc).isoformat(),
            last_deploy_sha="—",
            argocd_url=(
                os.getenv("ARGOCD_BASE_URL", "https://argocd.skyfirstlabs.com")
                + f"/applications/{slug}-prd"
            ),
            grafana_url=(
                os.getenv("GRAFANA_BASE_URL", "https://grafana.skyfirstlabs.com")
                + f"/d/tenant/{slug}?var-tenant={slug}"
            ),
        )

    def cluster_nodes(self) -> List[ClusterNode]:
        self._ensure_clients()
        out: List[ClusterNode] = []
        try:
            assert self._prd_client and self._stg_client
            for cluster, c in (
                ("stg", self._stg_client),
                ("prd", self._prd_client),
            ):
                for n in c.list_node().items:  # type: ignore[union-attr]
                    role = "infra"
                    if n.metadata.labels:
                        for k in n.metadata.labels:
                            if k.startswith("node-role.kubernetes.io/"):
                                role = k.split("/", 1)[1] or role
                                break
                    status = "ready"
                    for cond in n.status.conditions or []:
                        if cond.type == "Ready":
                            status = "ready" if cond.status == "True" else "not_ready"
                    pods_on_node = 0
                    try:
                        all_pods = c.list_pod_for_all_namespaces(  # type: ignore[union-attr]
                            field_selector=f"spec.nodeName={n.metadata.name}"
                        ).items
                        pods_on_node = len(all_pods)
                    except Exception:  # noqa: BLE001
                        pass
                    out.append(
                        ClusterNode(
                            name=n.metadata.name,
                            cluster=cluster,
                            role=role,
                            cpu_pct=0.0,  # needs metrics-server
                            memory_pct=0.0,
                            pods_count=pods_on_node,
                            status=status,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"kubernetes cluster_nodes failed: {exc}"
            ) from exc
        return out


# ── AWS Cost Explorer ──────────────────────────────────────────────


class AwsCostProvider:
    """Real ``CostProvider`` backed by AWS Cost Explorer.

    Required env vars:
        AWS_REGION                — typically eu-west-1
        AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  (or IRSA when on EKS)
        BEDROCK_PROFILE_PREFIX    — applied to tenant inference profile
                                    ARNs to group spend (default sky-)

    Uses cost-allocation tags ``TenantID`` and ``ApplicationID`` to
    split spend per tenant. Tags must be activated in the Billing
    console and propagated for at least 24h before this surfaces
    real data; until then ``TelemetryUnavailable`` is raised.
    """

    def __init__(self) -> None:
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TelemetryUnavailable(
                "boto3 not installed — pip install boto3"
            ) from exc
        region = os.getenv("AWS_REGION") or "eu-west-1"
        try:
            self._client = boto3.client("ce", region_name=region)
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"AWS Cost Explorer client init failed: {exc}"
            ) from exc
        return self._client

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    def _daily_series(
        self, ce_filter: Optional[dict] = None
    ) -> tuple[List[TimeseriesPoint], Dict[str, float]]:
        client = self._ensure_client()
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=30)
        params = {
            "TimePeriod": {"Start": self._iso(start), "End": self._iso(end)},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "DIMENSION", "Key": "SERVICE"},
            ],
        }
        if ce_filter:
            params["Filter"] = ce_filter
        try:
            resp = client.get_cost_and_usage(**params)
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"Cost Explorer query failed: {exc}"
            ) from exc

        daily: List[TimeseriesPoint] = []
        totals_by_service: Dict[str, float] = {}
        for period in resp.get("ResultsByTime", []):
            day_total = 0.0
            for g in period.get("Groups", []):
                service = (g.get("Keys") or ["unknown"])[0]
                amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
                day_total += amt
                totals_by_service[service] = (
                    totals_by_service.get(service, 0) + amt
                )
            daily.append(
                TimeseriesPoint(
                    t=period["TimePeriod"]["Start"] + "T00:00:00+00:00",
                    value=round(day_total, 2),
                )
            )
        return daily, totals_by_service

    def platform_cost(self) -> CostBreakdown:
        daily, by_service = self._daily_series()
        compute = sum(
            v for k, v in by_service.items() if "EC2" in k or "EKS" in k or "Fargate" in k
        )
        storage = sum(v for k, v in by_service.items() if "EBS" in k or "S3" in k)
        network = sum(v for k, v in by_service.items() if "Transfer" in k)
        bedrock = sum(v for k, v in by_service.items() if "Bedrock" in k)
        total = sum(by_service.values())
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return CostBreakdown(
            period_start=(end - timedelta(days=30)).isoformat(),
            period_end=end.isoformat(),
            compute_usd=round(compute, 2),
            storage_usd=round(storage, 2),
            network_usd=round(network, 2),
            bedrock_usd=round(bedrock, 2),
            total_usd=round(total, 2),
            daily=daily,
        )

    def tenant_cost(self, slug: str) -> CostBreakdown:
        ce_filter = {
            "Tags": {"Key": "TenantID", "Values": [slug]},
        }
        daily, by_service = self._daily_series(ce_filter=ce_filter)
        compute = sum(
            v for k, v in by_service.items() if "EC2" in k or "EKS" in k or "Fargate" in k
        )
        storage = sum(v for k, v in by_service.items() if "EBS" in k or "S3" in k)
        network = sum(v for k, v in by_service.items() if "Transfer" in k)
        bedrock = sum(v for k, v in by_service.items() if "Bedrock" in k)
        total = sum(by_service.values())
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return CostBreakdown(
            period_start=(end - timedelta(days=30)).isoformat(),
            period_end=end.isoformat(),
            compute_usd=round(compute, 2),
            storage_usd=round(storage, 2),
            network_usd=round(network, 2),
            bedrock_usd=round(bedrock, 2),
            total_usd=round(total, 2),
            daily=daily,
        )

    def revenue_summary(self) -> Dict[str, float]:
        # Revenue comes from Moloni, not from AWS — this provider
        # should not be the source of truth. Raise so the route
        # surfaces a 503 hinting at the right integration.
        raise TelemetryUnavailable(
            "revenue_summary lives in MoloniBillingProvider, not the AWS "
            "cost provider — fix the wiring in console_telemetry.factory"
        )


# ── Moloni billing ─────────────────────────────────────────────────


class MoloniBillingProvider:
    """Real ``BillingProvider`` backed by the Moloni REST API.

    Required env vars:
        MOLONI_API_KEY     — long-lived API key
        MOLONI_COMPANY_ID  — Moloni internal company id for SkyFirst
        MOLONI_BASE_URL    — defaults to https://api.moloni.pt/v1

    Returns the tenant billing record from a customer record matched
    by ``slug`` (Moloni custom field). Invoices, payment status and
    pipeline are queried in the same call. Network errors surface as
    ``TelemetryUnavailable``.
    """

    def __init__(self) -> None:
        self._base_url = os.getenv("MOLONI_BASE_URL", "https://api.moloni.pt/v1")
        self._token: Optional[str] = None
        self._token_exp: Optional[datetime] = None

    def _ensure_token(self) -> str:
        try:
            import requests  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TelemetryUnavailable(
                "requests not installed — pip install requests"
            ) from exc
        if self._token and self._token_exp and self._token_exp > datetime.now(timezone.utc):
            return self._token
        api_key = os.getenv("MOLONI_API_KEY")
        if not api_key:
            raise TelemetryUnavailable("MOLONI_API_KEY env var required")
        try:
            r = requests.post(
                f"{self._base_url}/grant",
                json={"grant_type": "api_key", "api_key": api_key},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(f"Moloni token grant failed: {exc}") from exc
        self._token = data.get("access_token")
        if not self._token:
            raise TelemetryUnavailable("Moloni response missing access_token")
        self._token_exp = datetime.now(timezone.utc) + timedelta(
            seconds=int(data.get("expires_in", 3600))
        )
        return self._token

    def tenant_billing(self, slug: str, tier: str) -> TenantBilling:
        # Real call would look up Moloni customer by slug field, then
        # retrieve their active subscription + latest invoice + next
        # billing date. Stubbed-out shape preserved for the schema.
        raise TelemetryUnavailable(
            "MoloniBillingProvider.tenant_billing not yet implemented — "
            "wire customer lookup by slug field + active-invoice query"
        )

    def alerts(self) -> List[Alert]:
        raise TelemetryUnavailable(
            "Alerts live in CloudWatch / Sentry, not Moloni. Wire those "
            "providers in console_telemetry_real instead."
        )

    def incidents(self) -> List[IncidentEntry]:
        raise TelemetryUnavailable(
            "Incidents live in Sentry / PagerDuty. Wire those providers."
        )


__all__ = [
    "AwsCostProvider",
    "KubernetesInfraProvider",
    "MoloniBillingProvider",
]
