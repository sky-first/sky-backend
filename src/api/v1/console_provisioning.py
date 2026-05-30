"""Provisioning workflow REST surface — webhook ingestion + SSE.

Mounted under the same ``/api/console/v1`` prefix as the rest of the
Internal Console (see ``src.main``), this router carries the two
routes the workflow engine needs:

* ``POST /jobs/webhook`` — phoned-home by GitHub Actions every phase
  start / success / failure. Signed with HMAC-SHA256, NOT gated by
  ``require_sky_team`` (the workflow has no Sky-team session).
* ``GET /jobs/{job_id}/events`` — Server-Sent Events stream the
  Console UI subscribes to. Replays the full event history then
  tails the per-job Redis pub/sub channel until the client
  disconnects. Gated by ``require_sky_team``.

Kept in its own module to keep ``console.py`` from sprawling further —
the workflow surface area is self-contained (no audit-log writes, no
RBAC permission scoping; the webhook is system-to-system and the SSE
tail is read-only).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.console_auth import require_sky_team
from src.api.deps import get_db_session
from src.models.internal_console import ProvisioningJob
from src.models.user import User
from src.services.provisioning_workflow import (
    SSE_HEARTBEAT_SECONDS,
    WEBHOOK_SIGNATURE_HEADER,
    WebhookPayload,
    event_to_sse_dict,
    get_webhook_secret,
    ingest_event,
    replay_events,
    subscribe_events,
    verify_signature,
)


logger = logging.getLogger(__name__)


router = APIRouter()


# ── Webhook ────────────────────────────────────────────────────────


@router.post(
    "/jobs/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Phase webhook from GitHub Actions provisioning workflow",
)
async def provisioning_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    x_signature: Optional[str] = Header(default=None, alias=WEBHOOK_SIGNATURE_HEADER),
) -> dict:
    """Persist one phase event after verifying the HMAC signature.

    NOT protected by ``require_sky_team`` — the caller is the GH Actions
    workflow runner, identified only by the shared HMAC secret. A
    missing or wrong signature yields 401; a malformed JSON body or
    payload yields 422.
    """
    secret = get_webhook_secret()
    if not secret:
        # Fail closed in any environment that didn't bother to set the
        # secret — better to reject than silently accept unsigned events.
        logger.error(
            "provisioning webhook hit but PROVISIONING_WEBHOOK_SECRET is unset"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="webhook secret not configured",
        )

    body_bytes = await request.body()
    if not verify_signature(secret, body_bytes, x_signature or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )

    try:
        body = json.loads(body_bytes.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid JSON: {exc}",
        ) from exc

    try:
        payload = WebhookPayload.from_dict(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    try:
        event = await ingest_event(db, payload)
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("job_not_found"):
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=422, detail=msg) from exc

    return {"id": str(event.id), "accepted": True}


# ── SSE stream ─────────────────────────────────────────────────────


def _sse_format(data: dict, event: str = "message") -> str:
    """Encode a payload as one SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _heartbeat() -> str:
    return ": heartbeat\n\n"


@router.get(
    "/jobs/{job_id}/events",
    summary="Stream provisioning workflow events for a job (SSE)",
)
async def provisioning_events_stream(
    job_id: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Replay historical events then tail live events from Redis.

    Connection close from the client cancels the underlying async
    generator; the Redis pubsub is released by ``subscribe_events`` in
    its ``finally`` block.
    """
    # Fail fast if the job doesn't exist — saves the client from a
    # silent empty stream when they mistype the id.
    try:
        job_uuid = uuid.UUID(job_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    job = (
        await db.execute(select(ProvisioningJob).where(ProvisioningJob.id == job_uuid))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_gen() -> AsyncIterator[str]:
        # 1) Replay everything we have on disk so a late subscriber
        #    sees the full timeline without a server round-trip.
        try:
            history = await replay_events(db, job_uuid)
        except ValueError as exc:
            yield _sse_format({"error": str(exc)}, event="error")
            return

        for ev in history:
            yield _sse_format(event_to_sse_dict(ev), event="event")
            if await request.is_disconnected():
                return

        # 2) Tail Redis. Interleave heartbeats so proxies don't drop
        #    the connection on idle. We race the subscriber on a
        #    sleep so the heartbeat fires even when no events arrive.
        sub = subscribe_events(job_uuid)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    next_task = asyncio.create_task(sub.__anext__())
                except StopAsyncIteration:
                    # Redis not available — degrade to heartbeat-only.
                    next_task = None

                if next_task is None:
                    yield _heartbeat()
                    await asyncio.sleep(SSE_HEARTBEAT_SECONDS)
                    continue

                done, _pending = await asyncio.wait(
                    {next_task},
                    timeout=SSE_HEARTBEAT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if next_task in done:
                    try:
                        msg = next_task.result()
                    except StopAsyncIteration:
                        break
                    except Exception as exc:  # pragma: no cover
                        logger.warning("SSE subscriber error: %s", exc)
                        break
                    yield _sse_format(msg, event="event")
                else:
                    next_task.cancel()
                    yield _heartbeat()
        finally:
            try:
                await sub.aclose()  # type: ignore[attr-defined]
            except Exception:
                pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
