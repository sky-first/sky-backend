"""Agent revocation worker — Celery beat task for periodic_sweep.

Master plan §12 + W12 follow-up.

Runs every 15 minutes (configured in celery_app.beat_schedule). For
every ACTIVE agent, re-checks whether the creator still belongs to the
agent's scope (Space or Crew). When membership has been removed but
the event-driven hook missed (e.g. a stale connection during the
remove call), the sweep pauses the orphan agent.

This is the safety net behind the synchronous wire-in in
``space_service.remove_space_member`` / ``crew_service.remove_crew_member``.
The sync hook is best-effort (failures are logged + swallowed); the
sweep guarantees eventual consistency.

Idempotent — running it twice in a row is a no-op the second time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _sweep_async() -> Dict[str, Any]:
    """Open a DB session and ask AgentRevocationService to do the work."""
    from src.config.database import AsyncSessionLocal
    from src.services.agent_revocation_service import AgentRevocationService

    async with AsyncSessionLocal() as db:
        svc = AgentRevocationService(db)
        result = await svc.periodic_sweep()
        if result.paused_agent_ids:
            await db.commit()
            logger.warning(
                "Periodic sweep paused %d orphan agent(s): %s",
                len(result.paused_agent_ids),
                [str(a) for a in result.paused_agent_ids],
            )
        else:
            logger.debug("Periodic sweep — no orphans found")
        return {
            "paused": len(result.paused_agent_ids),
            "reason": result.reason,
        }


@celery_app.task(name="src.workers.agent_revocation_worker.sweep_orphan_agents")
def sweep_orphan_agents() -> Dict[str, Any]:
    """Celery entrypoint. Returns ``{paused: N, reason: ...}`` so the
    Flower UI shows a useful payload."""
    try:
        return _run_async(_sweep_async())
    except Exception as e:
        logger.exception("Periodic sweep failed: %s", e)
        # Fail-open — the next tick will retry. Don't bubble to celery
        # because a permanent failure mode would hammer the queue.
        return {"paused": 0, "error": str(e)}
