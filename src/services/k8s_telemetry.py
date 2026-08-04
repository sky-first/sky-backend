"""Real Kubernetes-backed telemetry for the Internal Console.

This provider ships behind ``K8S_TELEMETRY_ENABLED`` (and is only wired
in when ``CONSOLE_MOCK_INFRA=false``). It reads live pod state from the
cluster the backend pod is running in, using:

* ``load_incluster_config()`` when the pod has an IRSA-bound service
  account (production / staging on EKS).
* ``load_kube_config()`` as a fallback for local development against
  the SSM-tunnel kubeconfig (``~/.kube/stg-tunnel.yaml``).

The provider exposes two coroutines that match the shapes used by the
Console routes — ``PlatformHealthSnapshot`` and ``TenantHealthSnapshot``
— plus thin synchronous adapters (`platform_health()` /
`tenant_health()`) so it can drop into the existing
``InfraProvider`` Protocol in ``console_telemetry.py`` without
rewriting any route.

Caching: each call is memoised for ``K8S_TELEMETRY_CACHE_TTL_SECONDS``
(default 30 s) in a process-local TTL cache. The Console UI polls
every ~10 s; without this cache a single open Console tab would burn
~6 list-pods/min against kube-apiserver per replica.

Failure modes are converted to ``TelemetryUnavailable`` so the Console
routes surface a clean 503 — the API does not silently fall back to
mocks in production.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.config.settings import settings
from src.services.console_telemetry import (
    ClusterNode,
    PlatformHealth,
    PodInfo,
    TelemetryUnavailable,
    TenantHealth,
)

logger = logging.getLogger(__name__)


# ── Data shapes ────────────────────────────────────────────────────


@dataclass
class PlatformHealthSnapshot:
    """Cluster-wide pod health snapshot.

    The Console route ``GET /api/console/v1/dashboard/health`` consumes
    the legacy ``PlatformHealth`` dataclass; this richer snapshot is
    the source of truth and is mapped down to ``PlatformHealth`` by
    ``to_platform_health()``. We keep both because the snapshot also
    exposes ``pods_total`` and ``pods_unhealthy_last_24h`` which the
    forthcoming UI cards need.
    """

    pods_total: int
    pods_running: int
    pods_pending: int
    pods_crashlooping: int
    pods_unhealthy_last_24h: int
    namespaces_scanned: List[str] = field(default_factory=list)
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Prometheus-sourced; 0.0 when Prometheus is unavailable
    api_uptime_pct: float = 0.0
    api_latency_p95_ms: float = 0.0
    api_error_rate_pct: float = 0.0
    # PostgreSQL pg_stat_activity; 0 when DB is unreachable
    db_connections_used: int = 0
    db_connections_max: int = 0

    def to_platform_health(self) -> PlatformHealth:
        """Project onto the legacy ``PlatformHealth`` shape so the
        existing Console route keeps working."""
        return PlatformHealth(
            api_uptime_pct=self.api_uptime_pct,
            api_latency_p95_ms=int(self.api_latency_p95_ms),
            api_error_rate_pct=self.api_error_rate_pct,
            pods_running=self.pods_running,
            pods_pending=self.pods_pending,
            pods_crashlooping=self.pods_crashlooping,
            db_connections_used=self.db_connections_used,
            db_connections_max=self.db_connections_max,
            last_incident=None,
        )


@dataclass
class TenantHealthSnapshot:
    """Per-tenant pod health snapshot.

    ``namespaces`` lists every namespace actually queried for this
    tenant (stg + prd by default). ``pods`` is the union of pods seen
    across those namespaces, normalised onto the existing ``PodInfo``
    dataclass for backward compatibility with the Console UI table.
    """

    slug: str
    namespaces: List[str]
    pods: List[PodInfo]
    pods_total: int
    pods_running: int
    pods_pending: int
    pods_crashlooping: int
    pods_unhealthy_last_24h: int
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_tenant_health(self) -> TenantHealth:
        return TenantHealth(
            pods=self.pods,
            last_deploy_at=self.collected_at.isoformat(),
            last_deploy_sha="—",
            argocd_url=f"https://argocd.skyfirstlabs.com/applications/{self.slug}-prd",
            grafana_url=(
                f"https://grafana.skyfirstlabs.com/d/tenant/{self.slug}"
                f"?var-tenant={self.slug}"
            ),
        )


# ── TTL cache ──────────────────────────────────────────────────────


class _TTLCache:
    """Thread-safe single-process TTL cache.

    Keyed by ``(method, *args)`` tuples. Stores ``(expires_at, value)``.
    We use a plain ``threading.Lock`` rather than asyncio primitives
    because the kubernetes-client API is sync; the async wrappers run
    it through ``asyncio.to_thread`` so multiple async callers can
    legitimately race the cache.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(1, int(ttl_seconds))
        self._lock = threading.Lock()
        self._store: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Tuple[Any, ...], value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ── Provider ───────────────────────────────────────────────────────


class KubernetesTelemetryProvider:
    """Live Kubernetes-backed telemetry provider.

    Construction is cheap (no API calls); the kube client is lazily
    initialised on first use via ``_ensure_client()`` so that importing
    this module does not fail in unit tests that never touch the
    cluster.

    The provider is intended to be a singleton per process — see
    ``get_provider()`` below. Multiple callers share the same client
    object and the same TTL cache.
    """

    # Status strings exposed on PodInfo. We normalise CrashLoopBackOff
    # to its own bucket because the platform UI shows it as a distinct
    # red badge — Kubernetes itself reports phase=Running with the
    # container in waiting state, which is misleading at a glance.
    STATUS_RUNNING = "running"
    STATUS_PENDING = "pending"
    STATUS_CRASHLOOPING = "crashlooping"
    STATUS_UNKNOWN = "unknown"

    def __init__(
        self,
        *,
        cache_ttl_seconds: Optional[int] = None,
        namespace_template: Optional[str] = None,
        platform_namespaces: Optional[Sequence[str]] = None,
        core_v1_api: Any = None,
    ) -> None:
        # Cache TTL defaults to the settings value but is overridable
        # from tests so they don't have to wait 30s between assertions.
        ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.K8S_TELEMETRY_CACHE_TTL_SECONDS
        )
        self._cache = _TTLCache(ttl)
        self._namespace_template = (
            namespace_template
            if namespace_template is not None
            else settings.K8S_TELEMETRY_NAMESPACE_TEMPLATE
        )
        # ``platform_namespaces`` can be ``None`` (scan all), an empty
        # list (also scan all — we treat empty as "no allow-list"),
        # or a non-empty list (only scan those).
        if platform_namespaces is not None:
            self._platform_namespaces: List[str] = [
                n.strip() for n in platform_namespaces if n.strip()
            ]
        else:
            raw = (settings.K8S_TELEMETRY_NAMESPACES or "").strip()
            self._platform_namespaces = (
                [n.strip() for n in raw.split(",") if n.strip()] if raw else []
            )
        # Allow tests to inject a fully-mocked CoreV1Api so they don't
        # need to monkeypatch the kubernetes module.
        self._core_v1 = core_v1_api
        self._init_tried = core_v1_api is not None
        self._init_error: Optional[str] = None

    # ── lifecycle ────────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        if self._core_v1 is not None:
            return self._core_v1
        if self._init_tried and self._init_error:
            # Re-raise the same error so each call gets a 503 rather
            # than a one-off success after a transient failure.
            raise TelemetryUnavailable(self._init_error)
        self._init_tried = True
        try:
            from kubernetes import client, config  # type: ignore[import-not-found]
        except ImportError as exc:
            self._init_error = (
                "kubernetes-client not installed — add `kubernetes==31.0.0` "
                "to requirements.txt"
            )
            raise TelemetryUnavailable(self._init_error) from exc

        loaded_from = None
        # Prefer in-cluster config: the IRSA-bound service account on
        # sky-be already has the right token mounted at
        # /var/run/secrets/kubernetes.io/serviceaccount/.
        try:
            config.load_incluster_config()
            loaded_from = "incluster"
        except Exception as in_cluster_exc:  # noqa: BLE001
            try:
                config.load_kube_config()
                loaded_from = "kube_config"
            except Exception as kube_cfg_exc:  # noqa: BLE001
                self._init_error = (
                    "Could not load Kubernetes config — neither "
                    "in-cluster ({}) nor kube-config ({}) were usable.".format(
                        str(in_cluster_exc)[:120],
                        str(kube_cfg_exc)[:120],
                    )
                )
                raise TelemetryUnavailable(self._init_error) from kube_cfg_exc

        logger.info("k8s_telemetry_config_loaded", extra={"source": loaded_from})
        try:
            self._core_v1 = client.CoreV1Api()
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"CoreV1Api init failed: {exc}"
            raise TelemetryUnavailable(self._init_error) from exc
        return self._core_v1

    # ── pod classification ───────────────────────────────────────

    @classmethod
    def _classify_pod(cls, pod: Any) -> str:
        """Return one of running/pending/crashlooping/unknown.

        CrashLoopBackOff wins over phase: Kubernetes reports a pod as
        ``Running`` even when its containers are in waiting state, and
        the operator dashboard needs the bad-state badge to win.
        """
        status = getattr(pod, "status", None)
        if status is None:
            return cls.STATUS_UNKNOWN
        for cs in getattr(status, "container_statuses", None) or []:
            state = getattr(cs, "state", None)
            waiting = getattr(state, "waiting", None) if state else None
            reason = (getattr(waiting, "reason", "") or "") if waiting else ""
            if reason.lower() == "crashloopbackoff":
                return cls.STATUS_CRASHLOOPING
        phase = (getattr(status, "phase", "") or "").lower()
        if phase == "running":
            return cls.STATUS_RUNNING
        if phase == "pending":
            return cls.STATUS_PENDING
        return cls.STATUS_UNKNOWN

    # ── core listing ─────────────────────────────────────────────

    def _list_namespaced_pods(self, namespace: str) -> List[Any]:
        """Wrapper around ``CoreV1Api.list_namespaced_pod`` that converts
        kubernetes exceptions to ``TelemetryUnavailable``."""
        client = self._ensure_client()
        cache_key = ("list_ns_pods", namespace)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            resp = client.list_namespaced_pod(namespace)
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"list_namespaced_pod({namespace!r}) failed: {exc}"
            ) from exc
        items = list(getattr(resp, "items", []) or [])
        self._cache.set(cache_key, items)
        return items

    def _list_all_pods(self) -> List[Any]:
        client = self._ensure_client()
        cache_key = ("list_all_pods",)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            resp = client.list_pod_for_all_namespaces()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"list_pod_for_all_namespaces failed: {exc}"
            ) from exc
        items = list(getattr(resp, "items", []) or [])
        self._cache.set(cache_key, items)
        return items

    def _list_namespace_events(self, namespace: str) -> List[Any]:
        """List Pod-kind events in a namespace, cached.

        Errors here are logged but downgraded to ``[]`` — the unhealthy
        count gracefully degrades to 0 if the SA doesn't have list-events
        permission, rather than 503-ing the whole route.
        """
        client = self._ensure_client()
        cache_key = ("list_ns_events", namespace)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            resp = client.list_namespaced_event(namespace)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "k8s_telemetry_events_unavailable",
                extra={"namespace": namespace, "error": str(exc)[:200]},
            )
            self._cache.set(cache_key, [])
            return []
        items = list(getattr(resp, "items", []) or [])
        self._cache.set(cache_key, items)
        return items

    # ── unhealthy-events scan ────────────────────────────────────

    @staticmethod
    def _is_unhealthy_event(ev: Any, since: datetime) -> bool:
        """Return True for pod-kind Warning events that look operationally
        relevant and that landed within the lookback window."""
        if (getattr(ev, "type", "") or "").lower() != "warning":
            return False
        involved = getattr(ev, "involved_object", None)
        kind = getattr(involved, "kind", "") if involved else ""
        if kind and kind.lower() != "pod":
            return False
        reason = (getattr(ev, "reason", "") or "").lower()
        relevant = {
            "backoff",
            "crashloopbackoff",
            "failed",
            "failedmount",
            "failedscheduling",
            "unhealthy",
            "imagepullbackoff",
            "errimagepull",
            "oomkilled",
        }
        if not any(r in reason for r in relevant):
            return False
        ts = (
            getattr(ev, "last_timestamp", None)
            or getattr(ev, "event_time", None)
            or getattr(ev, "first_timestamp", None)
        )
        if ts is None:
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts >= since

    def _count_unhealthy_pods_last_24h(self, namespaces: Sequence[str]) -> int:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        unhealthy_pod_keys: set = set()
        for ns in namespaces:
            for ev in self._list_namespace_events(ns):
                if not self._is_unhealthy_event(ev, since):
                    continue
                involved = getattr(ev, "involved_object", None)
                name = getattr(involved, "name", None) if involved else None
                if name:
                    unhealthy_pod_keys.add((ns, name))
        return len(unhealthy_pod_keys)

    # ── metrics-server helpers ───────────────────────────────────

    @staticmethod
    def _parse_cpu_millicores(raw: Any) -> float:
        """Parse a Kubernetes ``cpu`` quantity into millicores (mCPU).

        metrics-server reports values like ``"123m"`` (millicore),
        ``"1"`` (one whole core) or ``"500u"`` (micro). We project
        everything to mCPU so the percentage maths is consistent.
        Returns 0.0 on parse error rather than raising — telemetry
        must never block a request.
        """
        if raw is None:
            return 0.0
        s = str(raw).strip()
        if not s:
            return 0.0
        try:
            if s.endswith("m"):
                return float(s[:-1])
            if s.endswith("u"):
                return float(s[:-1]) / 1000.0
            if s.endswith("n"):
                return float(s[:-1]) / 1_000_000.0
            # Bare number = whole cores.
            return float(s) * 1000.0
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_memory_bytes(raw: Any) -> float:
        """Parse a Kubernetes ``memory`` quantity into bytes.

        Accepts the binary suffixes (``Ki/Mi/Gi/Ti``) plus the
        decimal ones (``K/M/G/T``). Anything else returns 0.
        """
        if raw is None:
            return 0.0
        s = str(raw).strip()
        if not s:
            return 0.0
        units = {
            "Ki": 1024,
            "Mi": 1024 ** 2,
            "Gi": 1024 ** 3,
            "Ti": 1024 ** 4,
            "K": 1000,
            "M": 1000 ** 2,
            "G": 1000 ** 3,
            "T": 1000 ** 4,
        }
        for suffix, mult in units.items():
            if s.endswith(suffix):
                try:
                    return float(s[: -len(suffix)]) * mult
                except ValueError:
                    return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _fetch_pod_metrics(self, namespace: str) -> Dict[str, tuple[float, float]]:
        """Return ``{pod_name: (cpu_millicore, memory_bytes)}`` for the
        namespace by hitting ``metrics.k8s.io/v1beta1/namespaces/{ns}/pods``.

        Empty dict on any failure (metrics-server not installed, RBAC
        missing, etc.) so telemetry degrades gracefully — Console just
        shows 0% rather than 503-ing.
        """
        try:
            from kubernetes import client  # type: ignore[import-not-found]
        except ImportError:
            return {}
        try:
            api = client.CustomObjectsApi()
            resp = api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "k8s_telemetry_metrics_query_failed",
                extra={"namespace": namespace, "error": str(exc)[:200]},
            )
            return {}
        out: Dict[str, tuple[float, float]] = {}
        for entry in (resp or {}).get("items", []) or []:
            name = (entry.get("metadata") or {}).get("name")
            if not name:
                continue
            cpu_m = 0.0
            mem_b = 0.0
            for container in entry.get("containers", []) or []:
                usage = container.get("usage") or {}
                cpu_m += self._parse_cpu_millicores(usage.get("cpu"))
                mem_b += self._parse_memory_bytes(usage.get("memory"))
            out[name] = (cpu_m, mem_b)
        return out

    @staticmethod
    def _fetch_db_connections() -> tuple[int, int]:
        """Return ``(used, max)`` from ``pg_stat_activity``.

        Uses a one-shot sync engine so it can be called from a sync
        context without an event loop. Returns ``(0, 0)`` on any error
        so a DB hiccup never blocks the health endpoint.
        """
        db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        if not db_url:
            return 0, 0
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool
            # NullPool: open one connection, run queries, close immediately.
            # A pooled engine would leave idle connections in pg_stat_activity
            # after every health-check poll, causing the count to drift upward.
            engine = create_engine(
                db_url, poolclass=NullPool, connect_args={"sslmode": "require"}
            )
            try:
                with engine.connect() as conn:
                    used = int(conn.execute(text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database()"
                    )).scalar() or 0)
                    max_conn = int(conn.execute(text(
                        "SELECT setting FROM pg_settings WHERE name = 'max_connections'"
                    )).scalar() or 0)
                    return used, max_conn
            finally:
                engine.dispose()
        except Exception:  # noqa: BLE001
            return 0, 0

    def _prometheus_scalar(self, query: str, default: float = 0.0) -> float:
        """Hit the Prometheus instant-query API and return the first scalar result.

        Returns *default* on any failure: no PROMETHEUS_URL env var, network
        error, no series returned, or NaN/Inf from the query engine.
        """
        prom_url = os.getenv("PROMETHEUS_URL", "").rstrip("/")
        if not prom_url:
            return default
        try:
            url = f"{prom_url}/api/v1/query?query={urllib.parse.quote(query)}"
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read())
            results = data.get("data", {}).get("result", [])
            if not results:
                return default
            val = float(results[0]["value"][1])
            return default if (math.isnan(val) or math.isinf(val)) else val
        except Exception:
            return default

    @staticmethod
    def _pod_limits(pod: Any) -> tuple[float, float]:
        """Return ``(cpu_limit_mCPU, memory_limit_bytes)`` for the pod
        (summed across containers). Falls back to ``requests`` when
        ``limits`` are not set on a container — same intent as the
        Kyverno ``check-resource-limits`` policy on staging."""
        spec = getattr(pod, "spec", None)
        if spec is None:
            return 0.0, 0.0
        cpu_m = 0.0
        mem_b = 0.0
        for c in getattr(spec, "containers", None) or []:
            resources = getattr(c, "resources", None)
            limits = (
                getattr(resources, "limits", None) if resources else None
            ) or {}
            requests = (
                getattr(resources, "requests", None) if resources else None
            ) or {}
            cpu_raw = limits.get("cpu") or requests.get("cpu")
            mem_raw = limits.get("memory") or requests.get("memory")
            cpu_m += KubernetesTelemetryProvider._parse_cpu_millicores(cpu_raw)
            mem_b += KubernetesTelemetryProvider._parse_memory_bytes(mem_raw)
        return cpu_m, mem_b

    # ── pod → PodInfo adapter ────────────────────────────────────

    @classmethod
    def _pod_to_info(
        cls,
        pod: Any,
        pod_metrics: Optional[Dict[str, tuple[float, float]]] = None,
    ) -> PodInfo:
        metadata = getattr(pod, "metadata", None)
        spec = getattr(pod, "spec", None)
        status = getattr(pod, "status", None)

        name = getattr(metadata, "name", "") if metadata else ""
        namespace = getattr(metadata, "namespace", "") if metadata else ""
        labels = (getattr(metadata, "labels", None) or {}) if metadata else {}
        component = (
            labels.get("app.kubernetes.io/component")
            or labels.get("component")
            or labels.get("app.kubernetes.io/name")
            or labels.get("app")
            or "unknown"
        )

        restarts = 0
        for cs in (getattr(status, "container_statuses", None) or []) if status else []:
            restarts += int(getattr(cs, "restart_count", 0) or 0)

        first_container = None
        containers = (getattr(spec, "containers", None) or []) if spec else []
        if containers:
            first_container = containers[0]
        image = getattr(first_container, "image", "") or "" if first_container else ""
        image_sha = "—"
        if "@sha256:" in image:
            image_sha = image.rsplit("@sha256:", 1)[-1][:12]
        elif ":" in image:
            image_sha = image.rsplit(":", 1)[-1][:12]

        age_hours = 0
        creation_ts = (
            getattr(metadata, "creation_timestamp", None) if metadata else None
        )
        if creation_ts is not None:
            if creation_ts.tzinfo is None:
                creation_ts = creation_ts.replace(tzinfo=timezone.utc)
            age_hours = int(
                (datetime.now(timezone.utc) - creation_ts).total_seconds() / 3600
            )

        cpu_pct = 0.0
        memory_pct = 0.0
        if pod_metrics is not None and name in pod_metrics:
            used_cpu_m, used_mem_b = pod_metrics[name]
            cpu_limit_m, mem_limit_b = cls._pod_limits(pod)
            if cpu_limit_m > 0:
                cpu_pct = round(100.0 * used_cpu_m / cpu_limit_m, 1)
            if mem_limit_b > 0:
                memory_pct = round(100.0 * used_mem_b / mem_limit_b, 1)

        return PodInfo(
            name=name,
            namespace=namespace,
            component=component,
            status=cls._classify_pod(pod),
            restarts=restarts,
            cpu_pct=cpu_pct,
            memory_pct=memory_pct,
            age_hours=age_hours,
            image_sha=image_sha,
        )

    # ── public sync API ──────────────────────────────────────────

    def get_platform_health_sync(self) -> PlatformHealthSnapshot:
        # If a non-empty allow-list is configured, sum across each
        # namespace; otherwise issue a single cluster-wide list call
        # (much cheaper than fan-out).
        if self._platform_namespaces:
            pods: List[Any] = []
            for ns in self._platform_namespaces:
                pods.extend(self._list_namespaced_pods(ns))
            namespaces_scanned = list(self._platform_namespaces)
        else:
            pods = self._list_all_pods()
            namespaces_scanned = sorted(
                {
                    getattr(getattr(p, "metadata", None), "namespace", "") or ""
                    for p in pods
                }
                - {""}
            )

        running = pending = crash = 0
        for p in pods:
            kind = self._classify_pod(p)
            if kind == self.STATUS_RUNNING:
                running += 1
            elif kind == self.STATUS_PENDING:
                pending += 1
            elif kind == self.STATUS_CRASHLOOPING:
                crash += 1

        unhealthy_24h = self._count_unhealthy_pods_last_24h(namespaces_scanned)

        uptime_pct = self._prometheus_scalar(
            'avg_over_time(up{job="sky-api"}[30d]) * 100'
        )
        latency_p95_ms = self._prometheus_scalar(
            'histogram_quantile(0.95,'
            ' sum by(le)(rate(http_request_duration_seconds_bucket{job="sky-api"}[5m])))'
            ' * 1000'
        )
        error_rate_pct = self._prometheus_scalar(
            'sum(rate(http_requests_total{job="sky-api",status="5xx"}[5m]))'
            ' / sum(rate(http_requests_total{job="sky-api"}[5m])) * 100'
        )

        db_used, db_max = self._fetch_db_connections()

        return PlatformHealthSnapshot(
            pods_total=len(pods),
            pods_running=running,
            pods_pending=pending,
            pods_crashlooping=crash,
            pods_unhealthy_last_24h=unhealthy_24h,
            namespaces_scanned=namespaces_scanned,
            api_uptime_pct=round(uptime_pct, 2),
            api_latency_p95_ms=round(latency_p95_ms, 1),
            api_error_rate_pct=round(error_rate_pct, 3),
            db_connections_used=db_used,
            db_connections_max=db_max,
        )

    def get_tenant_health_sync(self, slug: str) -> TenantHealthSnapshot:
        slug_clean = (slug or "").strip().lower()
        if not slug_clean:
            raise TelemetryUnavailable("tenant slug is required")
        namespaces = [
            self._namespace_template.format(slug=slug_clean, env=env)
            for env in ("stg", "prd")
        ]
        pods: List[Any] = []
        for ns in namespaces:
            # Per-namespace failures are swallowed: a tenant may legitimately
            # not have a staging deployment yet, and the API returns 404 for
            # the namespace. We log the issue and keep going so we still
            # surface what we *do* have.
            try:
                pods.extend(self._list_namespaced_pods(ns))
            except TelemetryUnavailable as exc:
                logger.info(
                    "k8s_telemetry_tenant_ns_unavailable",
                    extra={"slug": slug_clean, "namespace": ns, "error": str(exc)[:200]},
                )

        # Pull metrics-server stats per namespace in one shot so the
        # per-pod adapter can fill cpu_pct / memory_pct without extra
        # round-trips. Missing metrics (e.g. server still warming up
        # for a brand-new pod) degrade gracefully to 0%.
        metrics_by_ns: Dict[str, Dict[str, tuple[float, float]]] = {
            ns: self._fetch_pod_metrics(ns) for ns in namespaces
        }

        running = pending = crash = 0
        infos: List[PodInfo] = []
        for p in pods:
            ns = getattr(getattr(p, "metadata", None), "namespace", "") or ""
            info = self._pod_to_info(p, pod_metrics=metrics_by_ns.get(ns))
            infos.append(info)
            if info.status == self.STATUS_RUNNING:
                running += 1
            elif info.status == self.STATUS_PENDING:
                pending += 1
            elif info.status == self.STATUS_CRASHLOOPING:
                crash += 1

        unhealthy_24h = self._count_unhealthy_pods_last_24h(namespaces)

        return TenantHealthSnapshot(
            slug=slug_clean,
            namespaces=namespaces,
            pods=infos,
            pods_total=len(infos),
            pods_running=running,
            pods_pending=pending,
            pods_crashlooping=crash,
            pods_unhealthy_last_24h=unhealthy_24h,
        )

    # ── public async API (preferred from routes / Celery) ──────

    async def get_platform_health(self) -> PlatformHealthSnapshot:
        return await asyncio.to_thread(self.get_platform_health_sync)

    async def get_tenant_health(self, slug: str) -> TenantHealthSnapshot:
        return await asyncio.to_thread(self.get_tenant_health_sync, slug)

    # ── ``InfraProvider`` Protocol adapters ──────────────────────

    def platform_health(self) -> PlatformHealth:
        return self.get_platform_health_sync().to_platform_health()

    def tenant_health(self, slug: str) -> TenantHealth:
        return self.get_tenant_health_sync(slug).to_tenant_health()

    def cluster_nodes(self) -> List[ClusterNode]:
        core_v1 = self._ensure_client()
        try:
            nodes = core_v1.list_node().items
        except Exception as exc:
            raise TelemetryUnavailable(
                f"cluster_nodes: list_node failed: {exc}"
            ) from exc

        # Fetch node-level usage from metrics-server (graceful fallback to {})
        node_metrics: Dict[str, tuple[float, float]] = {}
        try:
            from kubernetes import client as _k8s_client  # type: ignore[import-not-found]
            custom = _k8s_client.CustomObjectsApi()
            resp = custom.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes")
            for item in (resp or {}).get("items", []) or []:
                name = (item.get("metadata") or {}).get("name", "")
                usage = item.get("usage") or {}
                if name:
                    node_metrics[name] = (
                        self._parse_cpu_millicores(usage.get("cpu")),
                        self._parse_memory_bytes(usage.get("memory")),
                    )
        except Exception:  # noqa: BLE001
            pass

        out: List[ClusterNode] = []
        for n in nodes:
            labels = n.metadata.labels or {}
            # sky-pool label (apps/infra) is the most informative role;
            # fall back to standard node-role.kubernetes.io/* labels.
            role = labels.get("sky-pool", "worker")
            if role == "worker":
                for k in labels:
                    if k.startswith("node-role.kubernetes.io/"):
                        role = k.split("/", 1)[1] or role
                        break
            status = "not_ready"
            for cond in (n.status.conditions or []):
                if cond.type == "Ready":
                    status = "ready" if cond.status == "True" else "not_ready"
                    break
            pods_count = 0
            try:
                pods_count = len(
                    core_v1.list_pod_for_all_namespaces(
                        field_selector=f"spec.nodeName={n.metadata.name}"
                    ).items
                )
            except Exception:  # noqa: BLE001
                pass

            cpu_pct = 0.0
            memory_pct = 0.0
            node_name = n.metadata.name
            if node_name in node_metrics:
                used_cpu_m, used_mem_b = node_metrics[node_name]
                capacity = n.status.capacity or {}
                cap_cpu_m = self._parse_cpu_millicores(capacity.get("cpu"))
                cap_mem_b = self._parse_memory_bytes(capacity.get("memory"))
                if cap_cpu_m > 0:
                    cpu_pct = round(100.0 * used_cpu_m / cap_cpu_m, 1)
                if cap_mem_b > 0:
                    memory_pct = round(100.0 * used_mem_b / cap_mem_b, 1)

            out.append(ClusterNode(
                name=node_name,
                cluster="stg",
                role=role,
                cpu_pct=cpu_pct,
                memory_pct=memory_pct,
                pods_count=pods_count,
                status=status,
            ))
        return out

    # ── test/operator helpers ────────────────────────────────────

    def invalidate_cache(self) -> None:
        """Drop all cached entries. Useful from a manual `/console/refresh`
        endpoint or from tests asserting two distinct API calls."""
        self._cache.clear()


# ── singleton accessor ─────────────────────────────────────────────


_provider_singleton: Optional[KubernetesTelemetryProvider] = None
_provider_lock = threading.Lock()


def get_provider() -> KubernetesTelemetryProvider:
    """Return the process-wide ``KubernetesTelemetryProvider`` instance.

    Constructed lazily on first call so that importing this module from
    a unit test environment never touches the cluster.
    """
    global _provider_singleton
    with _provider_lock:
        if _provider_singleton is None:
            _provider_singleton = KubernetesTelemetryProvider()
        return _provider_singleton


def reset_provider() -> None:
    """Reset the singleton — only for tests."""
    global _provider_singleton
    with _provider_lock:
        _provider_singleton = None


__all__ = [
    "KubernetesTelemetryProvider",
    "PlatformHealthSnapshot",
    "TenantHealthSnapshot",
    "get_provider",
    "reset_provider",
]
