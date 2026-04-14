"""Agent-run state machine — pure logic (no DB).

The state machine the Celery beat + worker in iteration 1.7 will follow.
Kept as a separate module so it can be exhaustively unit-tested without
a DB fixture and mutation-tested cheaply.

States:
  queued    — beat has enqueued a run; worker has not picked it up yet
  running   — a worker has claimed it and is executing
  succeeded — the AI service returned and we persisted the result
  failed    — the AI service errored or the worker timed out
  skipped   — the run completed but delta_kind=='none' so nothing was
              written as a notification/widget update; row preserved for audit

Transitions:
  queued    -> running   (worker claim)
  running   -> succeeded (AI service returned, result persisted)
  running   -> failed    (AI service errored / worker timeout)
  running   -> skipped   (delta_kind='none'; silent run)
  any other edge is illegal and raises IllegalTransition.

Retry budget:
  On failed, the agent's `consecutive_failures` counter increments.
  While counter <= len(BACKOFF_SCHEDULE), a new run is scheduled at
  `now + BACKOFF_SCHEDULE[counter-1]`. Once the counter exceeds the
  schedule, the agent is flipped to status='error' and no further runs
  are scheduled until an admin resumes it.

  Default: [5 min, 15 min, 45 min] — so the 4th consecutive failure
  flips the agent to 'error'.
"""

from __future__ import annotations

from datetime import timedelta
from typing import FrozenSet, Mapping


# ─── State vocabulary ─────────────────────────────────────────────────────

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"

TERMINAL_STATES: FrozenSet[str] = frozenset({SUCCEEDED, FAILED, SKIPPED})
ALL_STATES: FrozenSet[str] = frozenset({QUEUED, RUNNING, *TERMINAL_STATES})


# ─── Transition table ─────────────────────────────────────────────────────

# Events the machine accepts. Each event is valid from a specific set of
# current states and yields a specific new state.
CLAIM = "claim"                  # queued → running
REPORT_SUCCESS = "report_success"  # running → succeeded
REPORT_FAILURE = "report_failure"  # running → failed
REPORT_SKIP = "report_skip"      # running → skipped

_TRANSITIONS: Mapping[tuple[str, str], str] = {
    (QUEUED, CLAIM): RUNNING,
    (RUNNING, REPORT_SUCCESS): SUCCEEDED,
    (RUNNING, REPORT_FAILURE): FAILED,
    (RUNNING, REPORT_SKIP): SKIPPED,
}


class IllegalTransition(Exception):
    """Raised when an event is applied from a state that cannot accept it."""


def transition(current: str, event: str) -> str:
    """Return the resulting state, or raise `IllegalTransition`."""
    if current not in ALL_STATES:
        raise IllegalTransition(f"unknown current state: {current!r}")
    key = (current, event)
    if key not in _TRANSITIONS:
        raise IllegalTransition(
            f"cannot apply event {event!r} from state {current!r}"
        )
    return _TRANSITIONS[key]


# ─── Retry schedule ───────────────────────────────────────────────────────

# Exponential-ish backoff. After the last entry, the agent flips to 'error'.
BACKOFF_SCHEDULE: tuple[timedelta, ...] = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=45),
)


def compute_backoff(failure_count: int) -> timedelta | None:
    """Return the retry delay after `failure_count` consecutive failures.

    `failure_count` is the number of failures INCLUDING the one just
    recorded. Returns None when the budget is exhausted — the caller
    should then flip the agent to status='error' and not reschedule.

    Examples:
        compute_backoff(1) -> timedelta(minutes=5)
        compute_backoff(2) -> timedelta(minutes=15)
        compute_backoff(3) -> timedelta(minutes=45)
        compute_backoff(4) -> None   (budget exhausted)
    """
    if failure_count < 1:
        raise ValueError(
            "failure_count must be >= 1 (counter must be bumped before "
            "computing backoff)"
        )
    idx = failure_count - 1
    if idx >= len(BACKOFF_SCHEDULE):
        return None
    return BACKOFF_SCHEDULE[idx]


def budget_exhausted(failure_count: int) -> bool:
    """True when the agent should be flipped to 'error'."""
    return compute_backoff(failure_count) is None
