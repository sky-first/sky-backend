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

from typing import Any

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
                # Accumulate all amounts per-service (negatives kept for
                # the cost-mix breakdown), but only count positive amounts
                # toward the daily spend bar so data-transfer credits don't
                # cancel out compute charges on the chart.
                totals_by_service[service] = (
                    totals_by_service.get(service, 0) + amt
                )
                if amt > 0:
                    day_total += amt
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
        # AWS Cost Explorer can return negative rows for data-transfer credits that
        # exactly cancel out the corresponding compute charges. Sum only positive
        # amounts so Spend MTD reflects gross spend, not the net after credits.
        total = sum(v for v in by_service.values() if v > 0)
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
        total = sum(v for v in by_service.values() if v > 0)
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

    @staticmethod
    def _moloni_tier_price_eur(tier: str) -> float:
        prices = {
            "starter": 1250.0,
            "foundation": 3500.0,
            "core": 7500.0,
            "advanced": 15000.0,
            "strategic": 35000.0,
        }
        return prices.get(tier, 1250.0)

    def _moloni_get(self, path: str, params: Dict[str, Any]) -> Any:
        try:
            import requests  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TelemetryUnavailable("requests not installed") from exc
        token = self._ensure_token()
        params = dict(params)
        params.setdefault("access_token", token)
        company_id = os.getenv("MOLONI_COMPANY_ID")
        if company_id and "company_id" not in params:
            params["company_id"] = company_id
        try:
            r = requests.get(f"{self._base_url}/{path.lstrip('/')}", params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(f"Moloni GET {path} failed: {exc}") from exc

    def _find_customer_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        # Moloni customers list endpoint; we filter by 'reference' or
        # 'name' containing slug. The customer record must carry the
        # tenant slug in its 'reference' field (set when SkyFirst
        # creates a Moloni customer during onboarding).
        rows = self._moloni_get("customers/getAll/", {"qty": 200})
        if not isinstance(rows, list):
            return None
        slug_l = slug.lower()
        for c in rows:
            ref = (c.get("reference") or "").lower()
            name = (c.get("name") or "").lower()
            if slug_l == ref or slug_l in name:
                return c
        return None

    def tenant_billing(self, slug: str, tier: str) -> TenantBilling:
        # Strategy: look up Moloni customer where reference matches the
        # tenant slug, then fetch the most recent paid + the next
        # scheduled invoice. If we can't resolve the customer, surface
        # 503 so the Console shows a clear "Moloni mapping missing"
        # banner rather than a fabricated number.
        customer = self._find_customer_by_slug(slug)
        if not customer:
            raise TelemetryUnavailable(
                f"Moloni customer not found for slug={slug} — "
                "set the 'reference' field to the tenant slug in Moloni"
            )
        customer_id = customer.get("customer_id") or customer.get("id")
        if not customer_id:
            raise TelemetryUnavailable("Moloni customer record missing id")

        monthly = self._moloni_tier_price_eur(tier)
        last_invoice_at: Optional[str] = None
        next_invoice_at: Optional[str] = None
        payment_status = "pending"
        subscription_start: Optional[str] = None
        subscription_end: Optional[str] = None

        # Invoices: type 1 = Fatura (Portugal). Sort by date desc.
        try:
            invoices = self._moloni_get(
                "invoices/getAll/",
                {"customer_id": customer_id, "qty": 50},
            )
            if isinstance(invoices, list) and invoices:
                # Pick latest by 'date' field (YYYY-MM-DD)
                invoices.sort(key=lambda x: x.get("date", ""), reverse=True)
                latest = invoices[0]
                last_invoice_at = latest.get("date")
                # 1=draft, 2=closed/paid (Moloni status). Conservative.
                payment_status = "paid" if latest.get("status") in (2, "2") else "pending"
                subscription_start = invoices[-1].get("date")
                if last_invoice_at:
                    # next = +1 month from last
                    from datetime import date as _date

                    try:
                        y, m, d = (int(x) for x in last_invoice_at.split("-"))
                        nm = m + 1
                        ny = y + (1 if nm > 12 else 0)
                        nm = ((nm - 1) % 12) + 1
                        next_invoice_at = f"{ny:04d}-{nm:02d}-{min(d, 28):02d}"
                    except Exception:  # noqa: BLE001
                        next_invoice_at = None
        except TelemetryUnavailable:
            # Re-raise — operator needs to see the error rather than a
            # half-empty billing card.
            raise

        return TenantBilling(
            tier=tier,
            subscription_start=subscription_start,
            subscription_end=subscription_end,
            monthly_amount_eur=monthly,
            payment_status=payment_status,
            last_invoice_at=last_invoice_at,
            next_invoice_at=next_invoice_at,
            mrr_contribution_eur=monthly,
        )

    def revenue_summary(self) -> Dict[str, float]:
        """Real platform MRR derived from active tenants × tier price.

        Mocked previously as a hardcoded EUR 2500 + EUR 280 spend +
        78.6% gross margin. Now computes the actual answer:

        - **MRR (EUR):** sum of ``_moloni_tier_price_eur(tier)`` for
          every active tenant in the platform registry. The tier→price
          mapping is the same one this provider uses to bill each
          tenant individually, so the dashboard total reconciles
          exactly with the per-tenant Billing tab amounts.
        - **this_month_spend_usd / projection_eom_usd:** left at 0.0
          here. The Console route composes the revenue card by
          combining this provider's MRR with whatever the
          ``CostProvider`` (AWS Cost Explorer) reports for spend —
          two sources, one card. Returning 0.0 keeps the schema
          stable while making the cost portion the cost provider's
          job, not ours.
        - **gross_margin_pct:** 0.0 here; the route computes it from
          the combined MRR + spend it just assembled.

        Read the registry through the synchronous SQLAlchemy session
        (this is a sync provider, called from a sync route). We
        deliberately don't use ``AsyncSessionLocal`` here so the call
        site doesn't have to be async.
        """
        try:
            from src.config.database import engine as async_engine
            from src.models.tenant import Tenant
            from sqlalchemy import create_engine, select, func
        except Exception as exc:  # pragma: no cover — import guard
            raise TelemetryUnavailable(
                f"revenue_summary import failed: {exc}"
            ) from exc

        # Build a one-shot sync engine off the same DB URL.
        # render_as_string(hide_password=False) is required — str(url)
        # redacts the password as *** in SQLAlchemy 2.0, causing
        # authentication failure.
        try:
            raw_url = async_engine.url.render_as_string(hide_password=False)
        except Exception as exc:
            raise TelemetryUnavailable(f"revenue_summary: failed to build DB URL: {exc}") from exc
        sync_url = raw_url.replace("+asyncpg", "")
        sync_engine = create_engine(
            sync_url, pool_pre_ping=True, future=True,
            connect_args={"sslmode": "require"},
        )
        try:
            with sync_engine.connect() as conn:
                rows = conn.execute(
                    select(Tenant.tier).where(Tenant.is_active.is_(True))
                ).all()
        except Exception as exc:
            raise TelemetryUnavailable(f"revenue_summary: DB query failed: {exc}") from exc
        finally:
            sync_engine.dispose()

        mrr_eur = sum(
            self._moloni_tier_price_eur((tier or "starter")) for (tier,) in rows
        )
        return {
            "mrr_eur": round(mrr_eur, 2),
            "this_month_spend_usd": 0.0,
            "gross_margin_pct": 0.0,
            "projection_eom_usd": 0.0,
        }

    def alerts(self) -> List[Alert]:
        # Billing-domain alerts only. Infra/perf alerts come from
        # CloudWatch (separate provider, not wired yet). Returning [] is
        # truthful: there are no billing alerts because we do not yet
        # ingest the Moloni alert stream — Console renders "Sem alertas"
        # instead of fabricated data.
        return []

    def incidents(self) -> List[IncidentEntry]:
        """Return recent platform incidents from live Kubernetes Warning events.

        Groups events by (reason, namespace, base-name) so repeated firings
        of the same issue appear as a single entry. Skips pure-infra namespaces
        (kube-system, monitoring, cert-manager, etc.) that are not relevant to
        platform operators. Silently returns [] on any error so a K8s outage
        does not prevent the Console from loading.
        """
        _SKIP_NS = {
            "kube-system", "kube-public", "kube-node-lease",
            "velero", "cert-manager", "ingress-nginx",
        }
        _RELEVANT_REASONS = {
            "backoff", "crashloopbackoff", "failed", "failedmount",
            "failedscheduling", "unhealthy", "imagepullbackoff",
            "errimagepull", "oomkilled", "failedcreate",
        }
        try:
            from kubernetes import client as _k8s, config as _cfg  # type: ignore[import-not-found]
        except ImportError:
            return []
        try:
            try:
                _cfg.load_incluster_config()
            except Exception:  # noqa: BLE001
                _cfg.load_kube_config()
            v1 = _k8s.CoreV1Api()
            raw = v1.list_event_for_all_namespaces(field_selector="type=Warning").items
        except Exception:  # noqa: BLE001
            return []

        since = datetime.now(timezone.utc) - timedelta(days=30)
        import re
        _numeric_suffix = re.compile(r"-\d+$")

        # Group: (reason, namespace, base-name) → latest event + first seen
        groups: Dict[tuple, dict] = {}
        for ev in raw:
            ns = getattr(getattr(ev, "involved_object", None), "namespace", None) or ""
            if ns in _SKIP_NS:
                continue
            reason = (ev.reason or "").lower()
            if not any(r in reason for r in _RELEVANT_REASONS):
                continue
            ts = ev.last_timestamp or ev.event_time or ev.first_timestamp
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < since:
                continue
            name = getattr(getattr(ev, "involved_object", None), "name", "") or ""
            base_name = _numeric_suffix.sub("", name)
            key = (ev.reason or "", ns, base_name)
            entry = groups.get(key)
            if entry is None or ts > entry["last_ts"]:
                groups[key] = {
                    "ts": ev.first_timestamp or ts,
                    "last_ts": ts,
                    "message": (ev.message or "")[:120],
                    "ns": ns,
                    "base_name": base_name,
                    "reason": ev.reason or "",
                    "count": ev.count or 1,
                }

        out: List[IncidentEntry] = []
        for (reason, ns, base_name), g in sorted(
            groups.items(), key=lambda x: x[1]["last_ts"], reverse=True
        )[:20]:
            severity = (
                "critical" if reason.lower() in {"oomkilled", "crashloopbackoff"}
                else "warning"
            )
            first_ts = g["ts"]
            if first_ts and first_ts.tzinfo is None:
                first_ts = first_ts.replace(tzinfo=timezone.utc)
            out.append(IncidentEntry(
                id=f"k8s-{ns}-{base_name}-{reason}",
                severity=severity,
                title=f"{reason}: {base_name}" + (f" (×{g['count']})" if g["count"] > 1 else ""),
                started_at=first_ts.isoformat() if first_ts else g["last_ts"].isoformat(),
                resolved_at=None,
                affected_tenants=[],
            ))
        return out


# ── Prometheus activity ────────────────────────────────────────────


class PrometheusActivityProvider:
    """Real ``ActivityProvider`` backed by a Prometheus HTTP API.

    Required env vars:
        PROMETHEUS_URL                  — base URL, e.g.
                                          http://prometheus.monitoring:9090
        PROMETHEUS_QUERY_PLATFORM_24H   — optional override; default
                                          uses the BE request counter
        PROMETHEUS_QUERY_TENANT_7D      — optional override
        PROMETHEUS_QUERY_TOP_TENANTS    — optional override

    The default queries assume the BE app exposes
    ``sky_ai_requests_total{tenant="<slug>"}`` (emitted by src/ai/metrics.py).
    Override via env vars if needed.

    Network errors surface as ``TelemetryUnavailable`` — the Console
    catches that and renders a 503 banner.
    """

    DEFAULT_PLATFORM_24H = (
        'sum by (tenant) (rate(sky_ai_requests_total{tenant!=""}[5m]))'
    )
    DEFAULT_TENANT_7D = (
        'sum(rate(sky_ai_requests_total{tenant="__SLUG__"}[1h]))'
    )
    DEFAULT_TOP_TENANTS = (
        'topk(10, sum by (tenant) (increase(sky_ai_requests_total{tenant!=""}[24h])))'
    )

    def __init__(self) -> None:
        self._base = (os.getenv("PROMETHEUS_URL") or "").rstrip("/")
        self._timeout = int(os.getenv("PROMETHEUS_TIMEOUT_SECS", "10"))

    def _query_range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> List[Dict[str, Any]]:
        if not self._base:
            raise TelemetryUnavailable(
                "PROMETHEUS_URL env var required to enable real activity"
            )
        try:
            import requests  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TelemetryUnavailable("requests not installed") from exc
        try:
            r = requests.get(
                f"{self._base}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "step": step_seconds,
                },
                timeout=self._timeout,
            )
            r.raise_for_status()
            body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(f"Prometheus query failed: {exc}") from exc
        if body.get("status") != "success":
            raise TelemetryUnavailable(
                f"Prometheus error: {body.get('errorType')}: {body.get('error')}"
            )
        return body.get("data", {}).get("result", []) or []

    def _query_instant(self, query: str) -> List[Dict[str, Any]]:
        if not self._base:
            raise TelemetryUnavailable("PROMETHEUS_URL env var required")
        try:
            import requests  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TelemetryUnavailable("requests not installed") from exc
        try:
            r = requests.get(
                f"{self._base}/api/v1/query",
                params={"query": query},
                timeout=self._timeout,
            )
            r.raise_for_status()
            body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(f"Prometheus query failed: {exc}") from exc
        return body.get("data", {}).get("result", []) or []

    def platform_activity_24h(
        self, tenant_slugs: Sequence[str]
    ) -> List[TimeseriesPoint]:
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=24)
        query = os.getenv(
            "PROMETHEUS_QUERY_PLATFORM_24H", self.DEFAULT_PLATFORM_24H
        )
        series = self._query_range(query, start, end, step_seconds=3600)
        wanted = set(tenant_slugs)
        out: List[TimeseriesPoint] = []
        for ser in series:
            slug = ser.get("metric", {}).get("tenant", "")
            if wanted and slug not in wanted:
                continue
            for ts, val in ser.get("values", []):
                try:
                    bucket = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    out.append(
                        TimeseriesPoint(
                            t=bucket.isoformat().replace("+00:00", "Z"),
                            value=round(float(val), 2),
                            label=slug,
                        )
                    )
                except (ValueError, TypeError):
                    continue
        return out

    def tenant_activity_7d(self, slug: str) -> List[TimeseriesPoint]:
        end = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = end - timedelta(days=7)
        query_template = os.getenv(
            "PROMETHEUS_QUERY_TENANT_7D", self.DEFAULT_TENANT_7D
        )
        query = query_template.replace("__SLUG__", slug)
        series = self._query_range(query, start, end, step_seconds=86400)
        out: List[TimeseriesPoint] = []
        for ser in series:
            for ts, val in ser.get("values", []):
                try:
                    bucket = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    out.append(
                        TimeseriesPoint(
                            t=bucket.isoformat().replace("+00:00", "Z"),
                            value=round(float(val), 0),
                        )
                    )
                except (ValueError, TypeError):
                    continue
        return out

    def top_tenants_by_queries(self) -> List[Dict[str, Any]]:
        query = os.getenv(
            "PROMETHEUS_QUERY_TOP_TENANTS", self.DEFAULT_TOP_TENANTS
        )
        series = self._query_instant(query)
        rows: List[Dict[str, Any]] = []
        for ser in series:
            slug = ser.get("metric", {}).get("tenant", "")
            val_pair = ser.get("value")
            if not slug or not val_pair:
                continue
            try:
                value = float(val_pair[1])
            except (ValueError, TypeError, IndexError):
                continue
            rows.append({"slug": slug, "queries_24h": round(value, 0)})
        rows.sort(key=lambda r: r.get("queries_24h", 0), reverse=True)
        return rows


__all__ = [
    "AwsCostProvider",
    "KubernetesInfraProvider",
    "MoloniBillingProvider",
    "PrometheusActivityProvider",
]
