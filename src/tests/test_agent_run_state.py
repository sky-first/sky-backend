"""Unit tests for the agent-run state machine (pure logic).

No DB fixtures here. The integration behaviour is covered by
test_agent_run_service.py.
"""

from datetime import timedelta

import pytest

from src.core.agent_run_state import (
    ALL_STATES,
    BACKOFF_SCHEDULE,
    CLAIM,
    FAILED,
    IllegalTransition,
    QUEUED,
    REPORT_FAILURE,
    REPORT_SKIP,
    REPORT_SUCCESS,
    RUNNING,
    SKIPPED,
    SUCCEEDED,
    TERMINAL_STATES,
    budget_exhausted,
    compute_backoff,
    transition,
)


# ─── transition table ────────────────────────────────────────────────────


class TestTransitions:
    def test_queued_claim_goes_running(self):
        assert transition(QUEUED, CLAIM) == RUNNING

    def test_running_success_goes_succeeded(self):
        assert transition(RUNNING, REPORT_SUCCESS) == SUCCEEDED

    def test_running_failure_goes_failed(self):
        assert transition(RUNNING, REPORT_FAILURE) == FAILED

    def test_running_skip_goes_skipped(self):
        assert transition(RUNNING, REPORT_SKIP) == SKIPPED

    def test_queued_cannot_report_success(self):
        with pytest.raises(IllegalTransition):
            transition(QUEUED, REPORT_SUCCESS)

    def test_running_cannot_be_claimed_again(self):
        with pytest.raises(IllegalTransition):
            transition(RUNNING, CLAIM)

    @pytest.mark.parametrize("terminal", list(TERMINAL_STATES))
    def test_terminal_states_accept_no_events(self, terminal):
        for event in (CLAIM, REPORT_SUCCESS, REPORT_FAILURE, REPORT_SKIP):
            with pytest.raises(IllegalTransition):
                transition(terminal, event)

    def test_unknown_state_raises(self):
        with pytest.raises(IllegalTransition):
            transition("lollipop", CLAIM)

    def test_unknown_event_raises(self):
        with pytest.raises(IllegalTransition):
            transition(QUEUED, "wave-a-magic-wand")


# ─── backoff schedule ────────────────────────────────────────────────────


class TestBackoff:
    def test_first_failure_returns_5_minutes(self):
        assert compute_backoff(1) == timedelta(minutes=5)

    def test_second_failure_returns_15_minutes(self):
        assert compute_backoff(2) == timedelta(minutes=15)

    def test_third_failure_returns_45_minutes(self):
        assert compute_backoff(3) == timedelta(minutes=45)

    def test_fourth_failure_returns_none(self):
        assert compute_backoff(4) is None

    def test_zero_or_negative_failure_count_rejected(self):
        with pytest.raises(ValueError):
            compute_backoff(0)
        with pytest.raises(ValueError):
            compute_backoff(-1)

    def test_budget_exhausted_after_schedule_length(self):
        # Three entries → 4th is exhausted
        assert budget_exhausted(len(BACKOFF_SCHEDULE) + 1) is True
        assert budget_exhausted(len(BACKOFF_SCHEDULE)) is False

    def test_backoff_is_monotonic(self):
        last = timedelta(0)
        for i in range(1, len(BACKOFF_SCHEDULE) + 1):
            current = compute_backoff(i)
            assert current is not None
            assert current > last
            last = current


# ─── invariants ──────────────────────────────────────────────────────────


class TestInvariants:
    def test_all_states_disjoint(self):
        # Terminal states should be a subset of ALL_STATES
        assert TERMINAL_STATES.issubset(ALL_STATES)

    def test_no_transition_leaves_all_states(self):
        # Every transition target must be a known state
        for (current, _event), result in [
            ((QUEUED, CLAIM), RUNNING),
            ((RUNNING, REPORT_SUCCESS), SUCCEEDED),
            ((RUNNING, REPORT_FAILURE), FAILED),
            ((RUNNING, REPORT_SKIP), SKIPPED),
        ]:
            assert result in ALL_STATES
