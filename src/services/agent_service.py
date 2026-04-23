"""Agent service — business logic for agent CRUD and execution."""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentFinding
from src.repositories.agent import AgentFindingRepository, AgentRepository
from src.schemas.agent import AgentCreate, AgentUpdate

logger = logging.getLogger(__name__)

# Coarse buckets — fine-grained cadence lives in schedule_jsonb.
# `once` and `manual` deliberately map to "no next run" — the scheduler
# checks for None before enqueueing, so leaving it unset disables
# auto-runs for these two modes.
FREQUENCY_HOURS = {
    "minutely": 1 / 60,  # fraction of an hour — converted via timedelta below
    "hourly": 1,
    "daily": 24,
    "weekly": 168,
    "monthly": 24 * 30,  # calendar-month approximation; good enough for cost forecast
}


def _compute_next_execution(frequency: str, schedule_jsonb: Optional[dict] = None) -> Optional[datetime]:
    """Next-run timestamp for the scheduler. `once` and `manual` return None
    so the agent never auto-fires. `schedule_jsonb.interval_value` lets
    the user express "every 3 hours" or "every 15 minutes" without a new
    enum bucket — defaults to 1 when absent."""
    if frequency in ("once", "manual"):
        return None
    hours = FREQUENCY_HOURS.get(frequency, 24)
    if schedule_jsonb and isinstance(schedule_jsonb, dict):
        try:
            multiplier = int(schedule_jsonb.get("interval_value") or 1)
            if multiplier > 1:
                hours = hours * multiplier
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc) + timedelta(hours=hours)
DEPTH_CYCLES = {"quick": 1, "standard": 3, "deep": 5}


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AgentRepository(db)
        self.finding_repo = AgentFindingRepository(db)

    async def list_agents(
        self,
        scope: Optional[str] = None,
        scope_id: Optional[str] = None,
        created_by: Optional[UUID] = None,
    ) -> List[Agent]:
        return await self.repo.list_by_scope(scope=scope, scope_id=scope_id, created_by=created_by)

    async def get_agent(self, agent_id: UUID) -> Agent:
        agent = await self.repo.get_with_findings(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        return agent

    async def get_agent_raw(self, agent_id: UUID) -> Optional[Agent]:
        """Fetch agent without findings, returns None if missing."""
        return await self.repo.get_by_id(agent_id)

    async def create_agent(self, data: AgentCreate, user_id: UUID) -> Agent:
        next_run = _compute_next_execution(
            data.frequency,
            getattr(data, "schedule_jsonb", None),
        )
        now = datetime.now(timezone.utc)  # noqa: F841 — kept for future audit fields

        agent = Agent(
            name=data.name,
            archetype=data.archetype,
            scope=data.scope,
            scope_id=data.scope_id,
            scope_name=data.scope_name,
            status="active",
            monitor_type=data.monitor_type or "question",
            focus=data.focus,
            custom_sql=data.custom_sql,
            chat_context=data.chat_context,
            frequency=data.frequency,
            depth=data.depth or "standard",
            connection_ids=data.connection_ids,
            table_ids=data.table_ids,
            selected_context=data.selected_context,
            space_ids=data.space_ids,
            relationship_types=data.relationship_types,
            next_execution_at=next_run,
            created_by=user_id,
        )
        self.db.add(agent)
        await self.db.commit()

        # Ingest the agent identity itself so the RAG knows this agent
        # exists and can recognise its scope when answering chat
        # questions like "what do my agents watch?". Failure logged +
        # swallowed — never block agent creation on a broken AI side.
        try:
            from src.ai.http_client import AIServiceHTTPClient
            ai_client = AIServiceHTTPClient()
            await ai_client.ingest_knowledge_graph({
                "id": str(agent.id),
                "entity_type": "agent",
                "name": agent.name,
                "description": agent.focus,
                "space_id": str(agent.scope_id) if agent.scope == "space" and agent.scope_id else None,
                "crew_id": str(agent.scope_id) if agent.scope == "crew" and agent.scope_id else None,
                "owner_user_id": str(user_id) if agent.scope == "personal" else None,
                "entity_details": {
                    "scope": agent.scope,
                    "monitor_type": agent.monitor_type,
                    "frequency": agent.frequency,
                    "created_by": str(user_id),
                },
            })
        except Exception as exc:
            logger.warning(f"AI ingest failed for agent {agent.id}: {exc}")

        # RE-FETCH with findings eager-loaded. Even though an agent starts
        # with zero findings, AgentListResponse (the response_model for
        # POST /) declares findings: List[...]. Without this eager load,
        # Pydantic's serialization triggers a lazy relationship access
        # outside the greenlet context, blowing up with 500.
        return await self.repo.get_with_findings(agent.id)

    async def update_agent(self, agent_id: UUID, data: AgentUpdate) -> Agent:
        # Load with findings eager-loaded because the endpoint's
        # response_model (AgentListResponse) now includes findings. Without
        # eager load, response serialization triggers a lazy-load on the
        # relationship inside FastAPI's async context, which blows up with
        # MissingGreenlet after ~5s and surfaces as a generic 500
        # "unexpected error" to the UI — exactly the bug the user hit on
        # every Save.
        agent = await self.repo.get_with_findings(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(agent, key, value)

        await self.db.commit()
        # Re-fetch with findings so the response still has them populated
        # after the write. db.refresh() alone would not reload the
        # relationship.
        return await self.repo.get_with_findings(agent_id)

    async def delete_agent(self, agent_id: UUID) -> None:
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        await self.db.delete(agent)
        await self.db.commit()
        logger.info(f"Agent deleted: {agent_id}")

    async def pause_agent(self, agent_id: UUID) -> Agent:
        # Same response_model-needs-findings reasoning as update_agent.
        agent = await self.repo.get_with_findings(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        agent.status = "paused"
        agent.next_execution_at = None
        await self.db.commit()
        return await self.repo.get_with_findings(agent_id)

    async def resume_agent(self, agent_id: UUID) -> Agent:
        agent = await self.repo.get_with_findings(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        agent.status = "active"
        agent.next_execution_at = _compute_next_execution(
            agent.frequency,
            getattr(agent, "schedule_jsonb", None),
        )
        await self.db.commit()
        return await self.repo.get_with_findings(agent_id)

    # ─── Findings ───

    async def list_findings(
        self, agent_id: UUID, include_dismissed: bool = False
    ) -> List[AgentFinding]:
        return await self.finding_repo.list_by_agent(agent_id, include_dismissed=include_dismissed)

    async def dismiss_finding(self, finding_id: UUID) -> AgentFinding:
        finding = await self.finding_repo.dismiss(finding_id)
        if not finding:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
        return finding
