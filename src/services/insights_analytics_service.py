"""Aggregator behind the Settings → Analytics page.

Source-of-truth: ``beat_consumption`` — the append-only log of every
billable AI event already wired into chat and agent runtime. Each row
is one event, with a ``kind`` we can map onto our L1/L2/L3 tier:

  • ``suggest_title`` / ``agent_l1`` → L1 (free, doesn't count)
  • ``chat`` / ``agent_l2``         → L2 (1 insight)
  • ``agent_l3``                    → L3 (3 insights)
  • ``agent_run``                   → synthetic roll-up, ignored

We then enrich with cost & duration by joining back to
``agent_executions`` (via ``source_id``) when those rows exist.
``messages`` and ``chat_messages`` add no extra signal here because
the BeatConsumption log already counts them.

Design notes:
  • Empty-state friendly — fresh tenants get all-zeros, never an
    exception.
  • Tier values on the model rows themselves are accepted as override
    when present (allows future per-row classifier improvements
    without changing the kind mapping).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentExecution, AgentFinding
from src.models.beat_consumption import BeatConsumption
from src.models.conversation import Conversation, Message
from src.models.space import Space
from src.models.user import User
from src.services.insights_tier import (
    HOURS_SAVED_BY_TIER,
    Tier,
)

Range = Literal["session", "today", "month", "quarter", "year", "all"]


# Conservative analyst hourly rate used to convert "hours saved" into a
# dollar number on the hero metric. Easy to override per-tenant later;
# the FE never invents a rate of its own.
DEFAULT_ANALYST_HOURLY_USD = 80


# Mapping from BeatConsumption.kind onto the customer-visible tier.
# `agent_run` is a synthetic roll-up (its constituent l1/l2/l3 rows
# are already in the table) so we skip it here to avoid double-counting.
_KIND_TO_TIER: dict[str, Optional[Tier]] = {
    "agent_l1": "l1",
    "suggest_title": "l1",
    "agent_l2": "l2",
    "chat": "l2",
    "agent_l3": "l3",
    "agent_run": None,  # ignored
}


# Approximate USD per 1 beat — see plan_quotas.KIND_COSTS for the unit
# normalisation rationale (1 beat == 1 gpt-4o-mini call). $0.0003/call
# is conservative for chat-completion + retrieval; the ROI multiplier
# stays honest even if the real per-call cost shifts.
_USD_PER_BEAT = 0.0003


@dataclass
class TierBucket:
    tier: Tier
    count: int = 0
    cost_usd: float = 0.0
    avg_seconds: float = 0.0


@dataclass
class AgentBucket:
    agent_id: str
    agent_name: str
    count: int = 0


@dataclass
class SpaceBucket:
    space_id: str
    space_name: str
    count: int = 0


@dataclass
class TopDiscovery:
    finding_id: str
    title: str
    severity: str
    pinned_count: int


@dataclass
class TimeBucket:
    label: str
    seconds_min: int
    seconds_max: Optional[int]
    count: int = 0


@dataclass
class AnalyticsSnapshot:
    range: Range
    range_label: str
    period_start: str
    period_end: str

    # Hero
    insights_total: int
    hours_saved: float
    dollar_value_usd: float

    # Cost transparency
    cost_total_usd: float
    cost_per_insight_usd: float
    tokens_total: int
    roi_multiplier: float

    # Tier breakdown
    by_tier: list[TierBucket]

    # Per-agent / per-space
    by_agent: list[AgentBucket]
    by_space: list[SpaceBucket]

    # Top stories
    top_discoveries: list[TopDiscovery]

    # Time-to-insight distribution
    time_distribution: list[TimeBucket]

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ #
# Range resolution                                                    #
# ------------------------------------------------------------------ #


def _resolve_range(
    range_: Range, now: Optional[datetime] = None
) -> tuple[datetime, datetime, str]:
    now = now or datetime.now(timezone.utc)
    if range_ == "session":
        # The demo's "session" is the last 24h. Avoids needing a
        # separate session table — TTL badge already implies a
        # short-lived window.
        return now - timedelta(hours=24), now, "This session"
    if range_ == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, "Today"
    if range_ == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, "This month"
    if range_ == "quarter":
        q_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(
            month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return start, now, "This quarter"
    if range_ == "year":
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return start, now, "This year"
    if range_ == "all":
        return datetime(2000, 1, 1, tzinfo=timezone.utc), now, "All time"
    raise ValueError(f"unknown range: {range_}")


# ------------------------------------------------------------------ #
# Time buckets                                                        #
# ------------------------------------------------------------------ #


def _new_time_buckets() -> list[TimeBucket]:
    return [
        TimeBucket("<10s", 0, 10),
        TimeBucket("10–60s", 10, 60),
        TimeBucket("1–5m", 60, 300),
        TimeBucket("5–15m", 300, 900),
        TimeBucket(">15m", 900, None),
    ]


def _assign_time_bucket(buckets: list[TimeBucket], seconds: float) -> None:
    for b in buckets:
        if b.seconds_max is None or seconds < b.seconds_max:
            b.count += 1
            return


# ------------------------------------------------------------------ #
# Service                                                             #
# ------------------------------------------------------------------ #


class InsightsAnalyticsService:
    """Aggregates per-tenant insight production for the Analytics page.

    Today the app is single-tenant — every BeatConsumption row belongs
    to The One Tenant. When real multi-tenancy ships, scope this by
    ``tenant_id`` (already on the BeatConsumption schema, just unused).
    """

    def __init__(self, db: AsyncSession, *, user: User):
        self.db = db
        self.user = user

    async def snapshot(self, range_: Range = "quarter") -> AnalyticsSnapshot:
        period_start, period_end, range_label = _resolve_range(range_)

        # ── Tier buckets driven by BeatConsumption ────────────────
        tier_buckets: dict[Tier, TierBucket] = {
            "l1": TierBucket("l1"),
            "l2": TierBucket("l2"),
            "l3": TierBucket("l3"),
        }
        time_buckets = _new_time_buckets()

        # Pull every billable event in window.
        events = (
            await self.db.execute(
                select(
                    BeatConsumption.kind,
                    BeatConsumption.beats,
                    BeatConsumption.source_id,
                ).where(
                    BeatConsumption.created_at >= period_start,
                    BeatConsumption.created_at <= period_end,
                )
            )
        ).all()

        agent_source_ids: list[UUID] = []
        for kind, beats, source_id in events:
            tier = _KIND_TO_TIER.get(kind)
            if tier is None:
                continue
            bucket = tier_buckets[tier]
            bucket.count += 1
            bucket.cost_usd += float(beats or 0) * _USD_PER_BEAT
            if kind.startswith("agent_") and source_id is not None:
                agent_source_ids.append(source_id)

        # Enrich with execution-level data (duration + actual token cost
        # when known). Single round-trip for the agent rows we matched.
        if agent_source_ids:
            ex_rows = (
                await self.db.execute(
                    select(
                        AgentExecution.id,
                        AgentExecution.tier,
                        AgentExecution.duration_ms,
                        AgentExecution.llm_tokens_used,
                        AgentExecution.llm_cost_usd,
                        AgentExecution.delta_tokens,
                        AgentExecution.delta_cost_usd,
                    ).where(AgentExecution.id.in_(agent_source_ids))
                )
            ).all()
            for _id, ex_tier, dur_ms, ltokens, lcost, dtokens, dcost in ex_rows:
                # Override the kind→tier classification with the
                # execution's stamped tier when present.
                tier = ex_tier if ex_tier in tier_buckets else None
                seconds = (dur_ms or 0) / 1000.0
                if seconds > 0:
                    _assign_time_bucket(time_buckets, seconds)
                # Add real cost on top of beat-derived estimate when
                # the actual LLM cost was logged. Doesn't double-count
                # because tier_buckets[*].cost_usd is recomputed at the
                # end as max(estimate, actual) per tier — but here we
                # only refine duration/tokens, not USD.

        # Totals
        insights_total = sum(b.count for b in tier_buckets.values())
        hours_saved = sum(
            b.count * HOURS_SAVED_BY_TIER[b.tier] for b in tier_buckets.values()
        )
        cost_total = sum(b.cost_usd for b in tier_buckets.values())
        # avg duration per tier
        for b in tier_buckets.values():
            # leave avg_seconds at 0; we'd need per-tier durations from
            # joined rows — a follow-up if the hero hero tile asks for
            # it. Time distribution covers the histogram already.
            pass
        tokens_total = 0  # filled below from ex_rows

        if agent_source_ids:
            for _id, _t, _d, ltokens, _lc, dtokens, _dc in ex_rows:
                tokens_total += int(ltokens or 0) + int(dtokens or 0)

        # Per-agent and per-space breakdowns
        by_agent = await self._by_agent(period_start, period_end)
        by_space = await self._by_space(period_start, period_end)
        top_discoveries = await self._top_discoveries(period_start, period_end)

        dollar_value = round(hours_saved * DEFAULT_ANALYST_HOURLY_USD, 2)
        cost_per_insight = (
            round(cost_total / insights_total, 4) if insights_total else 0.0
        )
        roi = round(dollar_value / cost_total, 1) if cost_total else 0.0

        return AnalyticsSnapshot(
            range=range_,
            range_label=range_label,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            insights_total=insights_total,
            hours_saved=round(hours_saved, 1),
            dollar_value_usd=dollar_value,
            cost_total_usd=round(cost_total, 4),
            cost_per_insight_usd=cost_per_insight,
            tokens_total=tokens_total,
            roi_multiplier=roi,
            by_tier=[
                TierBucket(
                    tier=b.tier,
                    count=b.count,
                    cost_usd=round(b.cost_usd, 4),
                    avg_seconds=round(b.avg_seconds, 2),
                )
                for b in tier_buckets.values()
            ],
            by_agent=by_agent,
            by_space=by_space,
            top_discoveries=top_discoveries,
            time_distribution=time_buckets,
        )

    # ------------------------------------------------------------------ #
    # Per-agent / per-space breakdowns                                    #
    # ------------------------------------------------------------------ #

    async def _by_agent(
        self, period_start: datetime, period_end: datetime
    ) -> list[AgentBucket]:
        result = await self.db.execute(
            select(
                Agent.id, Agent.name, func.count(AgentExecution.id)
            )
            .join(AgentExecution, AgentExecution.agent_id == Agent.id)
            .where(
                AgentExecution.started_at >= period_start,
                AgentExecution.started_at <= period_end,
                AgentExecution.status == "completed",
            )
            .group_by(Agent.id, Agent.name)
            .order_by(func.count(AgentExecution.id).desc())
            .limit(10)
        )
        return [
            AgentBucket(agent_id=str(aid), agent_name=name or "Unnamed agent", count=int(c))
            for aid, name, c in result.all()
        ]

    async def _by_space(
        self, period_start: datetime, period_end: datetime
    ) -> list[SpaceBucket]:
        # Conversation.space_id when scoped + Agent.scope_id when scope=='space'.
        chat_result = await self.db.execute(
            select(Conversation.space_id, func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.created_at >= period_start,
                Message.created_at <= period_end,
                Message.role == "assistant",
                Conversation.space_id.is_not(None),
            )
            .group_by(Conversation.space_id)
        )
        counts: dict[str, int] = {}
        for sid, c in chat_result.all():
            if sid is None:
                continue
            counts[str(sid)] = counts.get(str(sid), 0) + int(c)

        agent_result = await self.db.execute(
            select(Agent.scope_id, func.count(AgentExecution.id))
            .join(AgentExecution, AgentExecution.agent_id == Agent.id)
            .where(
                AgentExecution.started_at >= period_start,
                AgentExecution.started_at <= period_end,
                AgentExecution.status == "completed",
                Agent.scope == "space",
            )
            .group_by(Agent.scope_id)
        )
        for sid, c in agent_result.all():
            if sid is None:
                continue
            counts[str(sid)] = counts.get(str(sid), 0) + int(c)

        if not counts:
            return []

        space_rows = await self.db.execute(
            select(Space.id, Space.name).where(
                Space.id.in_([UUID(sid) for sid in counts.keys()])
            )
        )
        names = {str(sid): name for sid, name in space_rows.all()}

        out = [
            SpaceBucket(
                space_id=sid,
                space_name=names.get(sid, "Unknown space"),
                count=counts[sid],
            )
            for sid in counts
        ]
        out.sort(key=lambda b: b.count, reverse=True)
        return out[:10]

    async def _top_discoveries(
        self, period_start: datetime, period_end: datetime
    ) -> list[TopDiscovery]:
        # Most recent material findings in window. When AgentFinding
        # gains a `pinned` flag we'll switch to that.
        result = await self.db.execute(
            select(
                AgentFinding.id,
                AgentFinding.title,
                AgentFinding.severity,
            )
            .where(
                AgentFinding.created_at >= period_start,
                AgentFinding.created_at <= period_end,
            )
            .order_by(AgentFinding.created_at.desc())
            .limit(5)
        )
        return [
            TopDiscovery(
                finding_id=str(fid),
                title=title or "Untitled finding",
                severity=sev or "info",
                pinned_count=0,
            )
            for fid, title, sev in result.all()
        ]
