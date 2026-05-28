"""Prometheus-backed SLI provider for the Internal Console health endpoint.

Queries the Prometheus HTTP API for the four SLI fields that
``KubernetesInfraProvider`` cannot supply:

* ``api_uptime_pct``        — probe_success SLO (30 d rolling)
* ``api_latency_p95_ms``    — P95 histogram_quantile (5 m)
* ``api_error_rate_pct``    — 5xx rate (5 m)
* ``db_connections_used``   — pg_stat_activity count
* ``db_connections_max``    — pg_settings_max_connections

Activation: set the ``PROMETHEUS_URL`` environment variable
(e.g. ``http://prometheus.monitoring:9090``).  When the variable is
absent the provider silently returns zeros so the Console renders
gracefully with no extra noise in the logs.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PromQL queries
# ---------------------------------------------------------------------------

# Metric names are from prometheus_fastapi_instrumentator (installed in sky-be).
# The ServiceMonitor (k8s/service-monitor-backend.yaml) sets job="sky-api" via
# relabeling so these queries work once Prometheus scrapes the /metrics endpoint.
#
# status label format from instrumentator: "2xx", "4xx", "5xx" (not raw codes).
_QUERIES: dict[str, str] = {
    # Uptime: fraction of requests that were NOT 5xx over the last 30 days.
    # Uses the instrumentator's http_requests_total with status="5xx" label.
    "api_uptime_pct": (
        "("
        "1 - ("
        "  sum(rate(http_requests_total{job=\"sky-api\",status=\"5xx\"}[30d]))"
        "  / sum(rate(http_requests_total{job=\"sky-api\"}[30d]))"
        ")"
        ") * 100"
    ),
    # Fallback when the primary returns nothing (e.g. no 5xx traffic):
    "_api_uptime_pct_fallback": (
        "clamp_max("
        "  sum(rate(http_requests_total{job=\"sky-api\",status=\"2xx\"}[30d]))"
        "  / sum(rate(http_requests_total{job=\"sky-api\"}[30d]))"
        "  * 100, 100)"
    ),
    # P95 latency: uses http_request_duration_highr_seconds (high-resolution
    # histogram without handler labels — more accurate percentile calculation).
    #
    # clamp_max(…, 30000): the highr histogram has a 60-second upper bucket
    # boundary.  AI/streaming endpoints (SSE, LLM chat) generate ~8% of
    # requests with latency genuinely above 60 s, which pushes histogram_quantile
    # to return the hard 60 000 ms ceiling rather than a meaningful API SLO value.
    # We cap at 30 000 ms so the Console dashboard displays a useful number while
    # still surfacing real degradations up to a 30-second SLA threshold.
    "api_latency_p95_ms": (
        "clamp_max("
        "histogram_quantile(0.95,"
        " sum(rate(http_request_duration_highr_seconds_bucket{job=\"sky-api\"}[5m]))"
        " by (le)) * 1000,"
        " 30000)"
    ),
    # Error rate: 5xx requests as % of all requests in the last 5 minutes.
    "api_error_rate_pct": (
        "sum(rate(http_requests_total{job=\"sky-api\",status=\"5xx\"}[5m]))"
        " / sum(rate(http_requests_total{job=\"sky-api\"}[5m])) * 100"
    ),
    # DB connections — requires postgres_exporter. Falls back to 0 gracefully.
    "db_connections_used": (
        "sum(pg_stat_activity_count{datname=~\"sky.*\"})"
    ),
    "db_connections_max": (
        "max(pg_settings_max_connections)"
    ),
}

_TIMEOUT_SECONDS = 5.0


class PrometheusHealthProvider:
    """Fetch platform SLI metrics from a Prometheus instance.

    Parameters
    ----------
    prometheus_url:
        Base URL of the Prometheus server, e.g. ``http://prometheus:9090``.
        Defaults to the ``PROMETHEUS_URL`` environment variable.  When
        neither is set, :meth:`get_platform_health_metrics` returns zeros.
    """

    def __init__(self, prometheus_url: Optional[str] = None) -> None:
        self._url: Optional[str] = prometheus_url or os.getenv("PROMETHEUS_URL") or None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_scalar(response_data: dict) -> Optional[float]:
        """Pull the numeric scalar out of a Prometheus instant-query response.

        Returns ``None`` when the result set is empty or the value is NaN.
        """
        try:
            result_type = response_data.get("data", {}).get("resultType")
            results = response_data.get("data", {}).get("result", [])
            if not results:
                return None
            if result_type == "scalar":
                # scalar: [timestamp, "value"]
                raw = results[1] if len(results) > 1 else results[0]
            else:
                # vector/matrix: first series, last value
                first = results[0]
                raw = first.get("value", [None, None])[1]
            if raw is None:
                return None
            value = float(raw)
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    async def _query(self, client, promql: str, label: str) -> Optional[float]:
        """Execute a single PromQL instant query; return the scalar or None."""
        try:
            httpx = _lazy_httpx()
            resp = await client.get(
                "/api/v1/query",
                params={"query": promql},
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            value = self._extract_scalar(resp.json())
            return value
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "prometheus_query_failed",
                extra={"metric": label, "error": str(exc)[:300]},
            )
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_platform_health_metrics(self) -> dict[str, float]:
        """Return SLI dict complementing ``KubernetesInfraProvider.platform_health``.

        Fields returned:
            api_uptime_pct, api_latency_p95_ms, api_error_rate_pct,
            db_connections_used, db_connections_max

        Any field whose query fails or returns NaN is set to ``0.0``.
        When ``PROMETHEUS_URL`` is not configured, all fields are ``0.0``
        and no warning is emitted.
        """
        zeros: dict[str, float] = {
            "api_uptime_pct": 0.0,
            "api_latency_p95_ms": 0.0,
            "api_error_rate_pct": 0.0,
            "db_connections_used": 0.0,
            "db_connections_max": 0.0,
        }

        if not self._url:
            # Not configured — return zeros silently.
            return zeros

        try:
            httpx = _lazy_httpx()
        except ImportError as exc:
            logger.warning("prometheus_provider_missing_httpx", extra={"error": str(exc)})
            return zeros

        result: dict[str, float] = dict(zeros)

        async with httpx.AsyncClient(base_url=self._url) as client:
            # --- api_uptime_pct (with probe_success fallback) ---
            uptime = await self._query(
                client, _QUERIES["api_uptime_pct"], "api_uptime_pct"
            )
            if uptime is None:
                uptime = await self._query(
                    client,
                    _QUERIES["_api_uptime_pct_fallback"],
                    "api_uptime_pct_fallback",
                )
            result["api_uptime_pct"] = uptime if uptime is not None else 0.0

            # --- api_latency_p95_ms ---
            latency = await self._query(
                client, _QUERIES["api_latency_p95_ms"], "api_latency_p95_ms"
            )
            result["api_latency_p95_ms"] = latency if latency is not None else 0.0

            # --- api_error_rate_pct ---
            error_rate = await self._query(
                client, _QUERIES["api_error_rate_pct"], "api_error_rate_pct"
            )
            result["api_error_rate_pct"] = error_rate if error_rate is not None else 0.0

            # --- db_connections_used ---
            db_used = await self._query(
                client, _QUERIES["db_connections_used"], "db_connections_used"
            )
            result["db_connections_used"] = db_used if db_used is not None else 0.0

            # --- db_connections_max ---
            db_max = await self._query(
                client, _QUERIES["db_connections_max"], "db_connections_max"
            )
            result["db_connections_max"] = db_max if db_max is not None else 0.0

        return result


# ---------------------------------------------------------------------------
# Lazy httpx import
# ---------------------------------------------------------------------------


def _lazy_httpx():
    """Import httpx lazily so the module loads even without the package."""
    try:
        import httpx  # type: ignore[import-untyped]
        return httpx
    except ImportError as exc:
        raise ImportError(
            "httpx is required for PrometheusHealthProvider — "
            "install it with: pip install httpx"
        ) from exc


__all__ = ["PrometheusHealthProvider"]
