"""BeatsService — quota check + consumption recording in one place.

One service handles every cost-bearing AI call site:

    rec = await BeatsService(db).check_and_record(
        user, kind="chat", source_id=ai_query.id,
    )

Returns a dict with ``used_after`` / ``limit`` / ``period_end`` so the
caller can shove that into the response body if needed (FE renders
the new state without a second round-trip).

If the quota is already exhausted the call raises
``PaymentRequiredError`` BEFORE recording — caller never even runs the
LLM. That's the whole point: the meter is the gate.

Window math is rolling: usage is ``SUM(beats) WHERE user_id = ? AND
created_at >= now() - <plan.period>``. No reset cron. Demo (7d) and
paid (30d) both ride on the same query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.plan_quotas import (
    PLAN_QUOTAS,
    PlanQuota,
    cost_for_kind,
    plan_for_user,
)
from src.core.exceptions import PaymentRequiredError
from src.models.beat_consumption import BeatConsumption
from src.models.tenant_plan import TenantPlan
from src.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class UsageSnapshot:
    """Snapshot of a user/tenant's beat usage at a point in time."""

    plan: PlanQuota
    used: Decimal
    limit: Decimal
    period_start: datetime
    period_end: datetime
    breakdown_by_kind: dict[str, Decimal] = field(default_factory=dict)

    @property
    def remaining(self) -> Decimal:
        return max(Decimal("0"), self.limit - self.used)

    @property
    def percent_used(self) -> int:
        if self.limit <= 0:
            return 0
        return int((self.used / self.limit) * 100)

    @property
    def days_remaining(self) -> int:
        """Days until the budget meaningfully refreshes.

        For a rolling window this is, by definition, the plan period
        length — old events keep dropping off the window's tail one
        per day, so a fully-spent user "regains" beats over the next
        ``period_days`` days. Demo countdown (TTL till user expires)
        is rendered by a separate badge that watches
        ``user.demo_expires_at``; this number is about the BUDGET
        cadence, not the user lifespan.
        """
        return self.plan.period_days

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.tier,
            "plan_label": self.plan.label,
            "used": float(self.used),
            "limit": float(self.limit),
            "remaining": float(self.remaining),
            "percent_used": self.percent_used,
            "days_remaining": self.days_remaining,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "breakdown_by_kind": {
                k: float(v) for k, v in self.breakdown_by_kind.items()
            },
            "upgrade_cta": self.plan.upgrade_cta,
        }


class BeatsService:
    """Quota guard + consumption logger."""

    def __init__(self, db: AsyncSession):
        self.db = db
        # Cached for the lifetime of this BeatsService instance — the
        # tenant plan tier is a singleton row and doesn't change mid-
        # request. Avoids re-querying for every _plan_for() lookup
        # within the same handler.
        self._cached_tenant_tier: Optional[str] = None
        self._tier_loaded: bool = False

    # ─── Public API ─────────────────────────────────────────────────────────

    async def usage_window(
        self,
        user: User,
        *,
        scope: str = "user",  # "user" or "tenant"
    ) -> UsageSnapshot:
        """Return current usage / limit for the rolling plan window.

        scope="user" is what the chat path checks; the user's own
        slice. scope="tenant" aggregates across every user in the
        tenant — used by /tenant/beats for Owner/Admin views.
        """
        plan = await self._plan_for(user)
        period_end = datetime.now(timezone.utc)
        period_start = period_end - plan.period

        if scope == "tenant":
            # tenant_id may be NULL until multi-tenant ships — the
            # query then aggregates "everyone with tenant_id IS NULL"
            # which is the same Sky tenant everyone sits in today.
            where_user = (
                BeatConsumption.tenant_id == user.tenant_id
                if getattr(user, "tenant_id", None) is not None
                else BeatConsumption.tenant_id.is_(None)
            )
        else:
            where_user = BeatConsumption.user_id == user.id

        # Total
        total_q = select(func.coalesce(func.sum(BeatConsumption.beats), 0)).where(
            where_user,
            BeatConsumption.created_at >= period_start,
        )
        used: Decimal = (await self.db.execute(total_q)).scalar_one() or Decimal("0")

        # Breakdown per kind (for the hover card / settings page)
        breakdown_q = (
            select(
                BeatConsumption.kind,
                func.coalesce(func.sum(BeatConsumption.beats), 0),
            )
            .where(where_user, BeatConsumption.created_at >= period_start)
            .group_by(BeatConsumption.kind)
        )
        breakdown_rows = (await self.db.execute(breakdown_q)).all()
        breakdown = {row[0]: Decimal(row[1] or 0) for row in breakdown_rows}

        return UsageSnapshot(
            plan=plan,
            used=Decimal(used),
            limit=plan.beats_per_period,
            period_start=period_start,
            period_end=period_end,
            breakdown_by_kind=breakdown,
        )

    async def check_and_record(
        self,
        user: User,
        *,
        kind: str,
        source_id: Optional[UUID] = None,
    ) -> UsageSnapshot:
        """Atomic gate + log: raise 402 if the event would put the
        user over the cap, otherwise record it and return the new
        post-event snapshot.

        Caller pattern (FastAPI handler):

            snapshot = await BeatsService(db).check_and_record(
                current_user, kind="chat", source_id=ai_query.id,
            )
            response.headers["x-sky-beats-remaining"] = str(snapshot.remaining)
        """
        cost = cost_for_kind(kind)
        snapshot = await self.usage_window(user, scope="user")

        if snapshot.used + cost > snapshot.limit:
            logger.info(
                "beats.quota_exceeded user=%s plan=%s used=%s limit=%s kind=%s cost=%s",
                user.id, snapshot.plan.tier, snapshot.used, snapshot.limit, kind, cost,
            )
            raise PaymentRequiredError(
                f"Your {snapshot.plan.label} plan budget for this period is full. "
                f"You've used {snapshot.used:.0f}/{snapshot.limit:.0f} beats.",
                upgrade_cta=snapshot.plan.upgrade_cta,
            )

        row = BeatConsumption(
            id=uuid4(),
            user_id=user.id,
            tenant_id=getattr(user, "tenant_id", None),
            kind=kind,
            source_id=source_id,
            beats=cost,
        )
        self.db.add(row)
        await self.db.flush()

        # Compose post-event snapshot without re-querying — cheap
        # and the breakdown stays accurate because we increment the
        # one kind we just consumed.
        snapshot.used = snapshot.used + cost
        snapshot.breakdown_by_kind[kind] = (
            snapshot.breakdown_by_kind.get(kind, Decimal("0")) + cost
        )
        return snapshot

    async def record_only(
        self,
        user: User,
        *,
        kind: str,
        source_id: Optional[UUID] = None,
    ) -> None:
        """Record a beat consumption row WITHOUT pre-checking the quota.

        Used by background workers (agent worker tier-router) where
        the gate fired earlier in the cycle and the actual L2/L3
        call already paid for itself. Avoids double-counting.
        """
        cost = cost_for_kind(kind)
        row = BeatConsumption(
            id=uuid4(),
            user_id=user.id,
            tenant_id=getattr(user, "tenant_id", None),
            kind=kind,
            source_id=source_id,
            beats=cost,
        )
        self.db.add(row)
        await self.db.flush()

    # ─── Internals ──────────────────────────────────────────────────────────

    async def _plan_for(self, user: User) -> PlanQuota:
        """Resolve plan tier for `user`, reading the singleton
        ``tenant_plan`` row to find the contracted tier. Demo users
        bypass the DB read entirely — their tier is decided by the
        ``is_demo`` flag, not by tenant config.
        """
        if bool(getattr(user, "is_demo", False)):
            return plan_for_user(is_demo=True)

        if not self._tier_loaded:
            row = (
                await self.db.execute(
                    select(TenantPlan.plan_tier).where(TenantPlan.id == 1)
                )
            ).scalar_one_or_none()
            self._cached_tenant_tier = row
            self._tier_loaded = True

        return plan_for_user(is_demo=False, tenant_tier=self._cached_tenant_tier)
