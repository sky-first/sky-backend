"""PromotionService — Knowledge refactor Phase 4.

End-to-end Personal→Crew→Space→Org promotion of a Metric (Phase 5
extends to GlossaryTerm). Three pieces:

  1. enqueue   — creates a PromotionRequest, resolves dependencies,
                 runs the conflict detector. Returns the request +
                 any conflicts that block it.
  2. approve   — atomic. Copies the metric to the target scope (and
                 any unsatisfied dependency sources) using the same
                 mutation gate as MetricService.
  3. reject    — closes the request without writes.

Conflict detector uses ``difflib.SequenceMatcher.ratio()`` for fuzzy
matching on names — threshold 0.75 per KNOWLEDGE_REFACTOR.md §5.4.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from typing import List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.models.metric import Metric
from src.models.promotion import (
    CONFLICT_DECISIONS,
    KnowledgeConflict,
    PromotionRequest,
    PromotionRequestItem,
)
from src.models.user import User
from src.services.metric_service import MetricService

# §5.4 — fuzzy similarity gate for conflict detection.
CONFLICT_THRESHOLD = 0.75


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _scope_widens(src: str, dst: str) -> bool:
    """Promotion only flows narrower→wider. The lattice is fixed:

        personal < crew < space < org
    """
    order = {"personal": 0, "crew": 1, "space": 2, "org": 3}
    return order.get(src, -1) < order.get(dst, -1)


class PromotionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.metrics = MetricService(db)

    # ─── enqueue ────────────────────────────────────────────────────────
    async def enqueue(
        self,
        *,
        requester: User,
        metric_id: UUID,
        target_scope: str,
        target_scope_id: Optional[UUID] = None,
        note: Optional[str] = None,
    ) -> Tuple[PromotionRequest, List[KnowledgeConflict]]:
        # Source metric must be visible to the requester (Phase 2 ACL).
        metric = await self.metrics._get_visible_or_404(requester, metric_id)

        if not _scope_widens(metric.scope, target_scope):
            raise ValidationError(
                f"promotion must widen scope (got {metric.scope} → {target_scope})"
            )

        # Requester must satisfy the target scope's WRITE rule, otherwise
        # they wouldn't be allowed to land the row even if approved.
        await self.metrics._assert_can_mutate_scope(
            requester, target_scope, target_scope_id
        )

        request = PromotionRequest(
            id=uuid.uuid4(),
            requester_user_id=requester.id,
            target_scope=target_scope,
            target_scope_id=target_scope_id,
            status="pending",
            note=note,
        )
        self.db.add(request)
        await self.db.flush()

        # Primary item — the metric itself.
        self.db.add(
            PromotionRequestItem(
                id=uuid.uuid4(),
                request_id=request.id,
                kind="metric",
                entity_id=metric.id,
                role="primary",
                label=metric.name,
            )
        )

        # Dependency resolver — Phase 4 covers Source only; GlossaryTerm
        # + Relationship deps land alongside Phase 5 + 6.
        if metric.source_id is not None:
            self.db.add(
                PromotionRequestItem(
                    id=uuid.uuid4(),
                    request_id=request.id,
                    kind="source",
                    entity_id=metric.source_id,
                    role="dependency",
                    label="data source",
                )
            )

        await self.db.flush()

        # Conflict detection — fuzzy match on name against existing
        # entities at the target scope.
        conflicts = await self._detect_conflicts(metric, request, target_scope, target_scope_id)
        if conflicts:
            request.status = "conflict_pending"
            await self.db.flush()
        return request, conflicts

    async def _detect_conflicts(
        self,
        metric: Metric,
        request: PromotionRequest,
        target_scope: str,
        target_scope_id: Optional[UUID],
    ) -> List[KnowledgeConflict]:
        # Find live, non-deleted metrics at the target scope.
        stmt = select(Metric).where(
            Metric.scope == target_scope,
            Metric.deleted_at.is_(None),
        )
        if target_scope == "org":
            stmt = stmt.where(Metric.scope_id.is_(None))
        else:
            stmt = stmt.where(Metric.scope_id == target_scope_id)

        rows = (await self.db.execute(stmt)).scalars().all()

        conflicts: List[KnowledgeConflict] = []
        for canonical in rows:
            sim = _name_similarity(metric.name, canonical.name)
            if sim < CONFLICT_THRESHOLD:
                continue
            reason = "name_match" if sim >= 0.99 else "fuzzy_name"
            c = KnowledgeConflict(
                id=uuid.uuid4(),
                request_id=request.id,
                proposed_kind="metric",
                proposed_entity_id=metric.id,
                canonical_kind="metric",
                canonical_entity_id=canonical.id,
                similarity=Decimal(f"{sim:.4f}"),
                reason=reason,
            )
            self.db.add(c)
            conflicts.append(c)
        if conflicts:
            await self.db.flush()
        return conflicts

    # ─── approve / reject ───────────────────────────────────────────────
    async def approve(
        self, *, approver: User, request_id: UUID
    ) -> PromotionRequest:
        request = await self._load(request_id)
        if request.status not in ("pending", "conflict_pending"):
            raise ValidationError(
                f"cannot approve a request in status '{request.status}'"
            )
        if request.status == "conflict_pending":
            unresolved = await self._unresolved_conflicts(request_id)
            if unresolved:
                raise ValidationError(
                    "all conflicts must be resolved before approval"
                )

        # Approver must satisfy the target scope's write rule. The same
        # gate the requester passed at enqueue time — the approver may
        # be different (Crew Commander reviewing Navigator's request).
        await self.metrics._assert_can_mutate_scope(
            approver, request.target_scope, request.target_scope_id
        )

        # Atomic copy. Find the primary item, copy its row to the target
        # scope, preserving created_by_user_id from the original.
        primary = await self._primary_item(request_id)
        if primary is None or primary.kind != "metric":
            raise NotFoundError("promotion request has no metric primary item")

        source = await self.db.get(Metric, primary.entity_id)
        if source is None:
            raise NotFoundError("source metric vanished mid-promotion")

        target = Metric(
            id=uuid.uuid4(),
            name=source.name,
            slug=await self.metrics._resolve_unique_slug(
                request.target_scope,
                request.target_scope_id,
                source.slug,
            ),
            description=source.description,
            scope=request.target_scope,
            scope_id=request.target_scope_id,
            status=source.status,
            formula_text=source.formula_text,
            formula_description=source.formula_description,
            formula_language=source.formula_language,
            source_id=source.source_id,
            source_table=source.source_table,
            source_column=source.source_column,
            aggregation=source.aggregation,
            unit=source.unit,
            time_grain=source.time_grain,
            target_value=source.target_value,
            target_date=source.target_date,
            threshold_warning=source.threshold_warning,
            threshold_critical=source.threshold_critical,
            tags=list(source.tags or []),
            owner_user_id=source.owner_user_id,
            created_by_user_id=source.created_by_user_id,
            updated_by_user_id=approver.id,
        )
        # Org-level certification — auto-set when approver lands the row
        # at scope=org.
        if request.target_scope == "org":
            target.certified_by_user_id = approver.id
            target.certified_at = datetime.now(timezone.utc)
        self.db.add(target)

        request.status = "approved"
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by_user_id = approver.id
        await self.db.flush()
        await self.db.refresh(request)
        return request

    async def reject(self, *, approver: User, request_id: UUID) -> PromotionRequest:
        request = await self._load(request_id)
        if request.status not in ("pending", "conflict_pending"):
            raise ValidationError(
                f"cannot reject a request in status '{request.status}'"
            )
        request.status = "rejected"
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by_user_id = approver.id
        await self.db.flush()
        await self.db.refresh(request)
        return request

    # ─── conflict resolution ────────────────────────────────────────────
    async def resolve_conflict(
        self,
        *,
        owner: User,
        conflict_id: UUID,
        decision: str,
    ) -> KnowledgeConflict:
        if decision not in CONFLICT_DECISIONS:
            raise ValidationError(f"invalid decision '{decision}'")
        conflict = await self.db.get(KnowledgeConflict, conflict_id)
        if conflict is None:
            raise NotFoundError("conflict not found")
        # Only Owner (or knowledge.certify holder) decides — same gate
        # as Org-write. Reuse the metric service helper.
        await self.metrics._assert_can_mutate_scope(owner, "org", None)
        conflict.decision = decision
        conflict.decided_by_user_id = owner.id
        conflict.decided_at = datetime.now(timezone.utc)

        if decision == "replace_canonical":
            # Demote the canonical metric to deprecated so retrieval
            # stops surfacing it.
            canonical = await self.db.get(Metric, conflict.canonical_entity_id)
            if canonical is not None:
                canonical.status = "deprecated"

        await self.db.flush()
        await self.db.refresh(conflict)
        return conflict

    # ─── helpers ────────────────────────────────────────────────────────
    async def _load(self, request_id: UUID) -> PromotionRequest:
        request = await self.db.get(PromotionRequest, request_id)
        if request is None:
            raise NotFoundError("promotion request not found")
        return request

    async def _primary_item(self, request_id: UUID) -> Optional[PromotionRequestItem]:
        row = await self.db.execute(
            select(PromotionRequestItem).where(
                PromotionRequestItem.request_id == request_id,
                PromotionRequestItem.role == "primary",
            )
        )
        return row.scalar_one_or_none()

    async def _unresolved_conflicts(
        self, request_id: UUID
    ) -> List[KnowledgeConflict]:
        rows = await self.db.execute(
            select(KnowledgeConflict).where(
                KnowledgeConflict.request_id == request_id,
                KnowledgeConflict.decision.is_(None),
            )
        )
        return list(rows.scalars().all())

    async def list_items(self, request_id: UUID) -> List[PromotionRequestItem]:
        rows = await self.db.execute(
            select(PromotionRequestItem).where(
                PromotionRequestItem.request_id == request_id
            )
        )
        return list(rows.scalars().all())
