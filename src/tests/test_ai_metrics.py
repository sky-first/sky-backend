"""W10 — AI metrics tests.

QA perspectives:
  - Each emitter increments the right counter with the right labels.
  - ACL-breach invariant — counter reachable; in prod it stays 0.
  - Injection: multi-pattern accumulates; unique label values.
  - Histogram observes values and is queryable.
  - Emitters safe when called with missing optional args.
  - reset_test_metrics clears between tests.
"""

from __future__ import annotations

import math

import pytest
from prometheus_client import Counter, Histogram

from src.ai.metrics import (
    ai_acl_breach_total,
    ai_guard_decisions_total,
    ai_injection_suspected_total,
    ai_policy_refusals_total,
    ai_requests_total,
    ai_tool_calls_total,
    ai_upstream_latency_seconds,
    observe_upstream_latency,
    record_input_guard,
    record_output_guard,
    record_request,
    record_tool_call,
    reset_test_metrics,
    sample_value,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_test_metrics()
    yield
    reset_test_metrics()


# ---------------------------------------------------------------------------
#  Shape
# ---------------------------------------------------------------------------


class TestShape:
    def test_counters_are_counters(self):
        for m in [
            ai_requests_total,
            ai_guard_decisions_total,
            ai_injection_suspected_total,
            ai_acl_breach_total,
            ai_tool_calls_total,
            ai_policy_refusals_total,
        ]:
            assert isinstance(m, Counter)

    def test_latency_is_histogram(self):
        assert isinstance(ai_upstream_latency_seconds, Histogram)


# ---------------------------------------------------------------------------
#  Requests
# ---------------------------------------------------------------------------


class TestRecordRequest:
    def test_counter_increments(self):
        record_request("/ai/chat", "200")
        record_request("/ai/chat", "200")
        v = sample_value(
            ai_requests_total,
            {"endpoint": "/ai/chat", "status": "200", "category": "ok"},
        )
        assert v == 2

    def test_different_endpoint_separate_counter(self):
        record_request("/ai/chat", "200")
        record_request("/ai/query", "200")
        a = sample_value(ai_requests_total, {"endpoint": "/ai/chat", "status": "200", "category": "ok"})
        b = sample_value(ai_requests_total, {"endpoint": "/ai/query", "status": "200", "category": "ok"})
        assert a == 1 and b == 1

    def test_category_label_routes(self):
        record_request("/ai/chat", "400", category="policy")
        v = sample_value(
            ai_requests_total,
            {"endpoint": "/ai/chat", "status": "400", "category": "policy"},
        )
        assert v == 1


# ---------------------------------------------------------------------------
#  Input guard
# ---------------------------------------------------------------------------


class TestInputGuard:
    def test_decision_counter(self):
        record_input_guard(decision="pass", reason="none")
        v = sample_value(
            ai_guard_decisions_total,
            {"stage": "input", "decision": "pass", "reason": "none"},
        )
        assert v == 1

    def test_injection_patterns_accumulate(self):
        record_input_guard(
            decision="flag",
            reason="injection",
            injection_patterns=["ignore_previous", "print_system_prompt"],
        )
        a = sample_value(ai_injection_suspected_total, {"pattern": "ignore_previous"})
        b = sample_value(ai_injection_suspected_total, {"pattern": "print_system_prompt"})
        assert a == 1 and b == 1

    def test_policy_category_counted(self):
        record_input_guard(
            decision="block",
            reason="policy",
            policy_category="self_harm",
        )
        v = sample_value(ai_policy_refusals_total, {"category": "self_harm"})
        assert v == 1

    def test_empty_injection_list_noop(self):
        """No injection patterns => injection counter stays 0."""
        record_input_guard(decision="pass", reason="none")
        assert sample_value(ai_injection_suspected_total, {"pattern": "ignore_previous"}) == 0


# ---------------------------------------------------------------------------
#  Output guard + ACL breach
# ---------------------------------------------------------------------------


class TestOutputGuard:
    def test_pass_decision(self):
        record_output_guard(decision="pass")
        v = sample_value(
            ai_guard_decisions_total,
            {"stage": "output", "decision": "pass", "reason": "none"},
        )
        assert v == 1

    def test_acl_breach_counts(self):
        record_output_guard(decision="block", reason="acl_breach", acl_breach_kind="citation_out_of_range")
        a = sample_value(
            ai_guard_decisions_total,
            {"stage": "output", "decision": "block", "reason": "acl_breach"},
        )
        b = sample_value(ai_acl_breach_total, {"kind": "citation_out_of_range"})
        assert a == 1 and b == 1

    def test_acl_breach_counter_starts_at_zero(self):
        """Invariant: in a fresh state, acl_breach is 0."""
        assert sample_value(ai_acl_breach_total, {"kind": "x"}) == 0


# ---------------------------------------------------------------------------
#  Tool calls
# ---------------------------------------------------------------------------


class TestToolCalls:
    def test_counts_by_tool_and_status(self):
        record_tool_call("sql.select", "ok")
        record_tool_call("sql.select", "denied")
        record_tool_call("widget.create", "ok")
        assert sample_value(ai_tool_calls_total, {"tool": "sql.select", "status": "ok"}) == 1
        assert sample_value(ai_tool_calls_total, {"tool": "sql.select", "status": "denied"}) == 1
        assert sample_value(ai_tool_calls_total, {"tool": "widget.create", "status": "ok"}) == 1


# ---------------------------------------------------------------------------
#  Latency
# ---------------------------------------------------------------------------


class TestLatency:
    def test_observe_counts_and_sum(self):
        observe_upstream_latency("chat", 0.3)
        observe_upstream_latency("chat", 1.2)
        observe_upstream_latency("chat", 7.5)
        count = sample_value(
            ai_upstream_latency_seconds,
            {"stage": "chat"},
            sample_name="_count",
        )
        assert count == 3
        s = sample_value(
            ai_upstream_latency_seconds,
            {"stage": "chat"},
            sample_name="_sum",
        )
        assert math.isclose(s, 0.3 + 1.2 + 7.5, rel_tol=1e-9)

    def test_negative_observation_clamped_to_zero(self):
        """A negative value (clock skew) must not poison the histogram."""
        observe_upstream_latency("chat", -5.0)
        s = sample_value(
            ai_upstream_latency_seconds,
            {"stage": "chat"},
            sample_name="_sum",
        )
        assert s == 0.0

    def test_different_stages_separate(self):
        observe_upstream_latency("retrieval", 0.1)
        observe_upstream_latency("llm", 5.0)
        a = sample_value(
            ai_upstream_latency_seconds,
            {"stage": "retrieval"},
            sample_name="_count",
        )
        b = sample_value(
            ai_upstream_latency_seconds,
            {"stage": "llm"},
            sample_name="_count",
        )
        assert a == 1 and b == 1


# ---------------------------------------------------------------------------
#  Reset helper
# ---------------------------------------------------------------------------


def test_reset_clears_everything():
    record_request("/ai/chat", "200")
    record_tool_call("sql.select", "ok")
    observe_upstream_latency("chat", 1.0)

    reset_test_metrics()

    assert sample_value(ai_requests_total, {"endpoint": "/ai/chat", "status": "200", "category": "ok"}) == 0
    assert sample_value(ai_tool_calls_total, {"tool": "sql.select", "status": "ok"}) == 0
    assert sample_value(ai_upstream_latency_seconds, {"stage": "chat"}, sample_name="_count") == 0
