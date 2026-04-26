"""MetricService — Knowledge refactor Phases 2 + 3.

Phase 2 shipped the model + table + minimal CRUD with author-only
mutation. Phase 3 plugs the RBAC matrix from KNOWLEDGE_REFACTOR.md §4
into create/update/delete:

  scope=personal — only the user themselves
  scope=crew     — Crew Commander OR Navigator (Explorer / Guest deny)
  scope=space    — Space Commander only (Navigator deny — wider blast
                    radius than Crew, gated tighter on purpose)
  scope=org      — Owner OR admin with `knowledge.certify` permission
                    grant (delegable per-user, not by platform role)

The same matrix applies to update + delete.
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
from src.models.user_permission_grant import (
    PERMISSION_KNOWLEDGE_CERTIFY,
    UserPermissionGrant,
)
from src.schemas.metric import MetricCreate, MetricUpdate

# Per Knowledge RBAC matrix:
#   crew: Commander + Navigator can write; Explorer + Guest cannot
#   space: only Commander (= Space "admin" role) can write
_CREW_WRITE_ROLES = {"commander", "navigator"}
_SPACE_WRITE_ROLES = {"admin"}  # Space "admin" ≡ Commander in the matrix


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

    async def _user_role_in_crew(self, user: User, crew_id: UUID) -> Optional[str]:
        row = await self.db.execute(
            select(CrewMember.role).where(
                CrewMember.user_id == user.id, CrewMember.crew_id == crew_id
            )
        )
        return row.scalar_one_or_none()

    async def _user_role_in_space(self, user: User, space_id: UUID) -> Optional[str]:
        row = await self.db.execute(
            select(SpaceMember.role).where(
                SpaceMember.user_id == user.id, SpaceMember.space_id == space_id
            )
        )
        return row.scalar_one_or_none()

    async def _has_live_grant(self, user: User, permission: str) -> bool:
        """True iff the user has a non-revoked grant for ``permission``.

        Live = ``revoked_at IS NULL``. Always re-queried — there is no
        caching layer here so revocations take effect on the next call.
        """
        row = await self.db.execute(
            select(UserPermissionGrant.id)
            .where(
                UserPermissionGrant.user_id == user.id,
                UserPermissionGrant.permission == permission,
                UserPermissionGrant.revoked_at.is_(None),
            )
            .limit(1)
        )
        return row.first() is not None

    async def _assert_can_mutate_scope(
        self, user: User, scope: str, scope_id: Optional[UUID]
    ) -> None:
        """Phase 3 gate — runs at create / update / delete time.

        Personal: user must match ``scope_id``.
        Crew:     user must be Commander or Navigator of the crew.
        Space:    user must be Commander (Space role ``admin``).
        Org:      Owner OR admin with ``knowledge.certify`` grant.
        """
        if scope == "personal":
            if scope_id != user.id:
                raise ForbiddenError("personal metrics are scoped to their owner")
            return

        if scope == "crew":
            role = await self._user_role_in_crew(user, scope_id)
            if role not in _CREW_WRITE_ROLES:
                raise ForbiddenError(
                    "crew metric writes require Commander or Navigator role"
                )
            return

        if scope == "space":
            role = await self._user_role_in_space(user, scope_id)
            if role not in _SPACE_WRITE_ROLES:
                raise ForbiddenError(
                    "space metric writes require the Commander (admin) role"
                )
            return

        if scope == "org":
            platform_role = (user.role or "").lower()
            if platform_role == "owner":
                return
            if platform_role == "admin" and await self._has_live_grant(
                user, PERMISSION_KNOWLEDGE_CERTIFY
            ):
                return
            raise ForbiddenError(
                "org metric writes require Owner or knowledge.certify grant"
            )

        raise ValidationError(f"invalid scope '{scope}'")

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

        # Phase 3 RBAC gate — covers Personal+Crew+Space+Org per the
        # KNOWLEDGE_REFACTOR.md §4 mutation matrix.
        await self._assert_can_mutate_scope(user, payload.scope, payload.scope_id)

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
        # Phase 3 — same matrix as create. Author can always update their
        # own row; otherwise the caller must satisfy the scope's write
        # rule. We keep the author shortcut for Personal so the user
        # doesn't need to pass any additional gate to edit their own row.
        if m.created_by_user_id != user.id:
            await self._assert_can_mutate_scope(user, m.scope, m.scope_id)

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
        if m.created_by_user_id != user.id:
            await self._assert_can_mutate_scope(user, m.scope, m.scope_id)
        m.deleted_at = datetime.now(timezone.utc)
        m.updated_by_user_id = user.id
        await self.db.flush()
