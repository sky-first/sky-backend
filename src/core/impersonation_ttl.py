"""Hard TTL on Console impersonation sessions.

Gap #6 from the 2026-05-30 security posture audit. The DB row had a
``started_at`` and an ``ended_at`` but no ``expires_at`` — sessions
that the operator forgot to close stayed "active" indefinitely, both
in the Console UI and in any future "is this actor still allowed to
proxy as the customer" check.

Rather than ship a schema migration on top of the messy 2026-05-30
alembic state, we compute the effective TTL at read time:

* ``IMPERSONATION_TTL`` (env-tunable; 1 hour by default) is added to
  ``started_at`` to produce ``expires_at``.
* ``status_for(row, now)`` rolls (started_at, ended_at, expires_at)
  into one of ``"active" | "expired" | "ended"`` so the response
  schema can populate the field without callers replicating the date
  math.

When we eventually ship the migration to persist ``expires_at`` on
the row itself, this helper stays — the column just provides
authority instead of computing it.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _ttl_seconds() -> int:
    raw = os.getenv("IMPERSONATION_TTL_SECONDS")
    if not raw:
        return 60 * 60  # 1 hour default
    try:
        n = int(raw)
    except ValueError:
        return 60 * 60
    # Refuse pathological values so a misconfigured deploy can't make
    # the TTL useless or so short it bricks the Console.
    if n < 60 or n > 24 * 60 * 60:
        return 60 * 60
    return n


IMPERSONATION_TTL = timedelta(seconds=_ttl_seconds())


def compute_expires_at(started_at: Optional[datetime]) -> Optional[datetime]:
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at + IMPERSONATION_TTL


def status_for(row: Any, now: Optional[datetime] = None) -> str:
    """Roll (started_at, ended_at, expires_at) into one of:

    * ``"ended"`` — the operator explicitly closed the session
    * ``"expired"`` — TTL elapsed without an explicit close
    * ``"active"`` — neither happened
    """
    ended_at = getattr(row, "ended_at", None)
    if ended_at is not None:
        return "ended"
    started_at = getattr(row, "started_at", None)
    expires_at = compute_expires_at(started_at)
    if expires_at is None:
        # No started_at — should never happen for a persisted row, but
        # the safe default is to consider it active rather than fake
        # an expiration.
        return "active"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return "expired" if current >= expires_at else "active"
