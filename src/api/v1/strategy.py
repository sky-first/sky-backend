"""Strategy API router."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.strategy import (
    StrategicObjectiveCreate,
    StrategicObjectiveResponse,
    StrategicObjectiveUpdate,
    StrategicPillarCreate,
    StrategicPillarResponse,
    StrategicPillarUpdate,
    StrategyAssumptionCreate,
    StrategyAssumptionResponse,
    StrategyAssumptionUpdate,
    StrategyCycleCreate,
    StrategyCycleResponse,
    StrategyCycleUpdate,
    StrategyHealthResponse,
    StrategyInitiativeCreate,
    StrategyInitiativeResponse,
    StrategyInitiativeUpdate,
    StrategyKeyResultCreate,
    StrategyKeyResultResponse,
    StrategyKeyResultUpdate,
    StrategyOKRCreate,
    StrategyOKRResponse,
    StrategyOKRUpdate,
    StrategyTreeResponse,
)
from src.services.strategy import StrategyService
from src.services.rbac_service import RBACService

router = APIRouter()


def get_service(db: AsyncSession = Depends(get_db)) -> StrategyService:
    return StrategyService(db)


@router.get("/tree", response_model=StrategyTreeResponse)
async def get_strategy_tree(
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyTreeResponse:
    """Get the full strategy tree."""
    await RBACService(db).assert_permission(current_user, "pages.view")
    return await service.get_strategy_tree(space_id=space_id, crew_id=crew_id)


@router.get("/health", response_model=StrategyHealthResponse)
async def get_strategy_health(
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyHealthResponse:
    """Get strategy health metrics."""
    await RBACService(db).assert_permission(current_user, "pages.view")
    return await service.get_strategy_health(space_id=space_id, crew_id=crew_id)


# --- Strategic Pillar ---


@router.post("/pillars", response_model=StrategicPillarResponse, status_code=201)
async def create_pillar(
    body: StrategicPillarCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicPillarResponse:
    """Create a new strategic pillar."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_pillar(body, background_tasks)


@router.put("/pillars/{pillar_id}", response_model=StrategicPillarResponse)
async def update_pillar(
    pillar_id: UUID,
    body: StrategicPillarUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicPillarResponse:
    """Update a strategic pillar."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_pillar(pillar_id, body, background_tasks)


@router.delete("/pillars/{pillar_id}", status_code=204)
async def delete_pillar(
    pillar_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategic pillar."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_pillar(pillar_id)


# --- Strategic Objective ---


@router.post("/objectives", response_model=StrategicObjectiveResponse, status_code=201)
async def create_objective(
    body: StrategicObjectiveCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicObjectiveResponse:
    """Create a new strategic objective."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_objective(body, background_tasks)


@router.put("/objectives/{objective_id}", response_model=StrategicObjectiveResponse)
async def update_objective(
    objective_id: UUID,
    body: StrategicObjectiveUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicObjectiveResponse:
    """Update a strategic objective."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_objective(objective_id, body, background_tasks)


@router.delete("/objectives/{objective_id}", status_code=204)
async def delete_objective(
    objective_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategic objective."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_objective(objective_id)


# --- Strategy OKR ---


@router.post("/okrs", response_model=StrategyOKRResponse, status_code=201)
async def create_okr(
    body: StrategyOKRCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyOKRResponse:
    """Create a new strategy OKR."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_okr(body, background_tasks)


@router.put("/okrs/{okr_id}", response_model=StrategyOKRResponse)
async def update_okr(
    okr_id: UUID,
    body: StrategyOKRUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyOKRResponse:
    """Update a strategy OKR."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_okr(okr_id, body, background_tasks)


@router.delete("/okrs/{okr_id}", status_code=204)
async def delete_okr(
    okr_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy OKR."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_okr(okr_id)


@router.post("/initiatives", response_model=StrategyInitiativeResponse, status_code=201)
async def create_initiative(
    body: StrategyInitiativeCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyInitiativeResponse:
    """Create a new strategy initiative."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_initiative(body, background_tasks)


@router.put("/initiatives/{initiative_id}", response_model=StrategyInitiativeResponse)
async def update_initiative(
    initiative_id: UUID,
    body: StrategyInitiativeUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyInitiativeResponse:
    """Update a strategy initiative."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_initiative(initiative_id, body, background_tasks)


@router.delete("/initiatives/{initiative_id}", status_code=204)
async def delete_initiative(
    initiative_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy initiative."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_initiative(initiative_id)


# --- Strategy Assumption ---


@router.post("/assumptions", response_model=StrategyAssumptionResponse, status_code=201)
async def create_assumption(
    body: StrategyAssumptionCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyAssumptionResponse:
    """Create a new strategy assumption."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_assumption(body, background_tasks)


@router.put("/assumptions/{assumption_id}", response_model=StrategyAssumptionResponse)
async def update_assumption(
    assumption_id: UUID,
    body: StrategyAssumptionUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyAssumptionResponse:
    """Update a strategy assumption."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_assumption(assumption_id, body, background_tasks)


@router.delete("/assumptions/{assumption_id}", status_code=204)
async def delete_assumption(
    assumption_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy assumption."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_assumption(assumption_id)


# --- Strategy Cycle ---


@router.post("/cycles", response_model=StrategyCycleResponse, status_code=201)
async def create_cycle(
    body: StrategyCycleCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyCycleResponse:
    """Create a new strategy cycle."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_cycle(body, background_tasks)


@router.put("/cycles/{cycle_id}", response_model=StrategyCycleResponse)
async def update_cycle(
    cycle_id: UUID,
    body: StrategyCycleUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyCycleResponse:
    """Update a strategy cycle."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_cycle(cycle_id, body, background_tasks)


@router.delete("/cycles/{cycle_id}", status_code=204)
async def delete_cycle(
    cycle_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy cycle."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_cycle(cycle_id)


# --- Strategy Key Result ---


@router.post("/key-results", response_model=StrategyKeyResultResponse, status_code=201)
async def create_key_result(
    body: StrategyKeyResultCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyKeyResultResponse:
    """Create a new strategy key result."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.create_key_result(body, background_tasks)


@router.put("/key-results/{kr_id}", response_model=StrategyKeyResultResponse)
async def update_key_result(
    kr_id: UUID,
    body: StrategyKeyResultUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyKeyResultResponse:
    """Update a strategy key result."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    return await service.update_key_result(kr_id, body, background_tasks)


@router.delete("/key-results/{kr_id}", status_code=204)
async def delete_key_result(
    kr_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy key result."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    await service.delete_key_result(kr_id)
