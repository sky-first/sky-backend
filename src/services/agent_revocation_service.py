"""W12 — agent privilege revocation.

Master plan §12. HI-002 follow-up.

When a user loses access to a scope (Space or Crew), every agent they
created that runs against that scope must STOP — otherwise the agent
keeps reading data through the orphaned creator's identity, persisting
privilege past the membership change.

This service runs:

  - On membership removal (called from ``space_service`` /
    ``crew_service`` after the row is deleted).
  - On user deactivation (called from ``user_service.deactivate``).
  - As a periodic janitor job (every 15min) for safety: re-checks every
    active agent and pauses any whose creator no longer belongs to the
    agent's scope.

The action is **pause**, not delete — the audit trail keeps the
configuration intact so a Space owner can review and re-activate or
discard. Reason is persisted on the agent (``status_reason``) and
emitted to the audit log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentScope, AgentStatus
from src.models.crew import CrewMember
from src.models.space import SpaceMember

logger = logging.getLogger(__name__)


# Reason codes (kept short — surfaces in audit / Slack alert).
REASON_CREATOR_LEFT_SPACE = "creator_left_space"
REASON_CREATOR_LEFT_CREW = "creator_left_crew"
REASON_CREATOR_DEACTIVATED = "creator_deactivated"
REASON_PERIODIC_SWEEP = "periodic_orphan_sweep"


@dataclass(frozen=True)
class RevocationResult:
    paused_agent_ids: List[UUID]
    reason: str


class AgentRevocationService:
    """Pauses agents whose creator no longer has access to the scope."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    #  Public — call sites in space/crew/user services
    # ------------------------------------------------------------------

    async def revoke_on_space_removal(
        self, *, user_id: UUID, space_id: UUID,
    ) -> RevocationResult:
        """User was just removed from ``space_id``. Pause every agent the
        user created that runs against this space (or a crew within it)."""
        return await self._pause_matching(
            creator_id=user_id,
            space_ids={space_id},
            reason=REASON_CREATOR_LEFT_SPACE,
        )

    async def revoke_on_crew_removal(
        self, *, user_id: UUID, crew_id: UUID,
    ) -> RevocationResult:
        return await self._pause_matching(
            creator_id=user_id,
            crew_ids={crew_id},
            reason=REASON_CREATOR_LEFT_CREW,
        )

    async def revoke_on_user_deactivation(
        self, *, user_id: UUID,
    ) -> RevocationResult:
        """User was deactivated → pause every active agent they created,
        regardless of scope. Service principals are unaffected."""
        return await self._pause_matching(
            creator_id=user_id,
            reason=REASON_CREATOR_DEACTIVATED,
        )

    async def periodic_sweep(self) -> RevocationResult:
        """Janitor pass — find agents whose creator's membership is gone
        and pause them. Runs every 15min via a Celery beat job (separate
        wire-in PR)."""
        paused: List[UUID] = []

        agents = (
            await self.db.execute(
                select(Agent).where(Agent.status == AgentStatus.ACTIVE.value)
            )
        ).scalars().all()

        for agent in agents:
            if agent.created_by is None:
                continue  # service principal or orphaned-by-design
            if not await self._creator_still_has_access(agent):
                await self._pause(agent, REASON_PERIODIC_SWEEP)
                paused.append(agent.id)

        if paused:
            await self.db.flush()
        return RevocationResult(paused_agent_ids=paused, reason=REASON_PERIODIC_SWEEP)

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    async def _pause_matching(
        self,
        *,
        creator_id: UUID,
        space_ids: Optional[Set[UUID]] = None,
        crew_ids: Optional[Set[UUID]] = None,
        reason: str,
    ) -> RevocationResult:
        """Pause every active agent matching the filter."""
        stmt = select(Agent).where(
            Agent.created_by == creator_id,
            Agent.status == AgentStatus.ACTIVE.value,
        )
        agents = (await self.db.execute(stmt)).scalars().all()

        paused: List[UUID] = []
        for agent in agents:
            if not self._agent_is_in_scope(agent, space_ids, crew_ids):
                continue
            await self._pause(agent, reason)
            paused.append(agent.id)

        if paused:
            await self.db.flush()
        return RevocationResult(paused_agent_ids=paused, reason=reason)

    @staticmethod
    def _agent_is_in_scope(
        agent: Agent,
        space_ids: Optional[Set[UUID]],
        crew_ids: Optional[Set[UUID]],
    ) -> bool:
        """When a filter is provided, the agent must intersect; when both
        filters are None, every agent matches (used by user-deactivation)."""
        if space_ids is None and crew_ids is None:
            return True

        if space_ids:
            try:
                aid = UUID(str(agent.scope_id))
            except (ValueError, TypeError):
                aid = None
            if agent.scope == AgentScope.SPACE.value and aid in space_ids:
                return True
            # Cross-space agent (organisation scope) that lists this space
            try:
                listed = {UUID(str(s)) for s in (agent.space_ids or [])}
            except (ValueError, TypeError):
                listed = set()
            if listed & space_ids:
                return True

        if crew_ids:
            try:
                aid = UUID(str(agent.scope_id))
            except (ValueError, TypeError):
                aid = None
            if agent.scope == AgentScope.CREW.value and aid in crew_ids:
                return True

        return False

    async def _pause(self, agent: Agent, reason: str) -> None:
        agent.status = AgentStatus.PAUSED.value
        # Persist the reason on the agent — added as a free-form column
        # that may not exist on legacy rows. Use setattr so we don't crash
        # on dialects without the column (SQLite tests share the model).
        if hasattr(agent, "status_reason"):
            agent.status_reason = reason
        logger.warning(
            "Agent %s paused (creator=%s reason=%s)",
            agent.id, agent.created_by, reason,
        )

    async def _creator_still_has_access(self, agent: Agent) -> bool:
        """Does the agent's creator still belong to the agent's scope?"""
        if agent.created_by is None:
            return True  # service principal — out of scope here

        if agent.scope == AgentScope.PERSONAL.value:
            return True  # personal agents are tied to the creator's existence

        if agent.scope == AgentScope.SPACE.value:
            try:
                space_id = UUID(str(agent.scope_id))
            except (ValueError, TypeError):
                return False
            row = (
                await self.db.execute(
                    select(SpaceMember.id).where(
                        SpaceMember.space_id == space_id,
                        SpaceMember.user_id == agent.created_by,
                    )
                )
            ).first()
            return row is not None

        if agent.scope == AgentScope.CREW.value:
            try:
                crew_id = UUID(str(agent.scope_id))
            except (ValueError, TypeError):
                return False
            row = (
                await self.db.execute(
                    select(CrewMember.id).where(
                        CrewMember.crew_id == crew_id,
                        CrewMember.user_id == agent.created_by,
                    )
                )
            ).first()
            return row is not None

        # Organisation scope — out of scope for this guard.
        return True


# ---------------------------------------------------------------------------
#  Pure helper for callers that want to chain
# ---------------------------------------------------------------------------


async def revoke_agents_when_user_leaves_space(
    db: AsyncSession, user_id: UUID, space_id: UUID,
) -> RevocationResult:
    return await AgentRevocationService(db).revoke_on_space_removal(
        user_id=user_id, space_id=space_id,
    )


async def revoke_agents_when_user_leaves_crew(
    db: AsyncSession, user_id: UUID, crew_id: UUID,
) -> RevocationResult:
    return await AgentRevocationService(db).revoke_on_crew_removal(
        user_id=user_id, crew_id=crew_id,
    )
