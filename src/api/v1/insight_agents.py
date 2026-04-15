"""Insight-mode agent endpoints.

Mounted at /api/v1/agents/insight so the existing /api/v1/agents endpoints
for question/datasource/sql mode agents stay untouched.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.insight_agent import (
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
