"""Agent repository for database operations."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.agent import Agent, AgentExecution, AgentFinding
from src.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Agent)

    async def get_with_findings(self, agent_id: UUID) -> Optional[Agent]:
        result = await self.db.execute(
            select(Agent)
            .options(selectinload(Agent.findings))
            .where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def list_by_scope(
        self,
        scope: Optional[str] = None,
        scope_id: Optional[str] = None,
        created_by: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Agent]:
        query = select(Agent)
        if scope:
            query = query.where(Agent.scope == scope)
        if scope_id:
            query = query.where(Agent.scope_id == scope_id)
        if created_by:
            query = query.where(Agent.created_by == created_by)
        query = query.order_by(Agent.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_active_for_execution(self) -> List[Agent]:
        """Get all active agents that need execution."""
        result = await self.db.execute(
            select(Agent).where(Agent.status == "active")
        )
        return list(result.scalars().all())


class AgentFindingRepository(BaseRepository[AgentFinding]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentFinding)

    async def list_by_agent(
        self,
        agent_id: UUID,
        include_dismissed: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> List[AgentFinding]:
        query = select(AgentFinding).where(AgentFinding.agent_id == agent_id)
        if not include_dismissed:
            query = query.where(AgentFinding.dismissed == False)
        query = query.order_by(AgentFinding.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def dismiss(self, finding_id: UUID) -> Optional[AgentFinding]:
        from datetime import datetime, timezone
        await self.db.execute(
            update(AgentFinding)
            .where(AgentFinding.id == finding_id)
            .values(dismissed=True, dismissed_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        return await self.get_by_id(finding_id)


class AgentExecutionRepository(BaseRepository[AgentExecution]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentExecution)
