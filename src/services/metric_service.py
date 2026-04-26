"""MetricService — Knowledge refactor Phase 2 (foundations).

Phase 2 ships the model + table + minimal CRUD. The mutation gates
(creating/promoting at crew/space/org scope) live in Phase 3 and the
contract tests in `src/tests/knowledge/test_knowledge_mutation_rbac.py`
will start passing as that lands.

For Phase 2 we keep it simple:

* read filter — Personal rows (your own), plus rows in crews you're
  in, plus rows in spaces you're in, plus everything at org scope.
* mutation — only the row's owner / creator can update or soft-delete
  it. Crew/space/org create paths exist but are not yet RBAC-gated by
  the platform-role grant matrix; they will be in Phase 3.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from src.models.crew import CrewMember
from src.models.metric import METRIC_LANGUAGES, METRIC_SCOPES, METRIC_STATUSES, Metric
from src.models.space import SpaceMember
from src.models.user import User
from src.schemas.metric import MetricCreate, MetricUpdate


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Turn a metric name into a stable URL-safe slug.

    The slug is what the unique constraint locks on, so we want it
    deterministic for the same input but tolerant of users typing the
    name twice with different casing or whitespace.
    """
    s = (name or "").strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    return s or "metric"


class MetricService:
    """Phase 2 CRUD façade — owner-restricted mutations, scope-aware reads."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── helpers ────────────────────────────────────────────────────────
    async def _user_crew_ids(self, user: User) -> List[UUID]:
        rows = await self.db.execute(
            select(CrewMember.crew_id).where(CrewMember.user_id == user.id)
        )
        return [r[0] for r in rows.all()]

    async def _user_space_ids(self, user: User) -> List[UUID]:
        rows = await self.db.execute(
            select(SpaceMember.space_id).where(SpaceMember.user_id == user.id)
        )
        return [r[0] for r in rows.all()]

    async def _resolve_unique_slug(
        self,
        scope: str,
        scope_id: Optional[UUID],
        base: str,
        ignore_id: Optional[UUID] = None,
    ) -> str:
        """Append `-2`, `-3`, … until (scope, scope_id, slug) is free.

        Soft-deleted rows are excluded so a user can re-use a slug they
        previously discarded.
        """
        candidate = base
        i = 2
        while True:
            stmt = select(Metric.id).where(
                Metric.scope == scope,
                Metric.scope_id == scope_id,
                Metric.slug == candidate,
                Metric.deleted_at.is_(None),
            )
            if ignore_id:
                stmt = stmt.where(Metric.id != ignore_id)
            existing = (await self.db.execute(stmt)).first()
            if not existing:
                return candidate
            candidate = f"{base}-{i}"
            i += 1

    # ─── validators ─────────────────────────────────────────────────────
    @staticmethod
    def _validate_scope(scope: str, scope_id: Optional[UUID]) -> None:
        if scope not in METRIC_SCOPES:
            raise ValidationError(f"invalid scope '{scope}'")
        if scope == "org":
            if scope_id is not None:
                raise ValidationError("scope_id must be null for org scope")
        else:
            if scope_id is None:
                raise ValidationError(f"scope_id is required for scope '{scope}'")

    @staticmethod
    def _validate_status_lang(status: str, language: str) -> None:
        if status not in METRIC_STATUSES:
            raise ValidationError(f"invalid status '{status}'")
        if language not in METRIC_LANGUAGES:
            raise ValidationError(f"invalid formula_language '{language}'")

    # ─── CRUD ───────────────────────────────────────────────────────────
    async def create(self, user: User, payload: MetricCreate) -> Metric:
        self._validate_scope(payload.scope, payload.scope_id)
        self._validate_status_lang(payload.status, payload.formula_language)

        # Personal scope must always be authored against the caller's
        # own user-id. Crew / space / org checks are Phase 3 territory.
        if payload.scope == "personal" and payload.scope_id != user.id:
            raise ForbiddenError("personal metrics must be scoped to the caller")

        slug = await self._resolve_unique_slug(
            payload.scope, payload.scope_id, _slugify(payload.name)
        )

        m = Metric(
            id=uuid.uuid4(),
            name=payload.name,
            slug=slug,
            description=payload.description,
            scope=payload.scope,
            scope_id=payload.scope_id,
            status=payload.status,
            formula_text=payload.formula_text,
            formula_description=payload.formula_description,
            formula_language=payload.formula_language,
            source_id=payload.source_id,
            source_table=payload.source_table,
            source_column=payload.source_column,
            aggregation=payload.aggregation,
            unit=payload.unit,
            time_grain=payload.time_grain,
            target_value=payload.target_value,
            target_date=payload.target_date,
            threshold_warning=payload.threshold_warning,
            threshold_critical=payload.threshold_critical,
            tags=list(payload.tags or []),
            owner_user_id=user.id,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        self.db.add(m)
        await self.db.flush()
        await self.db.refresh(m)
        return m

    async def list_visible(self, user: User) -> List[Metric]:
        crew_ids = await self._user_crew_ids(user)
        space_ids = await self._user_space_ids(user)

        clauses = [
            (Metric.scope == "org"),
            ((Metric.scope == "personal") & (Metric.scope_id == user.id)),
        ]
        if crew_ids:
            clauses.append((Metric.scope == "crew") & (Metric.scope_id.in_(crew_ids)))
        if space_ids:
            clauses.append((Metric.scope == "space") & (Metric.scope_id.in_(space_ids)))

        stmt = (
            select(Metric)
            .where(Metric.deleted_at.is_(None))
            .where(or_(*clauses))
            .order_by(Metric.created_at.desc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def _get_visible_or_404(self, user: User, metric_id: UUID) -> Metric:
        stmt = select(Metric).where(Metric.id == metric_id, Metric.deleted_at.is_(None))
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError("metric not found")

        if row.scope == "org":
            return row
        if row.scope == "personal":
            if row.scope_id == user.id:
                return row
            raise NotFoundError("metric not found")
        if row.scope == "crew":
            crew_ids = await self._user_crew_ids(user)
            if row.scope_id in crew_ids:
                return row
            raise NotFoundError("metric not found")
        if row.scope == "space":
            space_ids = await self._user_space_ids(user)
            if row.scope_id in space_ids:
                return row
            raise NotFoundError("metric not found")
        raise NotFoundError("metric not found")

    async def get(self, user: User, metric_id: UUID) -> Metric:
        return await self._get_visible_or_404(user, metric_id)

    async def update(self, user: User, metric_id: UUID, payload: MetricUpdate) -> Metric:
        m = await self._get_visible_or_404(user, metric_id)
        if m.created_by_user_id and m.created_by_user_id != user.id:
            # Phase 3 will plug in platform-role grants here.
            raise ForbiddenError("only the metric author can update it (Phase 2)")

        data = payload.model_dump(exclude_unset=True)

        # Slug only changes if the name changes.
        if "name" in data and data["name"] != m.name:
            data["slug"] = await self._resolve_unique_slug(
                m.scope, m.scope_id, _slugify(data["name"]), ignore_id=m.id
            )

        if "status" in data and data["status"] is not None:
            self._validate_status_lang(data["status"], m.formula_language)
        if "formula_language" in data and data["formula_language"] is not None:
            self._validate_status_lang(m.status, data["formula_language"])

        for k, v in data.items():
            setattr(m, k, v)
        m.updated_by_user_id = user.id
        m.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(m)
        return m

    async def delete(self, user: User, metric_id: UUID) -> None:
        m = await self._get_visible_or_404(user, metric_id)
        if m.created_by_user_id and m.created_by_user_id != user.id:
            raise ForbiddenError("only the metric author can delete it (Phase 2)")
        m.deleted_at = datetime.now(timezone.utc)
        m.updated_by_user_id = user.id
        await self.db.flush()
