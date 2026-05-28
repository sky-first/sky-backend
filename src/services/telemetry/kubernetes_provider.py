"""Improved Kubernetes telemetry provider with real CPU/memory metrics
and live log streaming via the kubernetes-client library.

This module exposes:
  - ``KubernetesInfraProvider`` — drop-in replacement that fills in
    ``cpu_pct`` / ``memory_pct`` from the metrics-server, and reads
    ``db_connections_used`` / ``db_connections_max`` from the
    ``sky-db-pool-config`` ConfigMap.
  - ``KubernetesLogStreamer`` — streams real pod logs line-by-line via
    ``kubernetes.stream`` so the WebSocket endpoint can forward them
    to the browser.

Env vars required (same as ``console_telemetry_real.KubernetesInfraProvider``):
    KUBECONFIG_STAGING  — path to kubeconfig for the stg cluster
    KUBECONFIG_PROD     — path to kubeconfig for the prd cluster

All kubernetes errors surface as ``TelemetryUnavailable`` so callers
can return a clean 503 instead of leaking internal stack traces.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List, Optional

from src.services.console_telemetry import (
    ClusterNode,
    PlatformHealth,
    PodInfo,
    TelemetryUnavailable,
    TenantHealth,
)

logger = logging.getLogger(__name__)

# ── In-memory TTL cache ────────────────────────────────────────────

# key → (stored_at_monotonic, result)
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str, ttl: float = 30.0) -> Any:
    """Return the cached value for *key* if it is still within *ttl* seconds.

    Returns ``None`` when the key is absent or has expired.
    """
    entry = _cache.get(key)
    if entry is None:
        return None
    stored_at, value = entry
    if time.monotonic() - stored_at <= ttl:
        return value
    # Expired — evict eagerly so memory doesn't grow unboundedly.
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: Any) -> None:
    """Store *value* in the in-memory cache under *key*."""
    _cache[key] = (time.monotonic(), value)


# ── Helpers ────────────────────────────────────────────────────────


def _parse_cpu_cores(quantity: str) -> float:
    """Convert a Kubernetes CPU quantity string to fractional cores.

    Examples:
        "250m"        → 0.25
        "2"           → 2.0
        "1500m"       → 1.5
        "125286296n"  → 0.125  (nanocores — returned by metrics-server)
    """
    quantity = quantity.strip()
    if quantity.endswith("n"):
        # Nanocores: metrics-server returns values like "125286296n"
        return float(quantity[:-1]) / 1_000_000_000.0
    if quantity.endswith("m"):
        return float(quantity[:-1]) / 1000.0
    return float(quantity)


def _parse_memory_bytes(quantity: str) -> float:
    """Convert a Kubernetes memory quantity string to bytes (as float).

    Handles Ki, Mi, Gi, Ti, Pi, Ei suffixes and plain integers.
    """
    quantity = quantity.strip()
    suffixes = {
        "Ki": 1024,
        "Mi": 1024 ** 2,
        "Gi": 1024 ** 3,
        "Ti": 1024 ** 4,
        "Pi": 1024 ** 5,
        "Ei": 1024 ** 6,
        "K": 1000,
        "M": 1000 ** 2,
        "G": 1000 ** 3,
        "T": 1000 ** 4,
        "P": 1000 ** 5,
        "E": 1000 ** 6,
    }
    for suffix, multiplier in suffixes.items():
        if quantity.endswith(suffix):
            return float(quantity[: -len(suffix)]) * multiplier
    return float(quantity)


def _parse_level(line: str) -> str:
    """Infer a log level from the beginning of a log line.

    Looks for common prefixes like ``ERROR``, ``WARN``, ``WARNING``,
    ``INFO``, ``DEBUG`` (case-insensitive). Returns ``"INFO"`` if none
    is found.
    """
    stripped = line.lstrip()
    for token in ("ERROR", "WARN", "WARNING", "CRITICAL", "DEBUG", "INFO"):
        if stripped.upper().startswith(token):
            return "ERROR" if token in ("ERROR", "CRITICAL") else (
                "WARN" if token in ("WARN", "WARNING") else (
                    "DEBUG" if token == "DEBUG" else "INFO"
                )
            )
    return "INFO"


# ── Main provider ──────────────────────────────────────────────────


class KubernetesInfraProvider:
    """Real ``InfraProvider`` backed by the kubernetes-client library.

    Extends the implementation in ``console_telemetry_real`` with:

    * CPU and memory percentages via the metrics-server
      (``apis/metrics.k8s.io/v1beta1``). When the metrics-server is
      unavailable the values fall back to ``0.0`` silently.

    * ``platform_health()`` now also reads ``db_connections_used`` and
      ``db_connections_max`` from the ``sky-db-pool-config`` ConfigMap
      in the ``sky-platform`` namespace. Missing ConfigMap → 0/0.

    Required env vars:
        KUBECONFIG_STAGING  — path to kubeconfig for the stg cluster
        KUBECONFIG_PROD     — path to kubeconfig for the prd cluster

    Optional env vars:
        ARGOCD_BASE_URL     — defaults to https://argocd.skyfirstlabs.com
        GRAFANA_BASE_URL    — defaults to https://grafana.skyfirstlabs.com
    """

    # ConfigMap that stores PgBouncer / PG pool limits
    _DB_POOL_CONFIGMAP_NS = "sky-platform"
    _DB_POOL_CONFIGMAP_NAME = "sky-db-pool-config"
    _DB_POOL_USED_KEY = "connections_used"
    _DB_POOL_MAX_KEY = "connections_max"

    def __init__(self) -> None:
        self._stg_core: object = None
        self._prd_core: object = None
        self._stg_custom: object = None
        self._prd_custom: object = None
        self._tried_init: bool = False

    # ── Client bootstrap ───────────────────────────────────────────

    def _ensure_clients(self) -> None:
        if self._tried_init:
            return
        self._tried_init = True
        try:
            from kubernetes import client as k8s_client  # type: ignore[import-not-found]
            from kubernetes import config as k8s_config  # type: ignore[import-not-found]
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

        # Each cluster gets its own isolated Configuration + ApiClient so that
        # loading stg and prd kubeconfigs does not interfere via the global
        # singleton. A failed prd (e.g. expired SSO) is logged and skipped
        # without preventing stg from working.
        _any_loaded = False

        try:
            stg_cfg = k8s_client.Configuration()
            k8s_config.load_kube_config(
                config_file=stg_path, client_configuration=stg_cfg
            )
            stg_cfg.connection_pool_maxsize = 4
            stg_api = k8s_client.ApiClient(configuration=stg_cfg)
            self._stg_core = k8s_client.CoreV1Api(api_client=stg_api)
            self._stg_custom = k8s_client.CustomObjectsApi(api_client=stg_api)
            _any_loaded = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("k8s_stg_kubeconfig_failed: %s", str(exc)[:200])

        try:
            prd_cfg = k8s_client.Configuration()
            k8s_config.load_kube_config(
                config_file=prd_path, client_configuration=prd_cfg
            )
            prd_cfg.connection_pool_maxsize = 4
            prd_api = k8s_client.ApiClient(configuration=prd_cfg)
            self._prd_core = k8s_client.CoreV1Api(api_client=prd_api)
            self._prd_custom = k8s_client.CustomObjectsApi(api_client=prd_api)
            _any_loaded = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("k8s_prd_kubeconfig_failed: %s", str(exc)[:200])

        if not _any_loaded:
            raise TelemetryUnavailable(
                "Failed to load both KUBECONFIG_STAGING and KUBECONFIG_PROD"
            )

    # ── Metrics-server helpers ─────────────────────────────────────

    def _fetch_pod_metrics(
        self,
        custom_api: object,
        namespace: str,
        pod_name: str,
    ) -> tuple[float, float]:
        """Return ``(cpu_cores, memory_bytes)`` for a single pod via the
        metrics-server API. Returns ``(0.0, 0.0)`` if metrics-server is
        unavailable or the pod has no metrics yet.
        """
        try:
            resp = custom_api.get_namespaced_custom_object(  # type: ignore[union-attr]
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
                name=pod_name,
            )
            containers = resp.get("containers", [])
            total_cpu = 0.0
            total_mem = 0.0
            for c in containers:
                usage = c.get("usage", {})
                total_cpu += _parse_cpu_cores(usage.get("cpu", "0"))
                total_mem += _parse_memory_bytes(usage.get("memory", "0"))
            return total_cpu, total_mem
        except Exception:  # noqa: BLE001 — metrics-server absent or pod not scraped yet
            return 0.0, 0.0

    def _node_allocatable(
        self,
        node: object,
    ) -> tuple[float, float]:
        """Return ``(allocatable_cpu_cores, allocatable_memory_bytes)``
        from a node object. Returns ``(1.0, 1.0)`` as safe divisor fallback.
        """
        try:
            alloc = node.status.allocatable  # type: ignore[union-attr]
            cpu = _parse_cpu_cores(alloc.get("cpu", "1"))
            mem = _parse_memory_bytes(alloc.get("memory", "1Ki"))
            return max(cpu, 0.001), max(mem, 1.0)
        except Exception:  # noqa: BLE001
            return 1.0, 1.0

    def _pod_requests(
        self,
        pod: object,
    ) -> tuple[float, float]:
        """Sum resource requests across all containers in a pod.

        Returns ``(cpu_cores_requested, memory_bytes_requested)``.
        Falls back to ``(0.0, 0.0)`` on any error.
        """
        try:
            total_cpu = 0.0
            total_mem = 0.0
            for c in (pod.spec.containers or []):  # type: ignore[union-attr]
                if c.resources and c.resources.requests:
                    total_cpu += _parse_cpu_cores(
                        c.resources.requests.get("cpu", "0")
                    )
                    total_mem += _parse_memory_bytes(
                        c.resources.requests.get("memory", "0")
                    )
            return total_cpu, total_mem
        except Exception:  # noqa: BLE001
            return 0.0, 0.0

    # ── DB pool ConfigMap ──────────────────────────────────────────

    def _read_db_pool_config(self) -> tuple[int, int]:
        """Read ``db_connections_used`` / ``db_connections_max`` from the
        ``sky-db-pool-config`` ConfigMap in the ``sky-platform`` namespace.

        Returns ``(0, 0)`` when the ConfigMap does not exist or any error
        occurs — callers should treat this as "data not available".
        """
        try:
            # Use the production client — the ConfigMap lives in the
            # platform namespace which is always on the prd cluster.
            cm = self._prd_core.read_namespaced_config_map(  # type: ignore[union-attr]
                name=self._DB_POOL_CONFIGMAP_NAME,
                namespace=self._DB_POOL_CONFIGMAP_NS,
            )
            data = cm.data or {}
            used = int(data.get(self._DB_POOL_USED_KEY, "0"))
            maximum = int(data.get(self._DB_POOL_MAX_KEY, "0"))
            return used, maximum
        except Exception:  # noqa: BLE001 — ConfigMap missing or API error
            return 0, 0

    # ── InfraProvider interface ────────────────────────────────────

    def platform_health(self) -> PlatformHealth:
        """Return aggregated cluster health across stg + prd, including
        real DB pool usage from the ``sky-db-pool-config`` ConfigMap.
        """
        self._ensure_clients()
        running = pending = crash = 0
        for label, core in (("stg", self._stg_core), ("prd", self._prd_core)):
            if core is None:
                continue
            try:
                pods = core.list_pod_for_all_namespaces().items  # type: ignore[union-attr]
                for p in pods:
                    phase = (p.status.phase or "").lower()
                    if phase == "running":
                        running += 1
                    elif phase == "pending":
                        pending += 1
                    for st in (p.status.container_statuses or []):
                        if (
                            st.state
                            and st.state.waiting
                            and (st.state.waiting.reason or "").lower()
                            == "crashloopbackoff"
                        ):
                            crash += 1
                            break
            except Exception as exc:  # noqa: BLE001 — one cluster down, continue
                logger.warning("k8s_platform_health_failed cluster=%s: %s", label, str(exc)[:200])

        db_used, db_max = self._read_db_pool_config()

        return PlatformHealth(
            api_uptime_pct=0.0,        # TODO: wire Prometheus
            api_latency_p95_ms=0,      # TODO: wire Prometheus
            api_error_rate_pct=0.0,    # TODO: wire Prometheus
            pods_running=running,
            pods_pending=pending,
            pods_crashlooping=crash,
            db_connections_used=db_used,
            db_connections_max=db_max,
            last_incident=None,
        )

    def _argocd_last_deploy(self, custom: Any, slug: str) -> tuple[str, str]:
        """Return (last_deploy_at_iso, short_sha) from ArgoCD application objects.

        Looks for apps whose name starts with ``sky-*`` or ``{slug}-*``.
        Falls back to current time + '—' if ArgoCD is unavailable.
        """
        try:
            apps = custom.list_namespaced_custom_object(  # type: ignore[union-attr]
                group="argoproj.io", version="v1alpha1",
                namespace="argocd", plural="applications",
            )
            latest_ts = ""
            latest_sha = "—"
            for app in apps.get("items", []):
                name = app.get("metadata", {}).get("name", "")
                # Match platform apps: sky-*-stg-aws or {slug}-*
                if not (name.startswith("sky-") or name.startswith(f"{slug}-")):
                    continue
                op = app.get("status", {}).get("operationState", {})
                finished = op.get("finishedAt", "")
                rev = op.get("syncResult", {}).get("revision", "") or \
                      app.get("status", {}).get("sync", {}).get("revision", "")
                if finished and finished > latest_ts:
                    latest_ts = finished
                    latest_sha = rev[:12] if rev else "—"
            if latest_ts:
                return latest_ts, latest_sha
        except Exception:  # noqa: BLE001
            pass
        return datetime.now(timezone.utc).isoformat(), "—"

    def tenant_health(self, slug: str) -> TenantHealth:
        """Return pod list for the tenant, enriched with real CPU/memory
        percentages from the metrics-server when available.

        Namespace convention: tries ``{slug}-stg`` first, then falls back to
        the shared ``staging`` namespace (Sky's single-tenant platform layout
        where pods are named ``sky-{service}-stg-aws``).
        """
        cached = _cache_get(f"tenant_health:{slug}")
        if cached is not None:
            return cached
        self._ensure_clients()
        try:
            pods: List[PodInfo] = []
            last_deploy_at = datetime.now(timezone.utc).isoformat()
            last_deploy_sha = "—"
            for env_label, core, custom in (
                ("stg", self._stg_core, self._stg_custom),
                ("prd", self._prd_core, self._prd_custom),
            ):
                if core is None:
                    continue

                # Fetch last deploy from ArgoCD (only once, from stg)
                if env_label == "stg":
                    last_deploy_at, last_deploy_sha = self._argocd_last_deploy(custom, slug)

                # Try the conventional namespace first ({slug}-{env}),
                # then fall back to the shared staging namespace.
                # In Sky's single-tenant layout all pods live in "staging".
                candidates = [f"{slug}-{env_label}", "staging" if env_label == "stg" else None]
                items = []
                ns = f"{slug}-{env_label}"
                for candidate_ns in candidates:
                    if candidate_ns is None:
                        continue
                    try:
                        fetched = core.list_namespaced_pod(candidate_ns).items  # type: ignore[union-attr]
                        if candidate_ns != f"{slug}-{env_label}":
                            # Shared namespace: show all non-system pods
                            # (sky-*-stg-aws naming convention, not {slug}-*)
                            fetched = [p for p in fetched if
                                       p.metadata.labels and
                                       p.metadata.labels.get("app.kubernetes.io/instance", "").startswith("sky-")]
                        if fetched:
                            items = fetched
                            ns = candidate_ns
                            break
                    except Exception:  # noqa: BLE001
                        continue
                if not items:
                    logger.warning(
                        "tenant_health_namespace_query_failed",
                        extra={"slug": slug, "env": env_label, "error": "no namespace found"},
                    )
                    continue

                # Try to fetch node allocatable resources once per
                # namespace to compute percentage against. We look up the
                # node of the first pod to get a representative value.
                node_cpu_alloc: float = 1.0
                node_mem_alloc: float = 1.0
                _node_fetched = False

                for p in items:
                    pod_name: str = p.metadata.name

                    # Component label — prefer K8s label, fall back to
                    # deriving from the app instance name (sky-be-stg-aws → backend)
                    component: str = "unknown"
                    if p.metadata and p.metadata.labels:
                        component = (
                            p.metadata.labels.get("app.kubernetes.io/component")
                            or p.metadata.labels.get("component")
                            or ""
                        )
                    if not component or component == "unknown":
                        instance = (p.metadata.labels or {}).get(
                            "app.kubernetes.io/instance", pod_name
                        )
                        _svc_map = {
                            "sky-be": "backend", "sky-fe": "frontend",
                            "sky-ai-worker": "ai-worker", "sky-ai": "ai",
                        }
                        component = next(
                            (v for k, v in _svc_map.items() if instance.startswith(k)),
                            "unknown",
                        )

                    # Restarts
                    restarts: int = sum(
                        s.restart_count for s in (p.status.container_statuses or [])
                    )

                    # Image SHA
                    container = (
                        p.spec.containers[0]
                        if p.spec and p.spec.containers
                        else None
                    )
                    image_sha: str = "—"
                    if (
                        container
                        and container.image
                        and "@sha256:" in container.image
                    ):
                        image_sha = container.image.rsplit("@sha256:", 1)[-1][:12]

                    # Age
                    age_hours: int = 0
                    if p.metadata.creation_timestamp:
                        age_hours = int(
                            (
                                datetime.now(timezone.utc)
                                - p.metadata.creation_timestamp
                            ).total_seconds()
                            / 3600
                        )

                    # CPU / memory from metrics-server
                    cpu_cores, mem_bytes = self._fetch_pod_metrics(
                        custom, ns, pod_name
                    )

                    # If metrics-server returned zeros, fall back to requests
                    if cpu_cores == 0.0 and mem_bytes == 0.0:
                        cpu_cores, mem_bytes = self._pod_requests(p)

                    # Fetch node allocatable once per namespace
                    if not _node_fetched and p.spec and p.spec.node_name:
                        try:
                            node_obj = core.read_node(p.spec.node_name)  # type: ignore[union-attr]
                            node_cpu_alloc, node_mem_alloc = self._node_allocatable(
                                node_obj
                            )
                            _node_fetched = True
                        except Exception:  # noqa: BLE001
                            pass

                    cpu_pct: float = min(
                        round(cpu_cores / node_cpu_alloc * 100.0, 1), 100.0
                    )
                    mem_pct: float = min(
                        round(mem_bytes / node_mem_alloc * 100.0, 1), 100.0
                    )

                    pods.append(
                        PodInfo(
                            name=pod_name,
                            namespace=ns,
                            component=component,
                            status=(p.status.phase or "Unknown").lower(),
                            restarts=int(restarts),
                            cpu_pct=cpu_pct,
                            memory_pct=mem_pct,
                            age_hours=age_hours,
                            image_sha=image_sha,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"kubernetes tenant_health failed: {exc}"
            ) from exc

        result = TenantHealth(
            pods=pods,
            last_deploy_at=last_deploy_at,
            last_deploy_sha=last_deploy_sha,
            argocd_url=(
                os.getenv("ARGOCD_BASE_URL", "https://argocd-stg.skyfirstlabs.com")
                + f"/applications/sky-be-stg-aws"
            ),
            grafana_url=(
                os.getenv("GRAFANA_BASE_URL", "https://grafana-stg.skyfirstlabs.com")
                + f"/d/tenant/{slug}?var-tenant={slug}"
            ),
        )
        # Only cache successful (non-empty) results — empty pods means the
        # cluster was unreachable and we don't want to serve stale zeros.
        if pods:
            _cache_set(f"tenant_health:{slug}", result)
        return result

    def cluster_nodes(self) -> List[ClusterNode]:
        """Return all cluster nodes with real CPU/memory usage percentages.

        Uses the metrics-server ``/apis/metrics.k8s.io/v1beta1/nodes``
        endpoint when available. Falls back to ``0.0`` silently if not.
        """
        cached = _cache_get("cluster_nodes")
        if cached is not None:
            return cached
        self._ensure_clients()
        out: List[ClusterNode] = []
        for cluster, core, custom in (
            ("stg", self._stg_core, self._stg_custom),
            ("prd", self._prd_core, self._prd_custom),
        ):
          if core is None:
              continue
          try:
                # Fetch node metrics from metrics-server (best-effort)
                node_metrics_by_name: dict[str, tuple[float, float]] = {}
                try:
                    metrics_resp = custom.list_cluster_custom_object(  # type: ignore[union-attr]
                        group="metrics.k8s.io",
                        version="v1beta1",
                        plural="nodes",
                    )
                    for nm in metrics_resp.get("items", []):
                        name = nm.get("metadata", {}).get("name", "")
                        usage = nm.get("usage", {})
                        cpu = _parse_cpu_cores(usage.get("cpu", "0"))
                        mem = _parse_memory_bytes(usage.get("memory", "0"))
                        node_metrics_by_name[name] = (cpu, mem)
                except Exception:  # noqa: BLE001 — metrics-server absent
                    pass

                for n in core.list_node().items:  # type: ignore[union-attr]
                    node_name: str = n.metadata.name

                    # Role
                    role: str = "infra"
                    if n.metadata.labels:
                        for k in n.metadata.labels:
                            if k.startswith("node-role.kubernetes.io/"):
                                role = k.split("/", 1)[1] or role
                                break

                    # Ready status
                    node_status: str = "ready"
                    for cond in n.status.conditions or []:
                        if cond.type == "Ready":
                            node_status = (
                                "ready" if cond.status == "True" else "not_ready"
                            )

                    # Pod count on this node
                    pods_on_node: int = 0
                    try:
                        all_pods = core.list_pod_for_all_namespaces(  # type: ignore[union-attr]
                            field_selector=f"spec.nodeName={node_name}"
                        ).items
                        pods_on_node = len(all_pods)
                    except Exception:  # noqa: BLE001
                        pass

                    # CPU / memory percentage
                    alloc_cpu, alloc_mem = self._node_allocatable(n)
                    used_cpu, used_mem = node_metrics_by_name.get(node_name, (0.0, 0.0))
                    cpu_pct: float = min(
                        round(used_cpu / alloc_cpu * 100.0, 1), 100.0
                    )
                    mem_pct: float = min(
                        round(used_mem / alloc_mem * 100.0, 1), 100.0
                    )

                    out.append(
                        ClusterNode(
                            name=node_name,
                            cluster=cluster,
                            role=role,
                            cpu_pct=cpu_pct,
                            memory_pct=mem_pct,
                            pods_count=pods_on_node,
                            status=node_status,
                        )
                    )
          except Exception as exc:  # noqa: BLE001 — one cluster down, continue
              logger.warning("k8s_cluster_nodes_failed cluster=%s: %s", cluster, str(exc)[:200])

        if out:  # only cache non-empty results
            _cache_set("cluster_nodes", out)
        return out


# ── Log streamer ───────────────────────────────────────────────────


class KubernetesLogStreamer:
    """Streams real pod logs line-by-line from the Kubernetes API.

    Usage::

        streamer = KubernetesLogStreamer()
        await streamer.stream(slug="acme", pod="sky-be-7d4f9b-xxxx",
                              send_line=send_line)

    ``send_line`` is called with a dict for each log line::

        {"ts": "...", "pod": "...", "level": "INFO|WARN|ERROR", "message": "..."}

    The method blocks until the pod terminates or the caller cancels
    the task. All Kubernetes errors raise ``TelemetryUnavailable``.

    Env vars:
        KUBECONFIG_PROD — used to resolve the production cluster client.
    """

    def __init__(self) -> None:
        self._core: Optional[object] = None
        self._tried_init: bool = False

    def _ensure_client(self) -> None:
        if self._tried_init:
            return
        self._tried_init = True
        try:
            from kubernetes import client as k8s_client  # type: ignore[import-not-found]
            from kubernetes import config as k8s_config  # type: ignore[import-not-found]
        except ImportError as exc:
            raise TelemetryUnavailable(
                "kubernetes-client not installed — pip install kubernetes"
            ) from exc

        prd_path = os.getenv("KUBECONFIG_PROD")
        if not prd_path:
            raise TelemetryUnavailable(
                "KUBECONFIG_PROD env var required for KubernetesLogStreamer"
            )

        try:
            k8s_config.load_kube_config(config_file=prd_path)
            self._core = k8s_client.CoreV1Api()
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"Failed to load kubeconfig for log streaming: {exc}"
            ) from exc

    async def stream(
        self,
        slug: str,
        pod: str,
        send_line: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Stream logs from ``pod`` in the ``{slug}-prd`` namespace.

        Each line is parsed and forwarded via ``send_line`` as a JSON-
        serialisable dict with keys ``ts``, ``pod``, ``level``,
        ``message``.

        The stream runs until the pod terminates, the connection is
        dropped, or an error occurs. kubernetes errors raise
        ``TelemetryUnavailable``; ``send_line`` errors propagate to the
        caller as-is (so the WebSocket handler can close cleanly).
        """
        import asyncio

        self._ensure_client()

        namespace: str = f"{slug}-prd"

        try:
            from kubernetes import stream as k8s_stream  # type: ignore[import-not-found]
        except ImportError as exc:
            raise TelemetryUnavailable(
                "kubernetes-client not installed — pip install kubernetes"
            ) from exc

        # kubernetes.stream is blocking — run it in a thread pool to
        # avoid stalling the event loop.
        loop = asyncio.get_running_loop()

        def _open_stream():  # type: ignore[return]
            return k8s_stream.stream(
                self._core.read_namespaced_pod_log,  # type: ignore[union-attr]
                pod,
                namespace,
                follow=True,
                timestamps=True,
                _preload_content=False,
            )

        try:
            resp = await loop.run_in_executor(None, _open_stream)
        except Exception as exc:  # noqa: BLE001
            raise TelemetryUnavailable(
                f"Failed to open log stream for pod {pod!r} in {namespace!r}: {exc}"
            ) from exc

        def _iter_lines():  # type: ignore[return]
            """Read lines from the streaming response (blocking)."""
            try:
                for line in resp:
                    yield line
            except Exception:  # noqa: BLE001 — normal EOF / disconnect
                return

        try:
            async for raw in _async_iter_lines(loop, _iter_lines):
                if not raw:
                    continue
                ts, message = _split_timestamp(raw)
                level = _parse_level(message)
                await send_line(
                    {
                        "ts": ts,
                        "pod": pod,
                        "level": level,
                        "message": message,
                    }
                )
        except Exception:  # noqa: BLE001 — client disconnect or stream end
            pass
        finally:
            try:
                resp.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass


# ── Private async iteration helper ────────────────────────────────


async def _async_iter_lines(loop, gen_factory):  # type: ignore[no-untyped-def]
    """Yield lines from a synchronous generator factory in the thread pool.

    ``gen_factory`` is a zero-argument callable that returns an iterator
    of strings. Each ``.send()`` / ``.__next__()`` call is dispatched to
    the default executor so blocking I/O does not stall the event loop.
    """
    import asyncio

    gen = gen_factory()
    sentinel = object()

    def _next():
        try:
            return next(gen)
        except StopIteration:
            return sentinel

    while True:
        line = await loop.run_in_executor(None, _next)
        if line is sentinel:
            break
        yield line


def _split_timestamp(raw: str) -> tuple[str, str]:
    """Split a Kubernetes log line that may begin with an RFC3339 timestamp.

    When ``timestamps=True`` is passed to ``read_namespaced_pod_log``,
    each line is prefixed with an RFC3339 timestamp followed by a space::

        2024-01-15T12:00:00.123456789Z INFO server started

    Returns ``(iso_timestamp, message)``. If no timestamp prefix is
    detected, the current UTC time is used as the timestamp and the
    entire line is treated as the message.
    """
    parts = raw.split(" ", 1)
    if len(parts) == 2 and "T" in parts[0] and parts[0].endswith("Z"):
        ts_raw = parts[0]
        # Normalise to a plain ISO string the frontend can parse
        try:
            # Replace nanoseconds (>6 digits) with microseconds
            import re as _re
            ts_clean = _re.sub(r"(\.\d{6})\d+(Z)", r"\1\2", ts_raw)
            dt = datetime.fromisoformat(ts_clean.replace("Z", "+00:00"))
            return dt.isoformat(), parts[1]
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat(), raw


__all__ = [
    "KubernetesInfraProvider",
    "KubernetesLogStreamer",
]
