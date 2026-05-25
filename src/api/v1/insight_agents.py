"""Insight-mode agent endpoints.

Mounted at /api/v1/agents/insight so the existing /api/v1/agents endpoints
for question/datasource/sql mode agents stay untouched.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.agent import Agent, AgentExecution
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.insight_agent import (
    AgentExecutionResponse,
    InsightAgentCreate,
    InsightAgentResponse,
    InsightAgentUpdate,
)
from src.services.insight_agent_service import InsightAgentService


router = APIRouter()


@router.post(
    "",
    response_model=InsightAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an insight-mode agent bound to a widget (B1)",
    responses={404: {"model": ErrorResponse}},
)
async def create_insight_agent(
    payload: InsightAgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightAgentResponse:
    service = InsightAgentService(db)
    try:
        agent = await service.create(current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return InsightAgentResponse.model_validate(agent)


@router.get(
    "",
    response_model=List[InsightAgentResponse],
    summary="List insight agents created by the current user",
)
async def list_insight_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[InsightAgentResponse]:
    service = InsightAgentService(db)
    agents = await service.list_for_user(current_user)
    return [InsightAgentResponse.model_validate(a) for a in agents]


# ─── Phase 3.5 — Agent Activity feed ─────────────────────────────────────
# Declared BEFORE /{agent_id} so "executions" isn't captured as a UUID path
# parameter — FastAPI matches routes in declaration order.
@router.get(
    "/executions",
    response_model=List[AgentExecutionResponse],
    summary="List the current user's recent agent executions (Agent Activity tab)",
)
async def list_recent_executions(
    agent_id: Optional[UUID] = Query(
        None,
        description="Optional: filter to a single agent. Omit to see the user's whole feed.",
    ),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[AgentExecutionResponse]:
    """Return up to `limit` most-recent executions for the agents the
    caller owns. Used by Settings → Agent Activity to render a cross-
    agent feed; also re-used (filtered by `agent_id`) on the per-agent
    detail panel.

    Security note: we resolve the caller's agents first and constrain
    the execution query to those ids. This keeps the endpoint safe
    even if `agent_id` is passed for someone else's agent — the join
    simply yields zero rows.
    """
    # Agents owned by the current user — cheap lookup, small set.
    owned_res = await db.execute(
        select(Agent.id, Agent.name, Agent.widget_id).where(
            Agent.created_by == current_user.id
        )
    )
    agents_by_id: dict[UUID, tuple[str, Optional[UUID]]] = {
        row.id: (row.name, row.widget_id) for row in owned_res
    }

    if not agents_by_id:
        return []

    allowed_ids = set(agents_by_id.keys())
    if agent_id is not None:
        if agent_id not in allowed_ids:
            # Not the user's agent — return empty rather than leak existence.
            return []
        allowed_ids = {agent_id}

    stmt = (
        select(AgentExecution)
        .where(AgentExecution.agent_id.in_(allowed_ids))
        .order_by(AgentExecution.started_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    executions = result.scalars().all()

    out: list[AgentExecutionResponse] = []
    for e in executions:
        agent_name, widget_id = agents_by_id.get(e.agent_id, (None, None))
        out.append(
            AgentExecutionResponse.model_validate(
                {
                    "id": e.id,
                    "agent_id": e.agent_id,
                    "status": e.status,
                    "cycles_consumed": e.cycles_consumed,
                    "findings_count": e.findings_count,
                    "error_message": e.error_message,
                    "delta_kind": e.delta_kind,
                    "delta_summary": e.delta_summary,
                    "llm_tokens_used": e.llm_tokens_used,
                    "llm_cost_usd": float(e.llm_cost_usd) if e.llm_cost_usd is not None else None,
                    "context_doc_ids": list(e.context_doc_ids or []),
                    "context_intent": e.context_intent,
                    "started_at": e.started_at,
                    "finished_at": e.finished_at,
                    "duration_ms": e.duration_ms,
                    "agent_name": agent_name,
                    "widget_id": widget_id,
                }
            )
        )
    return out


@router.get(
    "/{agent_id}",
    response_model=InsightAgentResponse,
    summary="Get a single insight agent",
    responses={404: {"model": ErrorResponse}},
)
async def get_insight_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightAgentResponse:
    service = InsightAgentService(db)
    try:
        agent = await service.get(agent_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return InsightAgentResponse.model_validate(agent)


@router.put(
    "/{agent_id}",
    response_model=InsightAgentResponse,
    summary="Update schedule / name / notify settings (B6)",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_insight_agent(
    agent_id: UUID,
    payload: InsightAgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightAgentResponse:
    service = InsightAgentService(db)
    try:
        agent = await service.update(agent_id, current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return InsightAgentResponse.model_validate(agent)


@router.post(
    "/{agent_id}/pause",
    response_model=InsightAgentResponse,
    summary="Pause an agent (B7)",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def pause_insight_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightAgentResponse:
    service = InsightAgentService(db)
    try:
        agent = await service.pause(agent_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return InsightAgentResponse.model_validate(agent)


@router.post(
    "/{agent_id}/resume",
    response_model=InsightAgentResponse,
    summary="Resume a paused agent (B8)",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def resume_insight_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightAgentResponse:
    service = InsightAgentService(db)
    try:
        agent = await service.resume(agent_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return InsightAgentResponse.model_validate(agent)


@router.post(
    "/{agent_id}/run-now",
    response_model=InsightAgentResponse,
    summary="Bypass the schedule and request an immediate run (B10)",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def run_now_insight_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightAgentResponse:
    service = InsightAgentService(db)
    try:
        agent = await service.run_now(agent_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return InsightAgentResponse.model_validate(agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End an agent (B9 — preserves runs/findings for audit)",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def delete_insight_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    service = InsightAgentService(db)
    try:
        await service.delete(agent_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
