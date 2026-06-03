"""Insight-mode agent service — create / read / update / delete.

Insight agents are scheduled re-runs of the query that produced a specific
widget. They inherit identity from the page the widget lives on (personal
→ user, crew → sp-crew, space → sp-space) via
`src.core.agent_identity.resolve_identity_for_page`.

RBAC contract:
  - create:  caller must own the widget (via its dashboard/page)
  - view:    caller must see the page containing the widget
  - mutate:  only the agent's created_by (or admin) can pause/resume/
             update/delete/run_now. This is intentionally stricter than
             scope-membership: a crew member can see but cannot override
             someone else's agent schedule.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_identity import resolve_identity_for_page
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.core.permissions import is_tenant_admin
from src.models.agent import Agent
from src.models.widget import Widget
from src.models.user import User
from src.schemas.insight_agent import (
    AgentScheduleConfig,
    InsightAgentCreate,
    InsightAgentUpdate,
)


# ─── Schedule helpers ─────────────────────────────────────────────────────

_UNIT_TO_DELTA = {
    "minute": lambda n: timedelta(minutes=n),
    "hour":   lambda n: timedelta(hours=n),
    "day":    lambda n: timedelta(days=n),
    "week":   lambda n: timedelta(weeks=n),
}


def _compute_next_run(schedule: AgentScheduleConfig, from_time: Optional[datetime] = None) -> datetime:
    base = from_time or datetime.utcnow()
    return base + _UNIT_TO_DELTA[schedule.interval_unit](schedule.interval_value)


# ─── Service ──────────────────────────────────────────────────────────────


class InsightAgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── helpers ──

    async def _get_or_404(self, agent_id: UUID) -> Agent:
        agent = (
            await self.db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        if agent is None or agent.monitor_type != "insight":
            raise NotFoundError("Insight agent not found")
        return agent

    def _can_mutate(self, agent: Agent, user: User) -> bool:
        return is_tenant_admin(user) or agent.created_by == user.id

    async def _load_widget_with_page(self, widget_id: UUID) -> tuple[Widget, "Page"]:
        from src.models.page import Page

        widget = (
            await self.db.execute(select(Widget).where(Widget.id == widget_id))
        ).scalar_one_or_none()
        if widget is None:
            raise NotFoundError(f"Widget {widget_id} not found")
        page = (
            await self.db.execute(select(Page).where(Page.id == widget.page_id))
        ).scalar_one_or_none()
        if page is None:
            raise NotFoundError("Widget has no page — orphaned")
        return widget, page

    # ── create ──

    async def create(self, user: User, payload: InsightAgentCreate) -> Agent:
        """Create a new insight agent bound to the given widget.

        The identity is resolved from the widget's page; the caller's user
        id is always recorded as `created_by` / `attributed_to_user`.
        """
        widget, page = await self._load_widget_with_page(payload.widget_id)
        resolved = await resolve_identity_for_page(
            db=self.db,
            page_id=page.id,
            creator_user_id=user.id,
        )

        now = datetime.utcnow()
        agent = Agent(
            name=payload.name or f"Insight agent for {widget.title or widget.id}",
            archetype="custom",
            monitor_type="insight",
            scope=(
                "crew" if resolved.crew_id
                else ("space" if resolved.space_id else "personal")
            ),
            scope_id=str(resolved.crew_id or resolved.space_id or user.id),
            status="active",
            frequency="daily",  # legacy column; schedule_jsonb is the truth
            connection_ids=[],
            # Identity
            identity_type=resolved.identity_type,
            service_principal_id=(
                resolved.identity_id if resolved.identity_type == "service_principal" else None
            ),
            created_by=user.id,
            # Insight linkage
            widget_id=widget.id,
            conversation_id=payload.conversation_id,
            # Schedule
            schedule_jsonb=payload.schedule.model_dump(mode="json"),
            ends_at=payload.schedule.ends_at,
            # Behaviour
            delta_strategy=payload.delta_strategy,
            notify_on_change=payload.notify_on_change,
            consecutive_failures=0,
            # Timestamps
            next_execution_at=_compute_next_run(payload.schedule, from_time=now),
            created_at=now,
            updated_at=now,
        )
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    # ── read ──

    async def get(self, agent_id: UUID, user: User) -> Agent:
        agent = await self._get_or_404(agent_id)
        # Viewable if: tenant-level admin, or creator, or scope member.
        # Membership check reuses the existing scope_id semantics
        # (crew/space id string).
        if is_tenant_admin(user) or agent.created_by == user.id:
            return agent
        # TODO when notification producer lands: allow crew/space members
        # to GET the agent details for transparency. For now, restrict
        # reads to the creator. This is safer (no information leak).
        raise NotFoundError("Insight agent not found")

    async def list_for_user(self, user: User) -> List[Agent]:
        """Return every insight agent the user can view — today, only their own."""
        result = await self.db.execute(
            select(Agent).where(
                Agent.monitor_type == "insight",
                Agent.created_by == user.id,
            ).order_by(Agent.created_at.desc())
        )
        return list(result.scalars().all())

    # ── update / lifecycle ──

    async def update(
        self, agent_id: UUID, user: User, payload: InsightAgentUpdate
    ) -> Agent:
        agent = await self.get(agent_id, user)
        if not self._can_mutate(agent, user):
            raise ForbiddenError("Only the agent creator can update it")

        now = datetime.utcnow()
        if payload.schedule is not None:
            agent.schedule_jsonb = payload.schedule.model_dump(mode="json")
            agent.ends_at = payload.schedule.ends_at
            # B6: schedule change recomputes next_execution_at from now
            agent.next_execution_at = _compute_next_run(payload.schedule, from_time=now)
        if payload.name is not None:
            agent.name = payload.name
        if payload.notify_on_change is not None:
            agent.notify_on_change = payload.notify_on_change
        if payload.delta_strategy is not None:
            agent.delta_strategy = payload.delta_strategy
        agent.updated_at = now

        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def pause(self, agent_id: UUID, user: User) -> Agent:
        agent = await self.get(agent_id, user)
        if not self._can_mutate(agent, user):
            raise ForbiddenError("Only the agent creator can pause it")
        if agent.status == "ended":
            raise BadRequestError("Ended agents cannot be paused")
        agent.status = "paused"
        agent.next_execution_at = None  # worker won't pick it up
        agent.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def resume(self, agent_id: UUID, user: User) -> Agent:
        agent = await self.get(agent_id, user)
        if not self._can_mutate(agent, user):
            raise ForbiddenError("Only the agent creator can resume it")
        if agent.status == "ended":
            raise BadRequestError("Ended agents cannot be resumed")
        if not agent.schedule_jsonb:
            raise BadRequestError("Agent has no schedule — cannot resume")
        agent.status = "active"
        agent.consecutive_failures = 0
        # B8: resume → next run is immediate so the user sees feedback fast
        agent.next_execution_at = datetime.utcnow()
        agent.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def run_now(self, agent_id: UUID, user: User) -> Agent:
        """B10 — schedule the agent to run on the next beat tick.

        In Phase 1 (no worker yet) this just sets next_execution_at=now.
        The Celery beat in iteration 1.7 will pick it up on the next poll.
        """
        agent = await self.get(agent_id, user)
        if not self._can_mutate(agent, user):
            raise ForbiddenError("Only the agent creator can run it manually")
        if agent.status == "ended":
            raise BadRequestError("Ended agents cannot be run manually")
        agent.next_execution_at = datetime.utcnow()
        # Ensure the agent is active so beat picks it up — resume-like semantics
        if agent.status == "paused":
            agent.status = "active"
        agent.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def delete(self, agent_id: UUID, user: User) -> None:
        """B9 — move to status='ended'. Runs and findings preserved for audit."""
        agent = await self.get(agent_id, user)
        if not self._can_mutate(agent, user):
            raise ForbiddenError("Only the agent creator can delete it")
        agent.status = "ended"
        agent.next_execution_at = None
        agent.updated_at = datetime.utcnow()
        await self.db.commit()
