"""Agent-run lifecycle service — persists runs + applies the state machine.

Used by the Celery beat (to enqueue) and the worker (to claim / report
outcomes). Every DB transition goes through one of these methods so the
state machine in `src.core.agent_run_state` is the single enforcement
point — there is no place in the codebase where an agent_execution row
should be updated directly.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_run_state import (
    CLAIM,
    QUEUED,
    REPORT_FAILURE,
    REPORT_SKIP,
    REPORT_SUCCESS,
    RUNNING,
    IllegalTransition,
    budget_exhausted,
    compute_backoff,
    transition,
)
from src.core.exceptions import NotFoundError
from src.models.agent import Agent, AgentExecution


class AgentRunService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── helpers ─────────────────────────────────────────────────────────

    async def _require_run(self, run_id: UUID) -> AgentExecution:
        run = (
            await self.db.execute(
                select(AgentExecution).where(AgentExecution.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError(f"AgentExecution {run_id} not found")
        return run

    async def _require_agent(self, agent_id: UUID) -> Agent:
        agent = (
            await self.db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        if agent is None:
            raise NotFoundError(f"Agent {agent_id} not found")
        return agent

    # ─── enqueue (beat → queued) ─────────────────────────────────────────

    async def enqueue(self, agent_id: UUID) -> AgentExecution:
        """Create a fresh queued run for the given agent."""
        agent = await self._require_agent(agent_id)
        run = AgentExecution(
            agent_id=agent.id,
            status=QUEUED,
            cycles_consumed=0,
            findings_count=0,
            attributed_to_user_id=agent.created_by,
            triggered_by_sp_id=agent.service_principal_id,
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    # ─── claim (worker → running) ────────────────────────────────────────

    async def claim(self, run_id: UUID) -> AgentExecution:
        """Move a queued run to running. Raises if the current state is
        not queued. Called by the worker after it picks up a job."""
        run = await self._require_run(run_id)
        new_state = transition(run.status, CLAIM)  # raises IllegalTransition
        run.status = new_state
        run.started_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(run)
        return run

    # ─── report outcomes ─────────────────────────────────────────────────

    async def report_success(
        self,
        run_id: UUID,
        *,
        result_hash: Optional[str] = None,
        result_payload: Optional[dict] = None,
        delta_kind: Optional[str] = None,
        delta_summary: Optional[str] = None,
        delta_tokens: Optional[int] = None,
        delta_cost_usd: Optional[Decimal] = None,
        llm_tokens_used: Optional[int] = None,
        llm_cost_usd: Optional[Decimal] = None,
        notification_id: Optional[UUID] = None,
    ) -> AgentExecution:
        """Record a successful run + reset the agent's failure counter."""
        run = await self._require_run(run_id)
        run.status = transition(run.status, REPORT_SUCCESS)

        now = datetime.utcnow()
        run.finished_at = now
        if run.started_at:
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)

        run.result_hash = result_hash
        run.result_payload = result_payload
        run.delta_kind = delta_kind
        run.delta_summary = delta_summary
        run.delta_tokens = delta_tokens
        run.delta_cost_usd = delta_cost_usd
        run.llm_tokens_used = llm_tokens_used
        run.llm_cost_usd = llm_cost_usd
        run.notification_id = notification_id

        # Reset the agent's consecutive-failures counter and project the
        # next run from the agent's schedule.
        agent = await self._require_agent(run.agent_id)
        agent.consecutive_failures = 0
        agent.last_execution_at = now
        agent.next_execution_at = _project_next_run_from_schedule(agent, now)
        agent.updated_at = now

        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def report_failure(
        self,
        run_id: UUID,
        *,
        error_message: str,
    ) -> AgentExecution:
        """Record a failed run; apply retry budget + exponential backoff.

        When the budget is exhausted the agent moves to status='error'
        and next_execution_at is cleared. Admins recover it manually.
        """
        run = await self._require_run(run_id)
        run.status = transition(run.status, REPORT_FAILURE)

        now = datetime.utcnow()
        run.finished_at = now
        run.error_message = error_message
        if run.started_at:
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)

        agent = await self._require_agent(run.agent_id)
        agent.consecutive_failures = (agent.consecutive_failures or 0) + 1
        agent.last_execution_at = now

        if budget_exhausted(agent.consecutive_failures):
            agent.status = "error"
            agent.next_execution_at = None
        else:
            backoff = compute_backoff(agent.consecutive_failures)
            # compute_backoff can only return None when budget is
            # exhausted; the `if` above covers that case.
            assert backoff is not None
            agent.next_execution_at = now + backoff

        agent.updated_at = now

        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def report_skip(self, run_id: UUID) -> AgentExecution:
        """Record a run that returned delta_kind='none' — no-op but
        preserves the row for audit and schedules the next regular run."""
        run = await self._require_run(run_id)
        run.status = transition(run.status, REPORT_SKIP)

        now = datetime.utcnow()
        run.finished_at = now
        run.delta_kind = "none"
        if run.started_at:
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)

        agent = await self._require_agent(run.agent_id)
        agent.consecutive_failures = 0  # a skipped run counts as a success
        agent.last_execution_at = now
        agent.next_execution_at = _project_next_run_from_schedule(agent, now)
        agent.updated_at = now

        await self.db.commit()
        await self.db.refresh(run)
        return run

    # ─── queue inspection ────────────────────────────────────────────────

    async def list_queued(self, limit: int = 10) -> List[AgentExecution]:
        """Return queued runs in FIFO order — used by the worker pick-up
        loop. In iteration 1.7 this gets a `FOR UPDATE SKIP LOCKED` clause
        so multiple workers don't double-claim; for now single-worker
        semantics are enough and the whole point of this method is to be
        the one place that defines the order."""
        result = await self.db.execute(
            select(AgentExecution)
            .where(AgentExecution.status == QUEUED)
            .order_by(AgentExecution.started_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ─── private ─────────────────────────────────────────────────────────────

def _project_next_run_from_schedule(agent: Agent, now: datetime) -> Optional[datetime]:
    """Compute the next_execution_at from the agent's schedule_jsonb.

    Returns None if the agent has no schedule (shouldn't happen for
    insight-mode agents, but guards older rows without one).
    """
    schedule = agent.schedule_jsonb
    if not schedule:
        return None
    value = int(schedule.get("interval_value", 0))
    unit = schedule.get("interval_unit")
    if value <= 0 or unit not in {"minute", "hour", "day", "week"}:
        return None
    from datetime import timedelta

    delta = {
        "minute": timedelta(minutes=value),
        "hour": timedelta(hours=value),
        "day": timedelta(days=value),
        "week": timedelta(weeks=value),
    }[unit]

    projected = now + delta
    if agent.ends_at and projected > agent.ends_at:
        return None
    return projected
