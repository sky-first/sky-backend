"""Provisioning workflow engine — webhook ingestion + SSE plumbing.

The Console (``POST /api/console/v1/tenants``) writes a
``ProvisioningJob`` row and queues a Celery task that dispatches a
``workflow_dispatch`` against the ``sky-poc-infra`` GitHub Actions
workflow ``onboard-client.yml``. That workflow then phones home at the
start/success/failure of every phase via a signed HTTP webhook to
``POST /api/console/v1/jobs/webhook``.

This module owns three things:

* HMAC signature compute / verify (used by both the worker and the
  webhook route).
* ``ingest_event`` — the single source of truth for what a webhook
  payload does to the DB:
  - appends a row to ``provisioning_job_events``;
  - advances ``ProvisioningJob.current_phase`` on a canonical
    ``succeeded`` transition;
  - marks the job ``FAILED`` (with ``completed_at``) on any
    ``failed`` event;
  - marks the job ``SUCCESS`` once the terminal ``report`` phase
    succeeds;
  - publishes the event JSON on the Redis pub/sub channel
    ``provisioning_job_events:<job_id>``.
* ``replay_events`` + ``subscribe_events`` — used by the SSE route to
  catch a late subscriber up and tail new events live.

Design note: every helper takes the ``AsyncSession`` from the caller
so unit tests can drive the lifecycle without spinning Redis. The
Redis publish is best-effort and swallowed on failure — the DB row
is the system of record.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.internal_console import (
    PROVISIONING_PHASES,
    ProvisioningJob,
    ProvisioningJobEvent,
    ProvisioningJobEventLevel,
    ProvisioningJobEventStatus,
    ProvisioningJobStatus,
)


logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────

PROVISIONING_WEBHOOK_SECRET_ENV = "PROVISIONING_WEBHOOK_SECRET"
"""Env var that holds the HMAC-SHA256 secret shared with GH Actions.

Rotated together with the GitHub repository secret of the same name. A
missing / empty env var disables signature verification entirely with a
loud warning — only acceptable in local dev. Tests pass the secret
directly to ``compute_signature`` / ``verify_signature``.
"""

WEBHOOK_SIGNATURE_HEADER = "X-Signature"
"""HTTP header carrying the hex HMAC. The workflow sends raw hex (no
``sha256=`` prefix) to keep the comparator trivial."""

REDIS_CHANNEL_PREFIX = "provisioning_job_events"
"""Pub/sub channel prefix; full channel is ``<prefix>:<job_id>``."""

SSE_HEARTBEAT_SECONDS = 25
"""Heartbeat interval for the SSE route. < 30s to survive most proxies."""


# ── Webhook payload ────────────────────────────────────────────────


@dataclass
class WebhookPayload:
    """Strongly-typed view of the JSON body GH Actions POSTs to us."""

    job_id: str
    phase: str
    status: str
    level: str = ProvisioningJobEventLevel.INFO.value
    message: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebhookPayload":
        """Build from an already-decoded JSON body.

        Raises ``ValueError`` if a required field is missing. We
        deliberately don't reject unknown phases / statuses here — the
        CHECK constraint will fail the INSERT and the route surfaces it
        as a 422. That keeps validation centralised in the DB schema.
        """
        required = ("job_id", "phase", "status")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"webhook payload missing fields: {missing}")
        return cls(
            job_id=str(data["job_id"]),
            phase=str(data["phase"]),
            status=str(data["status"]),
            level=str(data.get("level") or ProvisioningJobEventLevel.INFO.value),
            message=data.get("message"),
            metadata=dict(data.get("metadata") or {}),
            timestamp=data.get("timestamp"),
        )


# ── Signing ────────────────────────────────────────────────────────


def compute_signature(secret: str, body_bytes: bytes) -> str:
    """Return the hex HMAC-SHA256 of ``body_bytes`` keyed by ``secret``.

    Empty / None secret is treated as ``""`` deliberately — callers (the
    worker dispatching, the tests) get a deterministic value they can
    assert on; the verifier rejects unsigned-equivalent requests anyway.
    """
    key = (secret or "").encode("utf-8")
    return hmac.new(key, body_bytes, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body_bytes: bytes, signature: str) -> bool:
    """Constant-time compare against the expected HMAC.

    Returns False if ``secret`` is empty (we treat the absence of a
    configured secret as a fail-closed default) or if the hex strings
    differ.
    """
    if not secret:
        return False
    if not signature:
        return False
    expected = compute_signature(secret, body_bytes)
    # ``compare_digest`` is constant-time over equal-length inputs.
    return hmac.compare_digest(expected, signature.strip())


# ── Phase progression helper ───────────────────────────────────────


def _next_phase(current: Optional[str], event_phase: str) -> Optional[str]:
    """Return the new value for ``ProvisioningJob.current_phase``.

    The rule: ``current_phase`` only advances forward through
    ``PROVISIONING_PHASES``. Out-of-order succeeded events (a retry, a
    bug in the workflow) never roll the pointer backwards. Returns
    ``None`` when no advance should happen so the caller can no-op.
    """
    if event_phase not in PROVISIONING_PHASES:
        return None
    new_idx = PROVISIONING_PHASES.index(event_phase)
    if current is None:
        return event_phase
    if current not in PROVISIONING_PHASES:
        # Garbage in current — overwrite if the event is canonical.
        return event_phase
    if new_idx >= PROVISIONING_PHASES.index(current):
        return event_phase
    return None


# ── Redis pub/sub ──────────────────────────────────────────────────


def _channel(job_id: Any) -> str:
    return f"{REDIS_CHANNEL_PREFIX}:{job_id}"


async def _publish(job_id: Any, payload: dict[str, Any]) -> None:
    """Best-effort publish on the per-job channel.

    Lazy-imports the redis config to keep this module test-friendly
    (the unit tests for ``ingest_event`` shouldn't need a real Redis).
    """
    try:
        from src.config.redis import get_redis

        client = await get_redis()
        if client is None:
            return
        await client.publish(_channel(job_id), json.dumps(payload, default=str))
    except Exception as exc:  # pragma: no cover — Redis outage is non-fatal
        logger.warning(
            "provisioning_workflow: failed to publish event for job %s: %s",
            job_id,
            exc,
        )


# ── Public API ─────────────────────────────────────────────────────


async def ingest_event(
    db: AsyncSession, payload: WebhookPayload
) -> ProvisioningJobEvent:
    """Persist a webhook event and advance the parent job state.

    Lifecycle rules:
    * Every payload appends one ``ProvisioningJobEvent`` row.
    * ``status == 'succeeded'`` on a canonical phase advances
      ``ProvisioningJob.current_phase`` forward (never back).
    * ``status == 'succeeded'`` on the terminal ``report`` phase marks
      the job ``SUCCESS`` with ``completed_at = now``.
    * ``status == 'failed'`` (any phase) marks the job ``FAILED`` with
      ``completed_at = now`` and ``error_message = payload.message``.
    * The first time we see any event for a still-``pending`` job we
      bump it to ``RUNNING`` so the dashboard stops showing "queued".

    Returns the freshly inserted event row so the caller (HTTP route)
    can echo back something the workflow can correlate.
    """
    try:
        job_uuid = uuid.UUID(payload.job_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid job_id: {payload.job_id!r}") from exc

    job = (
        await db.execute(select(ProvisioningJob).where(ProvisioningJob.id == job_uuid))
    ).scalar_one_or_none()
    if job is None:
        raise ValueError(f"job_not_found: {payload.job_id}")

    event = ProvisioningJobEvent(
        job_id=job_uuid,
        phase=payload.phase,
        status=payload.status,
        level=payload.level,
        message=payload.message,
        event_metadata=payload.metadata or {},
    )
    db.add(event)

    # Pending → Running on first event.
    if job.status == ProvisioningJobStatus.PENDING.value:
        job.status = ProvisioningJobStatus.RUNNING.value

    if payload.status == ProvisioningJobEventStatus.SUCCEEDED.value:
        advance = _next_phase(job.current_phase, payload.phase)
        if advance is not None:
            job.current_phase = advance
        # Terminal phase succeeds → job complete.
        if payload.phase == PROVISIONING_PHASES[-1]:
            job.status = ProvisioningJobStatus.SUCCESS.value
            job.completed_at = datetime.now(timezone.utc)

    elif payload.status == ProvisioningJobEventStatus.FAILED.value:
        job.status = ProvisioningJobStatus.FAILED.value
        job.completed_at = datetime.now(timezone.utc)
        if payload.message:
            job.error_message = payload.message

    await db.flush()

    # Push out on the per-job channel for any live SSE subscriber. We
    # carry the freshly-assigned id + created_at so the consumer can
    # de-duplicate against the replay it already received.
    await _publish(
        job.id,
        {
            "id": str(event.id),
            "job_id": str(event.job_id),
            "phase": event.phase,
            "status": event.status,
            "level": event.level,
            "message": event.message,
            "metadata": event.event_metadata,
            "created_at": (event.created_at or datetime.now(timezone.utc)).isoformat(),
        },
    )

    return event


async def replay_events(
    db: AsyncSession, job_id: Any
) -> list[ProvisioningJobEvent]:
    """Return every event for ``job_id`` in chronological order.

    Used by the SSE endpoint to catch a late subscriber up before
    switching to the Redis tail.
    """
    if isinstance(job_id, str):
        try:
            job_id = uuid.UUID(job_id)
        except ValueError as exc:
            raise ValueError(f"invalid job_id: {job_id!r}") from exc
    rows = (
        await db.execute(
            select(ProvisioningJobEvent)
            .where(ProvisioningJobEvent.job_id == job_id)
            .order_by(ProvisioningJobEvent.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


async def subscribe_events(job_id: Any) -> AsyncIterator[dict[str, Any]]:
    """Yield published events from Redis pub/sub for ``job_id``.

    Yields decoded JSON dicts (same shape as ``ingest_event``'s
    publish call). Lazily acquires a Redis pubsub; on absence of Redis
    the iterator returns immediately so the caller falls back to
    heartbeat-only.
    """
    try:
        from src.config.redis import get_redis

        client = await get_redis()
    except Exception as exc:  # pragma: no cover — startup failure
        logger.warning("provisioning_workflow.subscribe: redis unavailable: %s", exc)
        return
    if client is None:
        return
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(_channel(job_id))
        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if msg is None:
                # Let the SSE route interleave heartbeats.
                await asyncio.sleep(0)
                continue
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                data = data.decode("utf-8")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                logger.warning(
                    "provisioning_workflow.subscribe: undecodable message: %r", data
                )
    finally:
        try:
            await pubsub.unsubscribe(_channel(job_id))
            await pubsub.aclose()
        except Exception:  # pragma: no cover
            pass


# ── Convenience for routes / workers ──────────────────────────────


def get_webhook_secret() -> str:
    """Read the configured shared secret. Empty string if unset."""
    return os.getenv(PROVISIONING_WEBHOOK_SECRET_ENV, "") or ""


def event_to_sse_dict(event: ProvisioningJobEvent) -> dict[str, Any]:
    """Serialize an event row into the wire shape the UI consumes."""
    return {
        "id": str(event.id),
        "job_id": str(event.job_id),
        "phase": event.phase,
        "status": event.status,
        "level": event.level,
        "message": event.message,
        "metadata": event.event_metadata or {},
        "created_at": (event.created_at or datetime.now(timezone.utc)).isoformat(),
    }


__all__ = [
    "PROVISIONING_WEBHOOK_SECRET_ENV",
    "WEBHOOK_SIGNATURE_HEADER",
    "REDIS_CHANNEL_PREFIX",
    "SSE_HEARTBEAT_SECONDS",
    "WebhookPayload",
    "compute_signature",
    "verify_signature",
    "ingest_event",
    "replay_events",
    "subscribe_events",
    "get_webhook_secret",
    "event_to_sse_dict",
]
