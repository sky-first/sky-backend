"""LLM cost / usage metrics via Langfuse.

Langfuse is already wired in ``sky-poc-ai`` — every LangGraph
execution emits a trace tagged with ``user_id``, ``space_id`` and
``agent_id`` (see ``core/agents/full_context_agent.py``). This module
queries those traces back via the Langfuse REST API so the Console
can render "real cost per tenant / per agent / per question" without
needing to instrument every LLM call ourselves a second time.

Design rules:

1. **Best-effort.** Langfuse is observability — losing the metrics
   panel must never break the Console. The provider catches every
   exception (network, auth, parsing, schema drift) and returns an
   empty :class:`LlmMetrics` with ``available=False``. Routes surface
   that flag to the UI so the operator knows the data is stale.

2. **Cache aggressively.** Langfuse Cloud rate-limits at ~100
   req/min/project; the Console UI polls every ~30s and the CEO
   dashboard piggy-backs on the same provider. A 5-minute TTL keeps
   us well under ceiling with several operators online and gives the
   daily snapshot worker a hot cache when it runs.

3. **No SDK lock-in.** We call the Langfuse REST API via ``httpx``
   directly instead of pulling the Python SDK in the backend repo —
   the SDK exists for the tracing path (sky-poc-ai), but for reading
   metrics back the public REST API is more stable and avoids a
   second dependency tree on the backend image.

Tenant scoping convention:

   * The sky-poc-ai callback tags traces with ``user_id`` +
     ``metadata.space_id`` + ``metadata.agent_id`` today.
   * Multi-tenant builds (Projeto A Model B) also tag
     ``metadata.tenant_id`` and ``metadata.tenant_slug``. Until that
     lands everywhere, this provider falls back to querying by the
     ``tags`` field (``["tenant:<slug>"]``) if present, and finally
     to filtering nothing (single-tenant deployments).

Endpoint mapping:

   * ``GET /api/public/metrics/daily?fromTimestamp=…&tags=tenant:<slug>``
     → aggregated counts + cost per day, broken down by model.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.config.settings import settings


logger = logging.getLogger(__name__)


# ── Data classes (wire format) ─────────────────────────────────────


@dataclass
class LlmMetrics:
    """Aggregated LLM usage + cost across a time window.

    All token counts are integers; cost is in USD with EUR computed
    via the static FX rate from settings. ``available`` is False when
    Langfuse is unreachable / disabled — the rest of the fields are
    zeroed in that case so the UI can still render skeletons.
    """

    tenant_id: Optional[str]
    window_days: int
    from_ts: datetime
    to_ts: datetime
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_cost_eur: float = 0.0
    by_model: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # by_model[model_name] = {"input_tokens": …, "output_tokens": …,
    #                          "requests": …, "cost_usd": …}
    cache_hit_rate_pct: float = 0.0
    avg_latency_ms: float = 0.0
    available: bool = True
    # Free-form note populated when ``available=False`` so the UI can
    # render a tooltip ("Langfuse offline", "metrics disabled", …).
    unavailable_reason: Optional[str] = None


# ── Cache ──────────────────────────────────────────────────────────


_CACHE: Dict[str, Tuple[float, LlmMetrics]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: str, ttl: int) -> Optional[LlmMetrics]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        cached_at, value = entry
        if (time.monotonic() - cached_at) > ttl:
            _CACHE.pop(key, None)
            return None
        return value


def _cache_set(key: str, value: LlmMetrics) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), value)


def _cache_clear() -> None:
    """Test helper — wipes the TTL cache. Not called in production."""
    with _CACHE_LOCK:
        _CACHE.clear()


# ── Provider ───────────────────────────────────────────────────────


def _empty(
    tenant_id: Optional[str],
    days: int,
    reason: str,
) -> LlmMetrics:
    now = datetime.now(timezone.utc)
    return LlmMetrics(
        tenant_id=tenant_id,
        window_days=days,
        from_ts=now - timedelta(days=days),
        to_ts=now,
        available=False,
        unavailable_reason=reason,
    )


class LlmCostMetricsProvider:
    """Reads LLM usage + cost figures from Langfuse.

    The provider is stateless apart from a process-wide TTL cache.
    Constructed lazily by :func:`llm_cost_metrics_provider`.

    Two read paths today:

    * :meth:`get_tenant_llm_metrics` — one tenant slice. Used by
      ``GET /api/console/v1/tenants/{slug}/llm-metrics``.
    * :meth:`get_platform_llm_metrics` — sum across all tenants. Used
      by ``GET /api/console/v1/platform/llm-metrics`` and by the CEO
      dashboard's ``llm_cost_30d_eur`` field.

    Both are wrapped in try/except — Langfuse latency or downtime
    must not 500 the Console; the consumer renders an "off" state.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        cache_ttl_seconds: Optional[int] = None,
        eur_per_usd: Optional[float] = None,
        http_timeout: float = 8.0,
    ) -> None:
        self.host = (host or settings.LANGFUSE_HOST or "").rstrip("/")
        self.public_key = public_key or settings.LANGFUSE_PUBLIC_KEY
        self.secret_key = secret_key or settings.LANGFUSE_SECRET_KEY
        self.enabled = (
            settings.LLM_METRICS_ENABLED if enabled is None else enabled
        )
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.LLM_METRICS_CACHE_TTL_SECONDS
        )
        self.eur_per_usd = (
            eur_per_usd
            if eur_per_usd is not None
            else settings.LLM_METRICS_EUR_PER_USD
        )
        self.http_timeout = http_timeout

    # ── Public API ────────────────────────────────────────────────

    def get_tenant_llm_metrics(
        self,
        tenant_id: str,
        days: int = 30,
    ) -> LlmMetrics:
        """LLM usage + cost for a single tenant.

        ``tenant_id`` is whatever the sky-poc-ai callback tagged the
        trace with — for the Console UI this is the tenant slug
        (``"gbt"``, ``"appsconcept"``, …). Caller is expected to
        translate ``Tenant.id`` → ``Tenant.slug`` before calling.
        """
        if not self._configured():
            return _empty(tenant_id, days, "langfuse_disabled")

        cache_key = f"tenant:{tenant_id}:{days}"
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            return cached

        try:
            raw = self._fetch_daily_metrics(days=days, tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langfuse_metrics_tenant_failed",
                extra={"tenant_id": tenant_id, "error": str(exc)},
            )
            return _empty(tenant_id, days, "langfuse_unreachable")

        metrics = self._aggregate(raw, tenant_id=tenant_id, days=days)
        _cache_set(cache_key, metrics)
        return metrics

    def get_platform_llm_metrics(self, days: int = 30) -> LlmMetrics:
        """LLM usage + cost across all tenants in the project."""
        if not self._configured():
            return _empty(None, days, "langfuse_disabled")

        cache_key = f"platform:{days}"
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            return cached

        try:
            raw = self._fetch_daily_metrics(days=days, tenant_id=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langfuse_metrics_platform_failed",
                extra={"error": str(exc)},
            )
            return _empty(None, days, "langfuse_unreachable")

        metrics = self._aggregate(raw, tenant_id=None, days=days)
        _cache_set(cache_key, metrics)
        return metrics

    # ── Internals ─────────────────────────────────────────────────

    def _configured(self) -> bool:
        return bool(
            self.enabled
            and self.host
            and self.public_key
            and self.secret_key
        )

    def _auth_header(self) -> Dict[str, str]:
        token = base64.b64encode(
            f"{self.public_key}:{self.secret_key}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}"}

    def _fetch_daily_metrics(
        self,
        *,
        days: int,
        tenant_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Hit Langfuse ``/api/public/metrics/daily``.

        Returns the raw ``data`` array (one entry per day, each
        carrying ``usage[]`` rows broken down by model). Empty list
        if Langfuse returns no rows (e.g. brand-new tenant).
        """
        now = datetime.now(timezone.utc)
        from_ts = now - timedelta(days=days)
        params: Dict[str, Any] = {
            "fromTimestamp": from_ts.isoformat(),
            "toTimestamp": now.isoformat(),
        }
        if tenant_id:
            # Langfuse supports tag-prefix filtering. The sky-poc-ai
            # callback adds ``tenant:<slug>`` to the tags list when
            # multi-tenant is on; single-tenant deploys won't have
            # that tag and the call will return an empty page — we
            # treat that as a legitimate zero rather than an outage.
            params["tags"] = f"tenant:{tenant_id}"

        url = f"{self.host}/api/public/metrics/daily"
        with httpx.Client(timeout=self.http_timeout) as client:
            resp = client.get(url, params=params, headers=self._auth_header())
            resp.raise_for_status()
            body = resp.json()
        # Langfuse wraps the rows in ``{"data": [...], "meta": {...}}``.
        if isinstance(body, dict):
            return list(body.get("data") or [])
        if isinstance(body, list):
            return body
        return []

    def _aggregate(
        self,
        rows: List[Dict[str, Any]],
        *,
        tenant_id: Optional[str],
        days: int,
    ) -> LlmMetrics:
        """Collapse Langfuse's per-day / per-model rows into one
        flat :class:`LlmMetrics`."""
        now = datetime.now(timezone.utc)
        from_ts = now - timedelta(days=days)

        total_requests = 0
        total_input = 0
        total_output = 0
        total_cost_usd = 0.0
        by_model: Dict[str, Dict[str, float]] = {}
        cache_hits = 0
        latency_sum_ms = 0.0
        latency_n = 0

        for row in rows:
            # Each row carries an aggregate ``countTraces`` for the
            # day plus a per-model breakdown under ``usage``.
            day_traces = int(row.get("countTraces") or 0)
            total_requests += day_traces

            # Average latency is reported per day in seconds; weight by
            # trace count so the overall average is correct.
            day_latency_s = row.get("avgLatency") or row.get("avg_latency_seconds")
            if day_latency_s is not None and day_traces > 0:
                try:
                    latency_sum_ms += float(day_latency_s) * 1000.0 * day_traces
                    latency_n += day_traces
                except (TypeError, ValueError):
                    pass

            # Cache hits — Langfuse exposes ``cacheHitRate`` per day
            # (0..1). Convert to absolute count to roll up correctly.
            cache_hit_rate = row.get("cacheHitRate")
            if cache_hit_rate is not None and day_traces > 0:
                try:
                    cache_hits += int(float(cache_hit_rate) * day_traces)
                except (TypeError, ValueError):
                    pass

            for usage in row.get("usage") or []:
                model = (usage.get("model") or "unknown").strip()
                in_tok = int(usage.get("inputUsage") or usage.get("input_tokens") or 0)
                out_tok = int(usage.get("outputUsage") or usage.get("output_tokens") or 0)
                req = int(usage.get("countObservations") or usage.get("requests") or 0)
                cost_usd = float(usage.get("totalCost") or usage.get("cost_usd") or 0.0)

                total_input += in_tok
                total_output += out_tok
                total_cost_usd += cost_usd

                bucket = by_model.setdefault(
                    model,
                    {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "requests": 0,
                        "cost_usd": 0.0,
                    },
                )
                bucket["input_tokens"] = int(bucket["input_tokens"]) + in_tok
                bucket["output_tokens"] = int(bucket["output_tokens"]) + out_tok
                bucket["requests"] = int(bucket["requests"]) + req
                bucket["cost_usd"] = round(
                    float(bucket["cost_usd"]) + cost_usd, 6
                )

        cache_hit_rate_pct = (
            (cache_hits / total_requests * 100.0) if total_requests > 0 else 0.0
        )
        avg_latency_ms = (latency_sum_ms / latency_n) if latency_n > 0 else 0.0

        return LlmMetrics(
            tenant_id=tenant_id,
            window_days=days,
            from_ts=from_ts,
            to_ts=now,
            total_requests=total_requests,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_usd=round(total_cost_usd, 4),
            total_cost_eur=round(total_cost_usd * self.eur_per_usd, 4),
            by_model=by_model,
            cache_hit_rate_pct=round(cache_hit_rate_pct, 2),
            avg_latency_ms=round(avg_latency_ms, 1),
            available=True,
        )


# ── Module-level singleton ─────────────────────────────────────────


_PROVIDER: Optional[LlmCostMetricsProvider] = None
_PROVIDER_LOCK = threading.Lock()


def llm_cost_metrics_provider() -> LlmCostMetricsProvider:
    """Return the process-wide provider singleton.

    A fresh instance is created on first call and reused thereafter —
    rebuilding it per request would defeat the in-memory TTL cache.
    Tests can reset by importing :func:`reset_provider`.
    """
    global _PROVIDER
    with _PROVIDER_LOCK:
        if _PROVIDER is None:
            _PROVIDER = LlmCostMetricsProvider()
    return _PROVIDER


def reset_provider() -> None:
    """Drop the cached provider + TTL cache.

    Used by tests to install a stub via monkey-patching without
    leaking state across cases.
    """
    global _PROVIDER
    with _PROVIDER_LOCK:
        _PROVIDER = None
    _cache_clear()


__all__ = [
    "LlmMetrics",
    "LlmCostMetricsProvider",
    "llm_cost_metrics_provider",
    "reset_provider",
]
