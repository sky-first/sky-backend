"""W10 — Chat / agent Prometheus metrics.

Master plan §10.

Exposes a small, stable set of counters + histograms that the chat
pipeline emits at key decision points. The existing
``prometheus_fastapi_instrumentator`` in ``main.py`` publishes them at
``/api/metrics`` alongside request metrics.

Invariants:
  - ``sky_ai_acl_breach_total`` MUST stay at zero in prod; alert fires
    on any increment (PagerDuty P1).
  - ``rate(sky_ai_injection_suspected_total[5m]) > 10/s`` alerts Slack.
  - Histograms use small-latency buckets so the p95 / p99 read well for
    LLM-scale durations.

Reset-friendly: all metric objects are module-level singletons, so
tests that import this module inside the same process may see counter
state from earlier tests. Call ``reset_test_metrics()`` at the top of
any test that asserts on absolute counts.
"""

from __future__ import annotations

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
)
from prometheus_client.metrics_core import Metric


# ---------------------------------------------------------------------------
#  Counters
# ---------------------------------------------------------------------------


ai_requests_total = Counter(
    "sky_ai_requests_total",
    "Chat / agent requests by endpoint + status + category.",
    labelnames=("endpoint", "status", "category"),
)

ai_guard_decisions_total = Counter(
    "sky_ai_guard_decisions_total",
    "Guard decisions (input / output guard).",
    labelnames=("stage", "decision", "reason"),
)

ai_injection_suspected_total = Counter(
    "sky_ai_injection_suspected_total",
    "Input flagged as likely prompt-injection (by pattern label).",
    labelnames=("pattern",),
)

ai_acl_breach_total = Counter(
    "sky_ai_acl_breach_total",
    "Output guard detected a citation outside the authorised set. "
    "MUST stay at 0 in prod — alert fires on any increment.",
    labelnames=("kind",),
)

ai_tool_calls_total = Counter(
    "sky_ai_tool_calls_total",
    "Tool executions attempted by the LLM.",
    labelnames=("tool", "status"),
)

ai_policy_refusals_total = Counter(
    "sky_ai_policy_refusals_total",
    "Input rejected by category classifier (abuse / self-harm / csam).",
    labelnames=("category",),
)


# ---------------------------------------------------------------------------
#  Histograms
# ---------------------------------------------------------------------------


_LATENCY_BUCKETS = (
    0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 60.0, 120.0,
)

ai_upstream_latency_seconds = Histogram(
    "sky_ai_upstream_latency_seconds",
    "End-to-end latency of a chat / agent call, excluding the network "
    "to the client. Buckets tuned for LLM-scale durations.",
    labelnames=("stage",),
    buckets=_LATENCY_BUCKETS,
)


# ---------------------------------------------------------------------------
#  Convenience emitters
# ---------------------------------------------------------------------------


def record_request(endpoint: str, status: str, category: str = "ok") -> None:
    ai_requests_total.labels(endpoint=endpoint, status=status, category=category).inc()


def record_input_guard(
    *,
    decision: str,
    reason: str = "none",
    injection_patterns: list[str] | None = None,
    policy_category: str | None = None,
) -> None:
    ai_guard_decisions_total.labels(
        stage="input", decision=decision, reason=reason,
    ).inc()
    if injection_patterns:
        for pat in injection_patterns:
            ai_injection_suspected_total.labels(pattern=pat).inc()
    if policy_category:
        ai_policy_refusals_total.labels(category=policy_category).inc()


def record_output_guard(
    *,
    decision: str,
    reason: str = "none",
    acl_breach_kind: str | None = None,
) -> None:
    ai_guard_decisions_total.labels(
        stage="output", decision=decision, reason=reason,
    ).inc()
    if acl_breach_kind:
        ai_acl_breach_total.labels(kind=acl_breach_kind).inc()


def record_tool_call(tool: str, status: str) -> None:
    ai_tool_calls_total.labels(tool=tool, status=status).inc()


def observe_upstream_latency(stage: str, seconds: float) -> None:
    ai_upstream_latency_seconds.labels(stage=stage).observe(max(0.0, float(seconds)))


# ---------------------------------------------------------------------------
#  Test-support
# ---------------------------------------------------------------------------


def reset_test_metrics() -> None:
    """Reset every counter + histogram. For use ONLY in tests — calling
    in prod would wipe all metrics mid-scrape."""
    for m in [
        ai_requests_total,
        ai_guard_decisions_total,
        ai_injection_suspected_total,
        ai_acl_breach_total,
        ai_tool_calls_total,
        ai_policy_refusals_total,
    ]:
        m._metrics.clear()  # type: ignore[attr-defined]
    # Histograms: reset via clearing internal child metrics.
    ai_upstream_latency_seconds._metrics.clear()  # type: ignore[attr-defined]


def sample_value(
    metric: Counter | Histogram,
    labels: dict[str, str],
    sample_name: str | None = None,
) -> float:
    """Return the current value of a labelled metric sample.

    For Counter: returns the ``_total`` sample.
    For Histogram: pass ``sample_name="_sum"`` / ``"_count"`` or a bucket
    like ``"_bucket"`` with ``labels={"le": "1.0", ...}``.
    """
    wanted: list[Metric] = list(metric.collect())
    for family in wanted:
        for sample in family.samples:
            if sample_name and not sample.name.endswith(sample_name):
                continue
            if all(sample.labels.get(k) == v for k, v in labels.items() if k != "le" or sample_name):
                return float(sample.value)
    return 0.0
