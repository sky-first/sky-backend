"""Agent service — business logic for agent CRUD and execution."""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.models.agent import Agent, AgentFinding
from src.models.user import User
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
        self.ai_client = AIServiceHTTPClient()

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

        # Personal mode invariant: a personal agent is owned by its creator.
        # Lucas's QA found that the FE wizard sometimes posts an empty /
        # placeholder scope_id when the user hasn't picked a Space (modo
        # PERSONAL), which then trips both the route-level RBAC check (which
        # compares scope_id to user.id) AND breaks downstream queries that
        # use scope_id as the personal owner identity. Normalising here
        # makes the creation path tolerant: scope=personal ALWAYS sets
        # scope_id to the creator's id so the resulting row is internally
        # consistent regardless of what the client posted.
        scope_lower = (data.scope.value if hasattr(data.scope, "value") else str(data.scope)).lower()
        resolved_scope_id = str(user_id) if scope_lower == "personal" else data.scope_id

        agent = Agent(
            name=data.name,
            archetype=data.archetype,
            scope=data.scope,
            scope_id=resolved_scope_id,
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
            auditable_only=bool(getattr(data, "auditable_only", False) or False),
            next_execution_at=next_run,
            created_by=user_id,
        )
        self.db.add(agent)
        await self.db.commit()

        # Ingest into knowledge graph — side-effect enrichment; never blocks the
        # create response. Capped at 5s so a slow AI cold-start (vectorization)
        # doesn't hold open the HTTP connection past the frontend's 60s timeout.
        try:
            import asyncio
            space_id = str(data.scope_id) if data.scope == "space" and data.scope_id else None
            crew_id = str(data.scope_id) if data.scope == "crew" and data.scope_id else None
            await asyncio.wait_for(
                self.ai_client.ingest_knowledge_graph({
                    "id": str(agent.id),
                    "entity_type": "agent",
                    "name": agent.name,
                    "scope": agent.scope,
                    "space_id": space_id,
                    "crew_id": crew_id,
                    "owner_user_id": str(user_id),
                    "entity_details": {"monitor_type": agent.monitor_type, "focus": agent.focus},
                }),
                timeout=5.0,
            )
        except Exception as exc:
            logger.warning(f"AI ingest failed or timed out for agent {agent.id}: {exc}")

        # Re-fetch with findings eagerly loaded. AgentListResponse no
        # longer serializes findings (see schemas/agent.py), but other
        # callers of the returned Agent (e.g. AI ingest hooks) may walk
        # the relationship, and keeping it pre-loaded avoids surprise
        # lazy-loads in the async session.
        return await self.repo.get_with_findings(agent.id)

    async def _require_can_mutate(self, agent: Agent, user: User, action: str = "agents.delete") -> None:
        """Apply the same policy we use for every other mutable entity:

        1. Personal agent: only the owner (=``scope_id``) may touch it.
        2. Creator bypass for Space/Crew/Org scopes — the user who
           created it can always delete/update.
        3. Otherwise, RBAC must grant the action key passed in
           (``agents.edit`` for updates/pause/resume; ``agents.delete``
           for deletion) in the space the agent lives in.

        Red-team HI-002 (2026-04-23): before this check, any
        authenticated user could DELETE or UPDATE ANY agent.

        2026-04-25 (CI red fix): ``action`` was hard-coded to
        ``agents.delete`` here regardless of caller, which silently
        gated every mutation behind delete permission — Navigator had
        ``agents.edit`` but no ``agents.delete``, so update_agent
        returned 403 even though the route-level
        ``RBACService.assert_permission(..., "agents.edit")`` had
        already passed. Parameterising restores the asymmetry.
        """
        from uuid import UUID as _UUID

        from fastapi import HTTPException as _HTTPException
        from fastapi import status as _status

        scope = (agent.scope or "").lower()

        # Personal: scope_id IS the owner user id.
        if scope == "personal":
            try:
                owner_id = _UUID(str(agent.scope_id))
            except Exception:
                owner_id = None
            if owner_id != user.id:
                raise _HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="Not found")
            return

        # Creator bypass for collaborative scopes.
        if agent.created_by == user.id:
            return

        # Fall through to RBAC. Resolve space_id if the scope is space-
        # or crew-bound (crew_ids live inside a space; use the agent's
        # space_id column if set, otherwise treat scope_id as space_id
        # for scope=="space").
        space_id = None
        if scope == "space":
            try:
                space_id = _UUID(str(agent.scope_id))
            except Exception:
                space_id = None

        from src.services.rbac_service import RBACService
        await RBACService(self.db).assert_permission(
            user, action, space_id=space_id
        )

    async def update_agent(self, agent_id: UUID, data: AgentUpdate, user: User) -> Agent:
        # Load with findings eager-loaded. AgentListResponse no longer
        # serializes findings (see schemas/agent.py), but keeping the
        # relationship hydrated here is cheap for a single-agent fetch
        # and shields any downstream code that might walk it inside the
        # async session.
        agent = await self.repo.get_with_findings(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        await self._require_can_mutate(agent, user, action="agents.edit")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(agent, key, value)

        await self.db.commit()
        # Re-fetch with findings so the response still has them populated
        # after the write. db.refresh() alone would not reload the
        # relationship.
        return await self.repo.get_with_findings(agent_id)

    async def delete_agent(self, agent_id: UUID, user: User) -> None:
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        await self._require_can_mutate(agent, user)
        await self.db.delete(agent)
        await self.db.commit()
        logger.info(f"Agent deleted: {agent_id} by user {user.id}")

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

    # ─── Add finding to page ───

    @staticmethod
    def _viz_kind_to_widget_type(viz_kind: Optional[str]) -> str:
        """Map a finding's viz_kind to the Widget.type the FE renders.

        Widget.type allow-list (see schemas/widget.py): chart | kpi |
        table | ai-box | text | insight | infographic | shape. The
        Pulse FE chart picker emits a richer set of viz_kind tokens
        (bar, line, donut, pie, kpi, big_number, delta, range,
        heatmap, sparkline, text, list) — we collapse them into the
        Widget allow-list here so the row passes the WidgetCreate
        validator and the renderer picks the right component from
        widget.data.viz_kind.
        """
        if not viz_kind:
            return "insight"
        kind = viz_kind.strip().lower()
        chart_kinds = {
            "bar", "line", "donut", "pie", "heatmap", "sparkline", "range", "area"
        }
        if kind in chart_kinds:
            return "chart"
        if kind in ("kpi", "big_number", "delta"):
            return "kpi"
        if kind in ("table", "list"):
            return "table"
        # Default: a rich card with title/description/rows — the FE
        # already renders this for findings with tabular evidence.
        return "insight"

    async def add_finding_to_page(
        self,
        *,
        agent_id: UUID,
        finding_id: UUID,
        page_id: UUID,
        user: User,
        position: Optional[dict] = None,
        size: Optional[dict] = None,
    ) -> dict:
        """Materialise an AgentFinding as a Widget on the target page.

        Previously the "Add to page" CTA in the FE finding card only sent
        the description text to the page (it called the generic POST
        /widgets endpoint with type='text'). Charts and KPIs were lost
        because the AgentFinding's rows + viz_kind were never read on
        this path.

        The new flow reads ``finding.viz_kind`` and ``finding.rows`` and
        constructs a fully-formed Widget so the page renders the same
        visualisation the user saw in the Cockpit card. The agent's
        connection_id is propagated so the widget can refresh data later.

        Returns a dict that maps cleanly onto AddFindingToPageResponse.
        """
        from src.models.page import Page
        from src.models.widget import Widget
        from sqlalchemy import select as _select

        # Load the finding and confirm it belongs to the agent named in
        # the URL — otherwise a malicious caller could attach somebody
        # else's finding to their own page.
        finding_q = await self.db.execute(
            _select(AgentFinding).where(AgentFinding.id == finding_id)
        )
        finding = finding_q.scalar_one_or_none()
        if finding is None or finding.agent_id != agent_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found"
            )

        agent_q = await self.db.execute(
            _select(Agent).where(Agent.id == agent_id)
        )
        agent = agent_q.scalar_one_or_none()
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
            )

        page_q = await self.db.execute(
            _select(Page).where(Page.id == page_id)
        )
        page = page_q.scalar_one_or_none()
        if page is None or page.deleted_at:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Page not found"
            )

        widget_type = self._viz_kind_to_widget_type(finding.viz_kind)

        # Pull a refresh-capable connection — the agent's first
        # connection_id when present, otherwise the finding's own
        # connection_id (set by the SSE stream when it picked one).
        refresh_connection_id: Optional[UUID] = None
        if agent.connection_ids:
            try:
                refresh_connection_id = UUID(str(agent.connection_ids[0]))
            except (ValueError, TypeError):
                refresh_connection_id = None
        if refresh_connection_id is None and finding.connection_id:
            refresh_connection_id = finding.connection_id

        # Build the widget payload. Frontend Cockpit picks columns/rows
        # from data.rows and the chart kind from data.viz_kind. The
        # description / reasoning surface as the card body.
        widget_data = {
            "title": finding.title,
            "description": finding.description,
            "viz_kind": finding.viz_kind,
            "rows": finding.rows or None,
            "source": "agent_finding",
            "finding_id": str(finding.id),
            "agent_id": str(agent.id),
            "confidence": finding.confidence,
            "reasoning": finding.reasoning,
            "recommendation": finding.recommendation,
        }

        widget = Widget(
            page_id=page_id,
            type=widget_type,
            title=(finding.title or "Agent finding")[:255],
            position=position or {"x": 0, "y": 0},
            size=size or {"width": 480, "height": 320},
            data=widget_data,
            config=None,
            connection_id=refresh_connection_id,
            created_by=user.id,
            created_by_agent_id=agent.id,
            source="agent",
        )
        self.db.add(widget)

        # Stamp the finding so the UI can show "Added to page X" and
        # the user does not re-add it accidentally.
        finding.added_to_page_id = page_id

        await self.db.commit()
        await self.db.refresh(widget)

        return {
            "widget_id": widget.id,
            "page_id": page_id,
            "finding_id": finding_id,
            "widget_type": widget_type,
        }
