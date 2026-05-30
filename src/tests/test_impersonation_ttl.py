"""Console impersonation TTL helper (Gap #6).

The Console row doesn't (yet) carry ``expires_at``; the helper computes
it from ``started_at + IMPERSONATION_TTL`` and rolls (started_at,
ended_at, expires_at) into one of ``"active" | "expired" | "ended"``.

These are unit-level checks against the helper itself — the routes
that wire it in are exercised by the existing console-API integration
tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.core.impersonation_ttl import (
    IMPERSONATION_TTL,
    compute_expires_at,
    status_for,
)


def _row(started_at, ended_at=None):
    return SimpleNamespace(started_at=started_at, ended_at=ended_at)


def test_compute_expires_at_adds_ttl():
    start = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    assert compute_expires_at(start) == start + IMPERSONATION_TTL


def test_compute_expires_at_assumes_utc_when_naive():
    start_naive = datetime(2026, 5, 30, 12, 0)
    exp = compute_expires_at(start_naive)
    assert exp.tzinfo is not None
    assert exp == start_naive.replace(tzinfo=timezone.utc) + IMPERSONATION_TTL


def test_status_active_within_window():
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert status_for(_row(start)) == "active"


def test_status_expired_past_ttl():
    start = datetime.now(timezone.utc) - (IMPERSONATION_TTL + timedelta(minutes=1))
    assert status_for(_row(start)) == "expired"


def test_status_ended_short_circuits_ttl():
    """Explicit close always wins, even when the TTL is in the future."""
    start = datetime.now(timezone.utc) - timedelta(minutes=2)
    ended = start + timedelta(minutes=1)
    assert status_for(_row(start, ended_at=ended)) == "ended"


def test_status_ended_short_circuits_when_ttl_already_passed():
    start = datetime.now(timezone.utc) - (IMPERSONATION_TTL + timedelta(minutes=5))
    ended = start + timedelta(minutes=1)
    assert status_for(_row(start, ended_at=ended)) == "ended"
