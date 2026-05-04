"""Tier classifier — unit tests, no DB.

Verifies the L1/L2/L3 mapping for chat and agent surfaces. Pure
function tests (no fixtures, no async).
"""

from __future__ import annotations

from src.services.insights_tier import (
    ALLOWANCE_WEIGHT_BY_TIER,
    HOURS_SAVED_BY_TIER,
    ClassificationInput,
    classify_agent_execution,
    classify_chat_message,
    classify_tier,
)


# ─── Generic classifier ─────────────────────────────────────────────────────


def test_pure_signal_no_retrieval_no_steps_lands_at_l1():
    assert classify_tier(ClassificationInput()) == "l1"


def test_retrieval_alone_promotes_to_l2():
    assert classify_tier(ClassificationInput(retrieval_used=True)) == "l2"


def test_multi_step_with_retrieval_lands_l3():
    assert classify_tier(
        ClassificationInput(retrieval_used=True, multi_step=True)
    ) == "l3"


def test_multi_step_without_retrieval_stays_at_l1():
    # Multi-step without retrieval is a procedural answer, not a deep
    # dive — leaving it at L1 keeps the tier from inflating.
    assert classify_tier(ClassificationInput(multi_step=True)) == "l1"


def test_high_input_with_retrieval_is_l3():
    assert classify_tier(
        ClassificationInput(retrieval_used=True, input_tokens=20_000)
    ) == "l3"


def test_large_output_alone_is_l2():
    assert classify_tier(ClassificationInput(output_tokens=8_000)) == "l2"


def test_findings_present_promotes_to_l2():
    assert classify_tier(ClassificationInput(findings_count=2)) == "l2"


def test_error_forces_l1_regardless_of_signal():
    assert classify_tier(
        ClassificationInput(
            retrieval_used=True, multi_step=True, error=True
        )
    ) == "l1"


# ─── Agent helper ───────────────────────────────────────────────────────────


def test_agent_no_findings_default_kind_is_l1():
    assert classify_agent_execution(findings_count=0) == "l1"


def test_agent_with_findings_is_l2():
    assert classify_agent_execution(findings_count=3) == "l2"


def test_agent_material_delta_promotes_to_l3():
    # material delta means the agent surfaced something genuinely new,
    # multi_step is implied by the supervisor; combined with the
    # implicit retrieval flag we land at L3.
    assert classify_agent_execution(
        findings_count=1, delta_kind="material"
    ) == "l3"


def test_scan_monitor_with_findings_is_l3():
    assert classify_agent_execution(
        findings_count=2, monitor_type="scan"
    ) == "l3"


# ─── Chat helper ────────────────────────────────────────────────────────────


def test_chat_short_no_retrieval_is_l1():
    assert classify_chat_message(retrieval_used=False) == "l1"


def test_chat_with_retrieval_is_l2():
    assert classify_chat_message(retrieval_used=True) == "l2"


def test_chat_multi_step_with_retrieval_is_l3():
    assert classify_chat_message(retrieval_used=True, multi_step=True) == "l3"


# ─── Sanity on the supporting tables ─────────────────────────────────────────


def test_hours_saved_strictly_increasing_by_tier():
    # The L3 reward must outpace L2 and L1, otherwise the value framing
    # falls apart on the hero metric.
    assert HOURS_SAVED_BY_TIER["l1"] < HOURS_SAVED_BY_TIER["l2"] < HOURS_SAVED_BY_TIER["l3"]


def test_l1_costs_zero_against_allowance():
    # L1 = free interaction. Any non-zero weight would mean trivial
    # lookups burn the customer's monthly insight cap, which is the
    # opposite of what we want to communicate.
    assert ALLOWANCE_WEIGHT_BY_TIER["l1"] == 0
    assert ALLOWANCE_WEIGHT_BY_TIER["l2"] >= 1
    assert ALLOWANCE_WEIGHT_BY_TIER["l3"] > ALLOWANCE_WEIGHT_BY_TIER["l2"]
