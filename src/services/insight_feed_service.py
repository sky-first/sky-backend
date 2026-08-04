"""Unified mobile Insights feed (BE-02, Sky Mobile).

Serves one machine-readable object per finding, unifying two sources:

* **agent** findings — attached to a registered ``Agent`` (scoped via that
  agent's Space/Crew), and
* **scan** findings — produced by the autonomous scan agent, carrying
  ``space_id`` directly (``agent_id`` is NULL).

Every read is scoped to the caller's **content plane** — the Spaces and Crews
they are actually a member of (no platform-role bypass; identical rule to the
legacy ``/agents/insights/all``). Pagination is a stable **keyset cursor** on
``(created_at DESC, id DESC)`` so inserts mid-paging never cause dupes or gaps.
Per-user ``reviewed``/``pinned`` state is joined from ``insight_state``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentFinding
from src.models.crew import CrewMember
from src.models.insight_state import InsightState
from src.models.space import SpaceMember
from src.schemas.insight_feed import InsightDetail, InsightFeedResponse, InsightItem

# A scan finding is "live" while it is recent (scans run every 1-24h); an agent
# finding is "live" while its agent is active + recently executed. Honest: this
# is "an agent is watching this", not a real-time metric stream.
_SCAN_LIVE_WINDOW = timedelta(hours=25)
_AGENT_LIVE_WINDOW = timedelta(days=2)


class InvalidCursor(Exception):
    """Raised for a malformed pagination cursor → the endpoint returns 400."""


class InsightFeedService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Scope (content plane) ───────────────────────────────────────────

    async def _member_scope(self, user_id: UUID) -> Tuple[List[UUID], List[UUID]]:
        space_ids = list(
            (
                await self.db.execute(
                    select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        crew_ids = list(
            (await self.db.execute(select(CrewMember.crew_id).where(CrewMember.user_id == user_id)))
            .scalars()
            .all()
        )
        return space_ids, crew_ids

    def _scope_where(self, user_id: UUID, space_ids: List[UUID], crew_ids: List[UUID]):
        """A finding is visible when it is a scan finding in one of my Spaces,
        OR an agent finding I own / whose Space or Crew I belong to."""
        space_strs = [str(s) for s in space_ids]  # Agent.scope_id is text
        crew_strs = [str(c) for c in crew_ids]

        clauses = []
        if space_ids:
            clauses.append(
                and_(
                    AgentFinding.source == "scan",
                    AgentFinding.space_id.in_(space_ids),
                )
            )
        agent_clauses = [Agent.created_by == user_id]
        if space_strs:
            agent_clauses.append(and_(Agent.scope == "space", Agent.scope_id.in_(space_strs)))
        if crew_strs:
            agent_clauses.append(and_(Agent.scope == "crew", Agent.scope_id.in_(crew_strs)))
        clauses.append(and_(AgentFinding.agent_id.isnot(None), or_(*agent_clauses)))
        return or_(*clauses)

    def _base_query(self, user_id: UUID):
        return (
            select(AgentFinding, Agent, InsightState)
            .select_from(AgentFinding)
            .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
            .outerjoin(
                InsightState,
                and_(
                    InsightState.finding_id == AgentFinding.id,
                    InsightState.user_id == user_id,
                ),
            )
        )

    @staticmethod
    def _apply_filter(query, filter_: str):
        if filter_ == "risk":
            return query.where(AgentFinding.type == "risk")
        if filter_ == "opportunity":
            return query.where(AgentFinding.type == "opportunity")
        if filter_ == "featured":
            return query.where(
                or_(InsightState.pinned_at.isnot(None), AgentFinding.severity == "high")
            )
        return query  # "all" / "latest"

    # ─── Feed ────────────────────────────────────────────────────────────

    async def list(
        self, user_id: UUID, filter_: str, cursor: Optional[str], limit: int
    ) -> InsightFeedResponse:
        space_ids, crew_ids = await self._member_scope(user_id)
        scope = self._scope_where(user_id, space_ids, crew_ids)

        query = self._base_query(user_id).where(scope).where(AgentFinding.dismissed.is_(False))
        query = self._apply_filter(query, filter_)

        if cursor:
            c_created, c_id = self._decode_cursor(cursor)
            query = query.where(
                or_(
                    AgentFinding.created_at < c_created,
                    and_(
                        AgentFinding.created_at == c_created,
                        AgentFinding.id < c_id,
                    ),
                )
            )

        query = query.order_by(AgentFinding.created_at.desc(), AgentFinding.id.desc()).limit(
            limit + 1
        )

        rows = (await self.db.execute(query)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._to_item(f, a, s) for (f, a, s) in rows]
        next_cursor = self._encode_cursor(rows[-1][0]) if has_more and rows else None
        counts = await self._counts(user_id, space_ids, crew_ids)
        return InsightFeedResponse(items=items, next_cursor=next_cursor, counts=counts)

    async def _counts(
        self, user_id: UUID, space_ids: List[UUID], crew_ids: List[UUID]
    ) -> Dict[str, int]:
        scope = self._scope_where(user_id, space_ids, crew_ids)
        by_type_rows = (
            await self.db.execute(
                select(AgentFinding.type, func.count())
                .select_from(AgentFinding)
                .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
                .where(scope)
                .where(AgentFinding.dismissed.is_(False))
                .group_by(AgentFinding.type)
            )
        ).all()
        by_type = {t: c for (t, c) in by_type_rows}

        featured = (
            await self.db.execute(
                select(func.count())
                .select_from(AgentFinding)
                .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
                .outerjoin(
                    InsightState,
                    and_(
                        InsightState.finding_id == AgentFinding.id,
                        InsightState.user_id == user_id,
                    ),
                )
                .where(scope)
                .where(AgentFinding.dismissed.is_(False))
                .where(
                    or_(
                        InsightState.pinned_at.isnot(None),
                        AgentFinding.severity == "high",
                    )
                )
            )
        ).scalar() or 0

        total = sum(by_type.values())
        return {
            "all": total,
            "latest": total,
            "risk": by_type.get("risk", 0),
            "opportunity": by_type.get("opportunity", 0),
            "insight": by_type.get("insight", 0),
            "featured": int(featured),
        }

    # ─── Detail ──────────────────────────────────────────────────────────

    async def detail(self, user_id: UUID, finding_id: str) -> Optional[InsightDetail]:
        row = await self._scoped_row(user_id, finding_id)
        if row is None:
            return None
        f, a, s = row
        base = self._to_item(f, a, s).model_dump()
        return InsightDetail(
            **base,
            description=f.description or "",
            stat_tiles=list(f.stat_tiles or []),
            viz_kind=f.viz_kind,
        )

    async def _scoped_row(self, user_id: UUID, finding_id: str):
        """The (finding, agent, state) tuple for ``finding_id`` IF it is in the
        caller's scope — else ``None`` (which the endpoint turns into 404, never
        a 403 that would leak the finding's existence)."""
        try:
            fid = UUID(str(finding_id))
        except (ValueError, TypeError):
            return None
        space_ids, crew_ids = await self._member_scope(user_id)
        scope = self._scope_where(user_id, space_ids, crew_ids)
        query = self._base_query(user_id).where(scope).where(AgentFinding.id == fid)
        return (await self.db.execute(query)).first()

    # ─── Review / pin (per-user, idempotent) ─────────────────────────────

    async def set_reviewed(self, user_id: UUID, finding_id: str, reviewed: bool) -> bool:
        return await self._set_flag(user_id, finding_id, "reviewed_at", reviewed)

    async def set_pinned(self, user_id: UUID, finding_id: str, pinned: bool) -> bool:
        return await self._set_flag(user_id, finding_id, "pinned_at", pinned)

    async def _set_flag(self, user_id: UUID, finding_id: str, column: str, value: bool) -> bool:
        row = await self._scoped_row(user_id, finding_id)
        if row is None:
            return False  # not in scope → endpoint returns 404
        finding = row[0]
        state = (
            await self.db.execute(
                select(InsightState)
                .where(InsightState.user_id == user_id)
                .where(InsightState.finding_id == finding.id)
            )
        ).scalar_one_or_none()
        if state is None:
            state = InsightState(user_id=user_id, finding_id=finding.id)
            self.db.add(state)
        setattr(state, column, datetime.now(timezone.utc) if value else None)
        state.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    # ─── Mapping helpers ─────────────────────────────────────────────────

    def _to_item(self, f: AgentFinding, agent, state) -> InsightItem:
        return InsightItem(
            id=str(f.id),
            severity=f.type,
            severity_level=f.severity,
            agent_name=f.agent_name or (agent.name if agent is not None else None),
            title=f.title,
            summary=(f.description or "")[:400],
            is_live=self._is_live(f, agent),
            series=list(f.series or []),
            created_at=f.created_at,
            reviewed=bool(state is not None and state.reviewed_at is not None),
            pinned=bool(state is not None and state.pinned_at is not None),
            deep_link=f"sky://insights/{f.id}",
        )

    @staticmethod
    def _aware(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def _is_live(self, f: AgentFinding, agent) -> bool:
        now = datetime.now(timezone.utc)
        if f.source == "scan":
            created = self._aware(f.created_at)
            return created is not None and (now - created) < _SCAN_LIVE_WINDOW
        if agent is not None and agent.status == "active":
            last = self._aware(agent.last_execution_at)
            return last is not None and (now - last) < _AGENT_LIVE_WINDOW
        return False

    # ─── Cursor (keyset on created_at, id) ───────────────────────────────

    @staticmethod
    def _encode_cursor(finding: AgentFinding) -> str:
        payload = json.dumps([finding.created_at.isoformat(), str(finding.id)])
        return base64.urlsafe_b64encode(payload.encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> Tuple[datetime, UUID]:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            created_iso, id_str = json.loads(raw)
            return datetime.fromisoformat(created_iso), UUID(id_str)
        except Exception as exc:  # noqa: BLE001 — any malformed input → 400
            raise InvalidCursor(str(exc)) from exc
