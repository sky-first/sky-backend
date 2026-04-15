"""Celery beat + worker for insight-mode agents.

Two tasks:

  schedule_insight_agents  — runs every minute; picks agents with
                             monitor_type='insight' AND status='active'
                             AND next_execution_at <= now, calls
                             AgentRunService.enqueue for each.

  execute_insight_run      — worker task, processes one queued
                             agent_execution. Claims it → calls the AI
                             service (mocked in Phase 1) → reports
                             success / failure back through
                             AgentRunService.

The AI service call is intentionally indirected through
`_call_ai_run_agent(...)` so Phase 2 (when HMAC-signed real calls land)
only has to replace that function — the queue → claim → report flow
stays stable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import AsyncSessionLocal
from src.core.exceptions import NotFoundError
from src.models.agent import Agent, AgentExecution
from src.models.notification import NotificationType
from src.schemas.notification import NotificationCreate
from src.services.agent_run_service import AgentRunService
from src.services.notification_service import NotificationService
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _emit_insight_notifications(
    db: AsyncSession,
    *,
    agent: Agent,
    run_id: UUID,
    delta_kind: Optional[str],
    delta_summary: Optional[str],
) -> None:
    """Emit up to two notifications per successful insight run.

    * INSIGHT_AGENT_RESULT — every completed run. Users mute this
      category when they only want material-delta pings.
    * INSIGHT_AGENT_MATERIAL — delta_kind == 'material' only. This is
      the "you should actually look at this" signal; kept distinct
      from RESULT so users can mute one without losing the other.

    Target user is `agent.created_by`. Both notifications carry a
    deep_link that opens the insight widget on the dashboard; the UI
    consumer resolves `entity_id` to the widget.
    """
    owner_id = agent.created_by
    if owner_id is None:
        # SP-owned agents have no human to ping here (audit record is
        # enough). If we need to fan out to crew admins later this is
        # the place to resolve them.
        return

    service = NotificationService(db)
    widget_id = str(agent.widget_id) if agent.widget_id else ""
    deep_link = f"/dashboard?insight={widget_id}" if widget_id else None

    result_title = f"{agent.name or 'Insight agent'} — run completed"
    description = (delta_summary or "").strip() or None

    # Feed-level notification — muted by default for power users.
    await service.create_notification(
        NotificationCreate(
            user_id=owner_id,
            type=NotificationType.INSIGHT_AGENT_RESULT.value,
            title=result_title,
            description=description,
            entity_type="agent_execution",
            entity_id=str(run_id),
            deep_link=deep_link,
        )
    )

    if (delta_kind or "").lower() == "material":
        material_title = f"{agent.name or 'Insight agent'} — material change"
        await service.create_notification(
            NotificationCreate(
                user_id=owner_id,
                type=NotificationType.INSIGHT_AGENT_MATERIAL.value,
                title=material_title,
                description=description,
                entity_type="agent_execution",
                entity_id=str(run_id),
                deep_link=deep_link,
            )
        )


# ─── Helpers ──────────────────────────────────────────────────────────────

def _run_async(coro):
    """Run an async coroutine from sync Celery context.

    Mirrors the pattern used by `src.workers.agent_worker`. Each Celery
    task invocation gets its own event loop so coroutines do not cross
    task boundaries.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed loop")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _call_ai_run_agent(
    agent: Agent, run: AgentExecution
) -> Dict[str, Any]:
    """Call the AI service's `/agents/run` endpoint.

    Phase 1: STUB. Returns a deterministic mock response so the pipeline
    is testable end-to-end without standing up the AI service. The body
    shape matches the master plan §6.2 response contract.

    Phase 2 replaces this function body with an HMAC-signed HTTP call to
    the AI service.
    """
    # Deterministic "first run" simulation. When result_hash is stable,
    # delta detection will flip subsequent runs to delta_kind='none'.
    fake_hash = f"stub-{agent.id}"
    return {
        "result_hash": fake_hash,
        "result_payload": {"rows": [], "schema": []},
        "delta": {"kind": "first_run", "summary": None},
        "tokens": {"in": 0, "out": 0},
        "cost_usd": 0.0,
        "duration_ms": 0,
        # Phase 2.10: Context-layer evidence trail. When the real AI
        # service lands, this dict carries the brain_doc_ids it
        # retrieved (UUIDs) and the classified intent string. The stub
        # returns empty so the `context_doc_ids` column falls back to
        # its default (empty array).
        "context": {"doc_ids": [], "intent": None},
    }


# ─── Beat: schedule due insight agents ────────────────────────────────────


@celery_app.task
def schedule_insight_agents() -> Dict[str, int]:
    """Enqueue every insight agent whose `next_execution_at` has passed."""

    async def _tick() -> int:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Agent).where(
                    Agent.monitor_type == "insight",
                    Agent.status == "active",
                    Agent.next_execution_at.is_not(None),
                    Agent.next_execution_at <= now,
                )
            )
            due = list(result.scalars().all())

            service = AgentRunService(db)
            enqueued = 0
            for agent in due:
                try:
                    run = await service.enqueue(agent.id)
                    execute_insight_run.delay(str(run.id))
                    enqueued += 1
                except Exception:
                    logger.exception(f"Failed to enqueue agent {agent.id}")
            return enqueued

    count = _run_async(_tick())
    logger.info(f"Insight agent scheduler: {count} runs enqueued")
    return {"enqueued": count}


# ─── Worker: process one queued run ───────────────────────────────────────


@celery_app.task(bind=True, max_retries=0)
def execute_insight_run(self, run_id: str) -> Dict[str, Any]:
    """Claim a queued agent_execution row, call the AI service, report.

    Failures are handled INSIDE the task (not by Celery retries): we want
    the state machine's exponential-backoff policy to be the single
    source of truth for retries. Celery's max_retries=0 keeps its own
    retry mechanism out of the way.
    """

    async def _process() -> Dict[str, Any]:
        run_uuid = UUID(run_id)
        async with AsyncSessionLocal() as db:
            service = AgentRunService(db)
            try:
                run = await service.claim(run_uuid)
            except NotFoundError:
                logger.warning(f"Run {run_id} disappeared before claim")
                return {"status": "missing"}

            agent = await service._require_agent(run.agent_id)
            try:
                response = await _call_ai_run_agent(agent, run)
            except Exception as err:
                logger.exception(
                    f"AI service call failed for run {run_id}: {err}"
                )
                await service.report_failure(
                    run_uuid, error_message=str(err)[:1000]
                )
                return {"status": "failed", "error": str(err)[:200]}

            delta_kind = (response.get("delta") or {}).get("kind")
            if delta_kind == "none":
                await service.report_skip(run_uuid)
                return {"status": "skipped"}

            ctx = response.get("context") or {}
            await service.report_success(
                run_uuid,
                result_hash=response.get("result_hash"),
                result_payload=response.get("result_payload"),
                delta_kind=delta_kind,
                delta_summary=(response.get("delta") or {}).get("summary"),
                context_doc_ids=ctx.get("doc_ids") or [],
                context_intent=ctx.get("intent"),
            )

            # Phase 3.3: notify the agent owner. Two levels:
            #   - INSIGHT_AGENT_MATERIAL on material deltas (user-facing
            #     "something changed you should look at").
            #   - INSIGHT_AGENT_RESULT for every completed run (feed
            #     entry — users usually mute this category but keep
            #     MATERIAL on).
            try:
                await _emit_insight_notifications(
                    db,
                    agent=agent,
                    run_id=run_uuid,
                    delta_kind=delta_kind,
                    delta_summary=(response.get("delta") or {}).get("summary"),
                )
            except Exception:
                # Notifications are side-effects; a failure here must
                # not roll back the successful run.
                logger.exception(
                    "notify_insight_run_failed run_id=%s agent_id=%s",
                    run_uuid, agent.id,
                )

            return {"status": "succeeded"}

    return _run_async(_process())
