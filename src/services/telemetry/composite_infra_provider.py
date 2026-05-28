"""Composite InfraProvider that merges Kubernetes pod data with Prometheus SLIs.

``CompositeInfraProvider`` wraps a ``KubernetesInfraProvider`` (or any object
satisfying the ``InfraProvider`` Protocol) and a ``PrometheusHealthProvider``.
It calls both concurrently and merges the results into a single
``PlatformHealth`` dataclass, so callers in the console routes see one unified
object with both pod counts and real SLI numbers.

Usage (in the dependency factory or route file)::

    from src.services.telemetry.prometheus_provider import PrometheusHealthProvider
    from src.services.telemetry.composite_infra_provider import CompositeInfraProvider
    from src.services.console_telemetry_real import KubernetesInfraProvider

    provider = CompositeInfraProvider(
        k8s=KubernetesInfraProvider(),
        prometheus=PrometheusHealthProvider(),
    )
    health = await provider.platform_health()
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List

from src.services.console_telemetry import (
    ClusterNode,
    InfraProvider,
    PlatformHealth,
    TenantHealth,
)

if TYPE_CHECKING:
    from src.services.telemetry.prometheus_provider import PrometheusHealthProvider

logger = logging.getLogger(__name__)


class CompositeInfraProvider:
    """Combines ``KubernetesInfraProvider`` (pods) with ``PrometheusHealthProvider`` (SLIs).

    ``platform_health`` is *async* so it can concurrently await the Prometheus
    HTTP calls.  ``tenant_health`` and ``cluster_nodes`` are synchronous
    pass-throughs to the K8s provider, matching the ``InfraProvider`` Protocol
    for those methods.

    Parameters
    ----------
    k8s:
        Any object satisfying the ``InfraProvider`` Protocol (typically a
        ``KubernetesInfraProvider`` instance).
    prometheus:
        A ``PrometheusHealthProvider`` instance.  Its
        ``get_platform_health_metrics`` method is awaited on every call to
        :meth:`platform_health`.
    """

    def __init__(
        self,
        k8s: InfraProvider,
        prometheus: "PrometheusHealthProvider",
    ) -> None:
        self._k8s = k8s
        self._prometheus = prometheus

    # ------------------------------------------------------------------
    # Primary async method
    # ------------------------------------------------------------------

    async def platform_health(self) -> PlatformHealth:
        """Return a ``PlatformHealth`` with pod counts from K8s and SLIs from Prometheus.

        The K8s call is made in a thread executor (it is synchronous / blocking)
        while the Prometheus queries run concurrently via asyncio.  Both results
        are merged into a single ``PlatformHealth`` before returning.

        Failures in either provider are handled defensively:
        - K8s errors propagate (they are already wrapped in ``TelemetryUnavailable``
          by ``KubernetesInfraProvider``).
        - Prometheus errors result in zero-filled SLI fields (already handled
          inside ``PrometheusHealthProvider``).
        """
        loop = asyncio.get_event_loop()

        # Run K8s (sync/blocking) in the default thread pool executor so it
        # does not block the event loop, and Prometheus (async) concurrently.
        k8s_task = loop.run_in_executor(None, self._k8s.platform_health)
        prom_task = asyncio.ensure_future(
            self._prometheus.get_platform_health_metrics()
        )

        k8s_health, prom_metrics = await asyncio.gather(k8s_task, prom_task)

        # Merge: pod fields come from K8s; SLI fields from Prometheus.
        return PlatformHealth(
            api_uptime_pct=prom_metrics.get("api_uptime_pct", 0.0),
            api_latency_p95_ms=int(prom_metrics.get("api_latency_p95_ms", 0.0)),
            api_error_rate_pct=prom_metrics.get("api_error_rate_pct", 0.0),
            pods_running=k8s_health.pods_running,
            pods_pending=k8s_health.pods_pending,
            pods_crashlooping=k8s_health.pods_crashlooping,
            db_connections_used=int(prom_metrics.get("db_connections_used", 0.0)),
            db_connections_max=int(prom_metrics.get("db_connections_max", 0.0)),
            last_incident=k8s_health.last_incident,
        )

    # ------------------------------------------------------------------
    # Synchronous pass-throughs (satisfy InfraProvider Protocol)
    # ------------------------------------------------------------------

    def tenant_health(self, slug: str) -> TenantHealth:
        """Delegate directly to the K8s provider."""
        return self._k8s.tenant_health(slug)

    def cluster_nodes(self) -> List[ClusterNode]:
        """Delegate directly to the K8s provider."""
        return self._k8s.cluster_nodes()


__all__ = ["CompositeInfraProvider"]
