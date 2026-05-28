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


# Hard SLO ceiling: the route must respond within this budget regardless
# of how slow K8s or Prometheus are individually. Each provider already
# has its own internal timeout (K8s client: urllib3 default ~60s which
# is too long; Prometheus: 5s). This outer gate caps the *combined* wait.
_HEALTH_TIMEOUT_SECONDS = 8.0

# Zero-metric fallback returned when a provider times out.
_EMPTY_PROM_METRICS: dict[str, float] = {
    "api_uptime_pct": 0.0,
    "api_latency_p95_ms": 0.0,
    "api_error_rate_pct": 0.0,
    "db_connections_used": 0.0,
    "db_connections_max": 0.0,
}


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
    timeout:
        Hard SLO ceiling in seconds for the combined K8s + Prometheus call.
        Defaults to ``_HEALTH_TIMEOUT_SECONDS``. When either provider exceeds
        its individual budget, the timed-out one is replaced with zeros so the
        other's data still reaches the caller. This prevents a degraded K8s
        API server from cascading into a Console page timeout.
    """

    def __init__(
        self,
        k8s: InfraProvider,
        prometheus: "PrometheusHealthProvider",
        timeout: float = _HEALTH_TIMEOUT_SECONDS,
    ) -> None:
        self._k8s = k8s
        self._prometheus = prometheus
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Primary async method
    # ------------------------------------------------------------------

    async def platform_health(self) -> PlatformHealth:
        """Return a ``PlatformHealth`` merging K8s pod counts and Prometheus SLIs.

        Both providers run concurrently. Each is individually wrapped in
        ``asyncio.wait_for`` with half the total budget so a slow provider
        degrades gracefully (returns zeros) without blocking the other.
        The total wall-clock time is capped at ``self._timeout`` seconds.
        """
        loop = asyncio.get_event_loop()
        half = self._timeout / 2

        # K8s is sync/blocking — offload to thread pool.
        async def _k8s_safe() -> PlatformHealth | None:
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, self._k8s.platform_health),
                    timeout=half,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "composite_infra: K8s platform_health timed out after %.1fs — "
                    "pod counts will be zero",
                    half,
                )
                return None
            except Exception as exc:  # noqa: BLE001
                logger.warning("composite_infra: K8s platform_health failed: %s", exc)
                return None

        async def _prom_safe() -> dict[str, float]:
            try:
                return await asyncio.wait_for(
                    self._prometheus.get_platform_health_metrics(),
                    timeout=half,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "composite_infra: Prometheus timed out after %.1fs — "
                    "SLI fields will be zero",
                    half,
                )
                return _EMPTY_PROM_METRICS
            except Exception as exc:  # noqa: BLE001
                logger.warning("composite_infra: Prometheus failed: %s", exc)
                return _EMPTY_PROM_METRICS

        k8s_health, prom_metrics = await asyncio.gather(_k8s_safe(), _prom_safe())

        # Merge: pod fields from K8s (or zeros if K8s timed out), SLIs from Prometheus.
        pods_running = k8s_health.pods_running if k8s_health else 0
        pods_pending = k8s_health.pods_pending if k8s_health else 0
        pods_crashlooping = k8s_health.pods_crashlooping if k8s_health else 0
        last_incident = k8s_health.last_incident if k8s_health else None

        return PlatformHealth(
            api_uptime_pct=prom_metrics.get("api_uptime_pct", 0.0),
            api_latency_p95_ms=int(prom_metrics.get("api_latency_p95_ms", 0.0)),
            api_error_rate_pct=prom_metrics.get("api_error_rate_pct", 0.0),
            pods_running=pods_running,
            pods_pending=pods_pending,
            pods_crashlooping=pods_crashlooping,
            db_connections_used=int(prom_metrics.get("db_connections_used", 0.0)),
            db_connections_max=int(prom_metrics.get("db_connections_max", 0.0)),
            last_incident=last_incident,
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
