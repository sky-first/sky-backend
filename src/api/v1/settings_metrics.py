"""
Settings & Metrics API — real database queries.

Every endpoint reads directly from the relevant tables; no stub values.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, and_, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.ai import AIFeedback, AIHistory
from src.models.connection import DataConnection
from src.models.crew import Crew, CrewMember
from src.models.dashboard import Widget
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.schemas.settings_metrics import (
    AiMetricsResponse,
    ConnectionMetricsResponse,
    CrewMetricsResponse,
    GlobalMetricsResponse,
    SpaceMetricsResponse,
    UserMetricsResponse,
)
from src.services.rbac_service import RBACService

router = APIRouter()

# ── Helpers ────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _metric(
    value: Any, trend_value: Optional[str] = None, is_positive: Optional[bool] = None
) -> Dict:
    """Build a MetricValue dict."""
    display = str(value) if value not in (None, "", 0) else "0"
    result: Dict = {"value": display}
    if trend_value is not None:
        result["trend"] = {"value": trend_value, "isPositive": bool(is_positive)}
    return result


async def _performance_metrics(db: AsyncSession) -> Dict:
    """Real latency from ai_queries.duration_ms.

    We sample the last 30 days of queries that have a recorded latency
    (new rows only — the column was added in 2026-04-15). When there's
    no data yet, surface "N/A" rather than the old hardcoded "< 3s".
    SLA target is 3000ms; compliance is the fraction of queries that
    hit it.
    """
    SLA_TARGET_MS = 3_000
    since = _now() - timedelta(days=30)

    stats = await db.execute(
        select(
            func.avg(AIHistory.duration_ms),
            func.sum(case((AIHistory.duration_ms <= SLA_TARGET_MS, 1), else_=0)),
            func.count(AIHistory.duration_ms),
        ).where(
            AIHistory.created_at >= since,
            AIHistory.duration_ms.is_not(None),
        )
    )
    avg_ms, within_sla, measured = stats.one()
    avg_ms = float(avg_ms) if avg_ms is not None else None
    within_sla = int(within_sla or 0)
    measured = int(measured or 0)

    if not measured:
        # No latency data yet — be honest about it rather than lying with a static value.
        return {
            "avgLatency": _metric("N/A"),
            "slaCompliance": _metric("N/A"),
            "responseTime": _metric("N/A"),
        }

    sla_pct = round(within_sla / measured * 100)
    avg_sec = avg_ms / 1000.0
    latency_label = f"{avg_sec:.1f}s" if avg_sec >= 0.1 else f"{int(avg_ms)}ms"
    return {
        "avgLatency": _metric(latency_label),
        "slaCompliance": _metric(f"{sla_pct}%"),
        "responseTime": _metric(latency_label),
    }


def _pct_change(current: Union[int, float], previous: Union[int, float]) -> Optional[str]:
    """Return percentage change string like '+12%' or '-5%'."""
    if not previous:
        return None
    pct = ((current - previous) / previous) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f}%"


# ── Global Metrics ─────────────────────────────────────────────────────────────


@router.get("/global", response_model=GlobalMetricsResponse)
async def get_global_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get global platform metrics computed from real database data."""
    await RBACService(db).assert_permission(current_user, "connections.view")

    now = _now()
    ago_30 = now - timedelta(days=30)
    ago_60 = now - timedelta(days=60)

    # ── Total queries ──────────────────────────────────────────────────────────
    total_q_res = await db.execute(select(func.count(AIHistory.id)))
    total_queries: int = total_q_res.scalar_one() or 0

    # ── Last 30 days ───────────────────────────────────────────────────────────
    last30_res = await db.execute(select(func.count(AIHistory.id)).where(AIHistory.date >= ago_30))
    last30: int = last30_res.scalar_one() or 0

    prev30_res = await db.execute(
        select(func.count(AIHistory.id)).where(AIHistory.date >= ago_60, AIHistory.date < ago_30)
    )
    prev30: int = prev30_res.scalar_one() or 0

    growth_str = _pct_change(last30, prev30)

    # ── Avg daily frequency (queries per day over last 30 days) ───────────────
    avg_freq = round(last30 / 30, 1) if last30 else 0

    # ── Active users (distinct users in last 30 days) ─────────────────────────
    active_users_res = await db.execute(
        select(func.count(distinct(AIHistory.user_id))).where(AIHistory.date >= ago_30)
    )
    active_users: int = active_users_res.scalar_one() or 0

    # ── Total users ────────────────────────────────────────────────────────────
    total_users_res = await db.execute(select(func.count(User.id)))
    total_users: int = total_users_res.scalar_one() or 0

    # ── Top user group (most common category) ─────────────────────────────────
    top_cat_res = await db.execute(
        select(AIHistory.category, func.count(AIHistory.id).label("cnt"))
        .where(AIHistory.category.isnot(None))
        .group_by(AIHistory.category)
        .order_by(func.count(AIHistory.id).desc())
        .limit(1)
    )
    top_cat_row = top_cat_res.fetchone()
    top_category = top_cat_row[0] if top_cat_row else "–"

    # ── Recurrence rate: users who queried in both periods ────────────────────
    repeat_users_res = await db.execute(
        select(func.count(distinct(AIHistory.user_id))).where(
            and_(
                AIHistory.date >= ago_30,
                AIHistory.user_id.in_(
                    select(distinct(AIHistory.user_id)).where(
                        and_(AIHistory.date >= ago_60, AIHistory.date < ago_30)
                    )
                ),
            )
        )
    )
    repeat_users: int = repeat_users_res.scalar_one() or 0
    recurrence_rate = f"{round((repeat_users / active_users) * 100)}%" if active_users else "0%"

    # ── Pinned (satisfaction proxy) ───────────────────────────────────────────
    pinned_res = await db.execute(
        select(func.count(AIHistory.id)).where(AIHistory.pinned.is_(True))
    )
    pinned_count: int = pinned_res.scalar_one() or 0
    satisfaction = f"{round((pinned_count / total_queries) * 100)}%" if total_queries else "0%"

    return {
        "usage": {
            "totalQueries": _metric(
                f"{total_queries:,}",
                (
                    _pct_change(total_queries, total_queries - last30)
                    if total_queries > last30
                    else None
                ),
                True,
            ),
            "last30Days": _metric(
                f"{last30:,}",
                growth_str,
                (last30 >= prev30) if growth_str else None,
            ),
            "growth": _metric(
                growth_str or ("N/A" if not prev30 else "0%"),
                None,
            ),
            "avgFrequency": _metric(f"{avg_freq}/day"),
        },
        "performance": await _performance_metrics(db),
        "engagement": {
            "activeUsers": _metric(
                f"{active_users} / {total_users}",
                f"{round((active_users / total_users) * 100)}% active" if total_users else None,
                True,
            ),
            "topUsersGroup": _metric(top_category),
            "recurrenceRate": _metric(recurrence_rate),
            "satisfactionRate": _metric(satisfaction),
        },
    }


# ── Connection Metrics ─────────────────────────────────────────────────────────


def _format_duration(avg_ms: Optional[float]) -> str:
    """Render an AVG(duration_ms) value as a short human label."""
    if avg_ms is None:
        return "N/A"
    if avg_ms >= 1_000:
        return f"{avg_ms / 1000.0:.1f}s"
    return f"{int(avg_ms)}ms"


def _format_last_sync(conn: Optional[DataConnection]) -> str:
    """Render DataConnection.last_sync + error as a compact status string.

    Shape: "OK — 2h ago" / "Error — 15m ago" / "Never" / "–".
    Honest surrogate for the "Sync Failures" hardcoded to 0 before: we
    don't track per-sync event history, but we do persist the latest
    sync timestamp and the current error JSON.
    """
    if conn is None:
        return "–"
    last = conn.last_sync
    if last is None:
        return "Never"
    status = "Error" if conn.error else "OK"
    delta = _now() - last
    seconds = int(delta.total_seconds())
    if seconds < 60:
        ago = f"{seconds}s ago"
    elif seconds < 3_600:
        ago = f"{seconds // 60}m ago"
    elif seconds < 86_400:
        ago = f"{seconds // 3600}h ago"
    else:
        ago = f"{seconds // 86_400}d ago"
    return f"{status} — {ago}"


@router.get("/connections/{connection_id}", response_model=ConnectionMetricsResponse)
async def get_connection_metrics(
    connection_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get metrics for a specific connection (or 'all').

    Scoping note: AIHistory rows are not tied directly to a connection —
    only to a space. We attribute a query to a connection when the
    connection lives in a space that also produced the query (via
    SpaceConnection). This is a proxy; a space with two connections will
    over-attribute, but it's consistent with the rest of the endpoint
    and matches the previous scoping logic.
    """
    await RBACService(db).assert_permission(current_user, "connections.view")

    now = _now()
    ago_30 = now - timedelta(days=30)

    # Resolve the connection row (used for lastSync + as the anchor for
    # Widget counts). May be None when connection_id == "all".
    conn_row: Optional[DataConnection] = None
    conn_uuid: Optional[UUID] = None
    if connection_id != "all":
        try:
            conn_uuid = UUID(connection_id)
        except ValueError:
            conn_uuid = None
        if conn_uuid is not None:
            conn_res = await db.execute(
                select(DataConnection).where(DataConnection.id == conn_uuid)
            )
            conn_row = conn_res.scalar_one_or_none()

    # Queries that reference this connection (via space_id)
    base_filter = []
    if connection_id != "all":
        from src.models.space import SpaceConnection

        space_ids_res = await db.execute(
            select(SpaceConnection.space_id).where(SpaceConnection.connection_id == connection_id)
        )
        space_ids = [str(r[0]) for r in space_ids_res.fetchall()]
        if space_ids:
            base_filter.append(AIHistory.space_id.in_(space_ids))
        else:
            # No spaces linked to this connection — still emit Widget and
            # lastSync metrics (those don't depend on history).
            widgets_count = 0
            if conn_uuid is not None:
                w_res = await db.execute(
                    select(func.count(Widget.id)).where(Widget.connection_id == conn_uuid)
                )
                widgets_count = w_res.scalar_one() or 0
            return {
                "usage": {
                    "queriesProcessed": _metric("0"),
                    "avgSyncFrequency": _metric("–"),
                },
                "valueMap": {
                    "supportedProcesses": _metric("0"),
                    "dependentWidgets": _metric(str(widgets_count)),
                },
                "reliability": {
                    "lastSync": _metric(_format_last_sync(conn_row)),
                    "avgExecTime": _metric("N/A"),
                },
            }

    # Queries processed (total + last 30d)
    q_total_res = await db.execute(
        select(func.count(AIHistory.id)).where(*base_filter)
        if base_filter
        else select(func.count(AIHistory.id))
    )
    q_total: int = q_total_res.scalar_one() or 0

    q_30_res = await db.execute(
        select(func.count(AIHistory.id)).where(*base_filter, AIHistory.date >= ago_30)
        if base_filter
        else select(func.count(AIHistory.id)).where(AIHistory.date >= ago_30)
    )
    q_30: int = q_30_res.scalar_one() or 0

    # Spaces using this connection
    if connection_id != "all":
        processes_res = await db.execute(
            select(func.count(distinct(AIHistory.space_id))).where(*base_filter)
        )
    else:
        processes_res = await db.execute(select(func.count(distinct(AIHistory.space_id))))
    supported_processes: int = processes_res.scalar_one() or 0

    # Dependent widgets — real count via Widget.connection_id. For "all"
    # we count every widget bound to any connection.
    if connection_id != "all" and conn_uuid is not None:
        w_res = await db.execute(
            select(func.count(Widget.id)).where(Widget.connection_id == conn_uuid)
        )
    else:
        w_res = await db.execute(
            select(func.count(Widget.id)).where(Widget.connection_id.is_not(None))
        )
    widgets_count: int = w_res.scalar_one() or 0

    # Avg exec time — real AVG(duration_ms). NULL rows predate the column
    # and are excluded (see AIHistory.duration_ms comment).
    avg_q = (
        select(func.avg(AIHistory.duration_ms)).where(
            *base_filter,
            AIHistory.duration_ms.is_not(None),
        )
        if base_filter
        else select(func.avg(AIHistory.duration_ms)).where(AIHistory.duration_ms.is_not(None))
    )
    avg_ms_res = await db.execute(avg_q)
    avg_ms_raw = avg_ms_res.scalar_one_or_none()
    avg_ms = float(avg_ms_raw) if avg_ms_raw is not None else None

    return {
        "usage": {
            "queriesProcessed": _metric(
                f"{q_total:,}",
                _pct_change(q_30, q_total - q_30) if q_total > q_30 else None,
                True,
            ),
            "avgSyncFrequency": _metric(f"{round(q_30 / 30, 1)}/day"),
        },
        "valueMap": {
            "supportedProcesses": _metric(str(supported_processes)),
            "dependentWidgets": _metric(str(widgets_count)),
        },
        "reliability": {
            "lastSync": _metric(_format_last_sync(conn_row)),
            "avgExecTime": _metric(_format_duration(avg_ms)),
        },
    }


# ── Space Metrics ──────────────────────────────────────────────────────────────


@router.get("/spaces/{space_id}", response_model=SpaceMetricsResponse)
async def get_space_metrics(
    space_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get metrics for a specific space (or 'all')."""
    await RBACService(db).assert_permission(current_user, "connections.view")

    now = _now()
    ago_30 = now - timedelta(days=30)

    # Build filter
    if space_id != "all":
        hist_filter = AIHistory.space_id == space_id
    else:
        hist_filter = None

    # Queries in this space
    q = select(func.count(AIHistory.id))
    if hist_filter is not None:
        q = q.where(hist_filter)
    total_res = await db.execute(q)
    total: int = total_res.scalar_one() or 0

    # Active users per space
    q2 = select(func.count(distinct(AIHistory.user_id))).where(AIHistory.date >= ago_30)
    if hist_filter is not None:
        q2 = q2.where(hist_filter)
    active_users_res = await db.execute(q2)
    active_users: int = active_users_res.scalar_one() or 0

    # Interaction volume last 30d
    q3 = select(func.count(AIHistory.id)).where(AIHistory.date >= ago_30)
    if hist_filter is not None:
        q3 = q3.where(hist_filter)
    interactions_res = await db.execute(q3)
    interactions: int = interactions_res.scalar_one() or 0

    # Spaces / crews in this space (network growth proxy)
    if space_id != "all":
        crews_res = await db.execute(select(func.count(Crew.id)).where(Crew.space_id == space_id))
    else:
        crews_res = await db.execute(select(func.count(Crew.id)))
    crews_count: int = crews_res.scalar_one() or 0

    # Cross-collab: queries with a crew_id (collaborative queries)
    q4 = select(func.count(AIHistory.id)).where(AIHistory.crew_id.isnot(None))
    if hist_filter is not None:
        q4 = q4.where(hist_filter)
    collab_res = await db.execute(q4)
    collab_count: int = collab_res.scalar_one() or 0
    cross_collab = f"{round((collab_count / total) * 100)}%" if total else "0%"

    return {
        "usageVolume": {
            "activityPerSpace": _metric(f"{total:,} queries"),
            "avgEngagement": _metric(f"{active_users} users"),
            "interactionVolume": _metric(f"{interactions:,} last 30d"),
        },
        "networkHealth": {
            "networkGrowth": _metric(f"{crews_count} crews"),
            "crossCollaboration": _metric(cross_collab),
        },
    }


# ── Crew Metrics ───────────────────────────────────────────────────────────────


@router.get("/crews/{crew_id}", response_model=CrewMetricsResponse)
async def get_crew_metrics(
    crew_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get metrics for a specific crew (or 'all')."""
    await RBACService(db).assert_permission(current_user, "connections.view")

    now = _now()
    ago_30 = now - timedelta(days=30)

    if crew_id != "all":
        hist_filter = AIHistory.crew_id == crew_id
    else:
        hist_filter = AIHistory.crew_id.isnot(None)

    # Usage frequency
    q_30_res = await db.execute(
        select(func.count(AIHistory.id)).where(hist_filter, AIHistory.date >= ago_30)
    )
    q_30: int = q_30_res.scalar_one() or 0

    # Active sessions proxy = distinct user+date combinations
    sessions_res = await db.execute(
        select(
            func.count(
                distinct(
                    func.concat(
                        cast(AIHistory.user_id, type_=type(AIHistory.user_id)),
                        ":",
                        func.date(AIHistory.date),
                    )
                )
            )
        ).where(hist_filter, AIHistory.date >= ago_30)
    )
    active_sessions: int = sessions_res.scalar_one() or 0

    # Avg response time — real AVG(duration_ms) scoped by crew. NULL
    # rows (pre-duration_ms column) are excluded. Falls back to "N/A"
    # when no measured rows exist.
    avg_ms_res = await db.execute(
        select(func.avg(AIHistory.duration_ms)).where(
            hist_filter, AIHistory.duration_ms.is_not(None)
        )
    )
    avg_ms_raw = avg_ms_res.scalar_one_or_none()
    avg_ms = float(avg_ms_raw) if avg_ms_raw is not None else None

    return {
        "engagement": {
            "usageFrequency": _metric(f"{q_30:,} queries / 30d"),
            "activeSessions": _metric(str(active_sessions)),
        },
        "performance": {
            "avgResponseTime": _metric(_format_duration(avg_ms)),
        },
    }


# ── User Metrics ───────────────────────────────────────────────────────────────


@router.get("/users/{user_id}", response_model=UserMetricsResponse)
async def get_user_metrics(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get metrics for a specific user (or 'all')."""
    await RBACService(db).assert_permission(current_user, "connections.view")

    now = _now()
    ago_30 = now - timedelta(days=30)

    if user_id != "all":
        try:
            uid = UUID(user_id)
        except ValueError:
            uid = None
        hist_filter = AIHistory.user_id == uid if uid else None
    else:
        hist_filter = None

    # Queries per period
    q_count_query = select(func.count(AIHistory.id)).where(AIHistory.date >= ago_30)
    if hist_filter is not None:
        q_count_query = q_count_query.where(hist_filter)
    q_count_res = await db.execute(q_count_query)
    q_count: int = q_count_res.scalar_one() or 0

    # Recurrence: queried in prev 30d as well
    prev_q_query = select(func.count(AIHistory.id)).where(
        AIHistory.date >= (ago_30 - timedelta(days=30)),
        AIHistory.date < ago_30,
    )
    if hist_filter is not None:
        prev_q_query = prev_q_query.where(hist_filter)
    prev_res = await db.execute(prev_q_query)
    prev_q: int = prev_res.scalar_one() or 0
    recurrence = "Returning" if prev_q > 0 else ("New" if q_count > 0 else "Inactive")

    # Satisfaction: ratio of pinned items
    pinned_query = select(func.count(AIHistory.id)).where(AIHistory.pinned.is_(True))
    if hist_filter is not None:
        pinned_query = pinned_query.where(hist_filter)
    pinned_res = await db.execute(pinned_query)
    pinned_count: int = pinned_res.scalar_one() or 0
    satisfaction = f"{round((pinned_count / q_count) * 100)}%" if q_count else "0%"

    return {
        "individualPatterns": {
            "queriesPerPeriod": _metric(f"{q_count:,} last 30d"),
            "recurrence": _metric(recurrence),
            "satisfactionScore": _metric(satisfaction),
        }
    }


# ── AI Performance ─────────────────────────────────────────────────────────────


@router.get("/ai", response_model=AiMetricsResponse)
async def get_ai_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get AI effectiveness metrics from real interaction data.

    Accuracy & corrections are computed from AIFeedback rows. When no
    feedback exists yet we return "N/A" rather than the old 5% estimate
    fallback — fabricated numbers were misleading operators into
    thinking accuracy was being measured.
    """
    await RBACService(db).assert_permission(current_user, "connections.view")

    # Total queries
    total_res = await db.execute(select(func.count(AIHistory.id)))
    total: int = total_res.scalar_one() or 0

    # Pinned (positive signal — user found it useful enough to save)
    pinned_res = await db.execute(
        select(func.count(AIHistory.id)).where(AIHistory.pinned.is_(True))
    )
    pinned: int = pinned_res.scalar_one() or 0

    # Insight acceptance = % pinned (real, always available)
    acceptance_rate = f"{round((pinned / total) * 100)}%" if total else "0%"

    # Real corrections & accuracy from AIFeedback. The rating column
    # stores the string 'good' / 'bad' (see src/models/ai.py
    # CheckConstraint). If no feedback exists yet, we return "N/A"
    # instead of guessing.
    bad_feedback_res = await db.execute(
        select(func.count(AIFeedback.id)).where(AIFeedback.rating == "bad")
    )
    bad_feedback: int = bad_feedback_res.scalar_one() or 0
    any_feedback_res = await db.execute(select(func.count(AIFeedback.id)))
    any_feedback: int = any_feedback_res.scalar_one() or 0

    if any_feedback > 0:
        corrections_label = str(bad_feedback)
        accuracy_label = f"{round(((any_feedback - bad_feedback) / any_feedback) * 100)}%"
    else:
        corrections_label = "N/A"
        accuracy_label = "N/A"

    # Real avg latency (same source as global Performance metrics).
    perf = await _performance_metrics(db)

    return {
        "engineEffectiveness": {
            "perceivedAccuracy": _metric(accuracy_label),
            "correctionsMade": _metric(corrections_label),
            "insightAcceptanceRate": _metric(acceptance_rate),
            "averageLatency": perf["avgLatency"],
        }
    }
