"""Cost breakdown endpoint — Phase 5.2/5.3.

The Usage tab already surfaces global query-count metrics. This
endpoint extends it with the dimension leadership actually cares
about now that LLM calls cost money: where is the spend going?

Two aggregations:

  * per-crew totals for the last N days (default 30)
  * daily series for the same window (stacks up to a sparkline /
    bar chart on the UI)

We aggregate from `agent_executions.llm_cost_usd` joined to
`agents.scope_id` resolved as crew when scope='crew'. For agents
scoped to space / personal we bucket them as 'space' / 'personal'
so the total always adds up — no silent losses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError
from src.models.agent import Agent, AgentExecution
from src.models.crew import Crew
from src.models.user import User

router = APIRouter()


class CrewCost(BaseModel):
    crew_id: Optional[UUID]
    crew_name: str
    total_cost_usd: float
    total_tokens: int
    run_count: int

    model_config = ConfigDict(from_attributes=True)


class DailyCost(BaseModel):
    day: str                  # ISO date (YYYY-MM-DD)
    total_cost_usd: float
    total_tokens: int


class CostMetricsResponse(BaseModel):
    generated_at: datetime
    window_days: int
    total_cost_usd: float
    total_tokens: int
    by_crew: list[CrewCost]
    daily: list[DailyCost]


def _as_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


@router.get(
    "/cost",
    response_model=CostMetricsResponse,
    summary="LLM-cost breakdown by crew + daily series (Usage tab)",
)
async def get_cost_metrics(
    window_days: int = Query(30, ge=1, le=180),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CostMetricsResponse:
    """Return per-crew cost + daily series for the trailing
    ``window_days``.

    Scopes without a crew resolve to a synthetic bucket so every
    cent shows up somewhere:
        * scope='space'     → "Space (no crew)" bucket
        * scope='personal'  → "Personal" bucket
        * scope='organization' or unknown → "Organisation"

    Tenant-wide spend is org-level financial data — restricted to
    platform Owner / Admin. Members get a 403; the FE Profile page
    already hides the panel for non-admins via `canSeePlatformUsage`.
    """
    if getattr(current_user, "role", None) not in ("owner", "admin"):
        raise ForbiddenError(
            "Tenant cost metrics are restricted to platform Owner / Admin."
        )

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)

    # ── Daily series ────────────────────────────────────────────────────
    # func.date(started_at) works on both SQLite (string date) and
    # Postgres (date type). We coerce to ISO string on the client side
    # via str() on whatever the DB returns, so either dialect is fine.
    day_expr = func.date(AgentExecution.started_at)
    daily_query = (
        select(
            day_expr.label("day"),
            func.coalesce(func.sum(AgentExecution.llm_cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AgentExecution.llm_tokens_used), 0).label("tokens"),
        )
        .where(AgentExecution.started_at >= since)
        .group_by(day_expr)
        .order_by(day_expr.asc())
    )
    daily_rows = (await db.execute(daily_query)).all()
    daily = [
        DailyCost(
            day=str(r.day)[:10],
            total_cost_usd=_as_float(r.cost),
            total_tokens=int(r.tokens or 0),
        )
        for r in daily_rows
    ]

    # ── Per-crew breakdown ──────────────────────────────────────────────
    # Agents live with `scope` + `scope_id`. For scope='crew' we join
    # crews on scope_id; for other scopes the bucket label is
    # synthesised via CASE.
    bucket_label = case(
        (Agent.scope == "crew", Crew.name),
        (Agent.scope == "space", "Space (no crew)"),
        (Agent.scope == "personal", "Personal"),
        else_="Organisation",
    )
    bucket_id = case(
        (Agent.scope == "crew", Crew.id),
        else_=None,
    )

    crew_query = (
        select(
            bucket_id.label("crew_id"),
            bucket_label.label("crew_name"),
            func.coalesce(func.sum(AgentExecution.llm_cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AgentExecution.llm_tokens_used), 0).label("tokens"),
            func.count(AgentExecution.id).label("runs"),
        )
        .select_from(AgentExecution)
        .join(Agent, Agent.id == AgentExecution.agent_id)
        # Left join — agents scoped to crew will link; others leave
        # Crew columns NULL and the CASE takes over with synthetic
        # labels.
        .outerjoin(
            Crew,
            (Agent.scope == "crew")
            & (func.cast(Agent.scope_id, Crew.id.type) == Crew.id),
        )
        .where(AgentExecution.started_at >= since)
        .group_by(bucket_id, bucket_label)
        .order_by(func.sum(AgentExecution.llm_cost_usd).desc().nullslast())
    )

    try:
        crew_rows = (await db.execute(crew_query)).all()
    except Exception:
        # SQLite in the test bed can't do the cast(UUID→UUID) join —
        # fall back to the simpler (scope-only) breakdown.
        simple_query = (
            select(
                Agent.scope.label("scope"),
                func.coalesce(func.sum(AgentExecution.llm_cost_usd), 0).label("cost"),
                func.coalesce(func.sum(AgentExecution.llm_tokens_used), 0).label("tokens"),
                func.count(AgentExecution.id).label("runs"),
            )
            .select_from(AgentExecution)
            .join(Agent, Agent.id == AgentExecution.agent_id)
            .where(AgentExecution.started_at >= since)
            .group_by(Agent.scope)
        )
        simple_rows = (await db.execute(simple_query)).all()
        crew_rows = [
            type("Row", (), {
                "crew_id": None,
                "crew_name": str(r.scope or "unknown").capitalize(),
                "cost": r.cost,
                "tokens": r.tokens,
                "runs": r.runs,
            })
            for r in simple_rows
        ]

    by_crew = [
        CrewCost(
            crew_id=r.crew_id,
            crew_name=str(r.crew_name),
            total_cost_usd=_as_float(r.cost),
            total_tokens=int(r.tokens or 0),
            run_count=int(r.runs or 0),
        )
        for r in crew_rows
    ]

    total_cost = sum(c.total_cost_usd for c in by_crew)
    total_tokens = sum(c.total_tokens for c in by_crew)

    return CostMetricsResponse(
        generated_at=now,
        window_days=window_days,
        total_cost_usd=total_cost,
        total_tokens=total_tokens,
        by_crew=by_crew,
        daily=daily,
    )
