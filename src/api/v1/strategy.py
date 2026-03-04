"""Strategy API router."""

from uuid import UUID

from fastapi import APIRouter, Depends
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

router = APIRouter()


def get_service(db: AsyncSession = Depends(get_db)) -> StrategyService:
    return StrategyService(db)


@router.get("", response_model=StrategyTreeResponse)
async def get_strategy_tree(
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyTreeResponse:
    """Get the full strategy tree."""
    return await service.get_strategy_tree()


@router.get("/health", response_model=StrategyHealthResponse)
async def get_strategy_health(
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyHealthResponse:
    """Get strategy health metrics."""
    return await service.get_strategy_health()


# --- Strategic Pillar ---

@router.post("/pillars", response_model=StrategicPillarResponse, status_code=201)
async def create_pillar(
    body: StrategicPillarCreate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicPillarResponse:
    """Create a new strategic pillar."""
    return await service.create_pillar(body)


@router.put("/pillars/{pillar_id}", response_model=StrategicPillarResponse)
async def update_pillar(
    pillar_id: UUID,
    body: StrategicPillarUpdate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicPillarResponse:
    """Update a strategic pillar."""
    return await service.update_pillar(pillar_id, body)


@router.delete("/pillars/{pillar_id}", status_code=204)
async def delete_pillar(
    pillar_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategic pillar."""
    await service.delete_pillar(pillar_id)


# --- Strategic Objective ---

@router.post("/objectives", response_model=StrategicObjectiveResponse, status_code=201)
async def create_objective(
    body: StrategicObjectiveCreate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicObjectiveResponse:
    """Create a new strategic objective."""
    return await service.create_objective(body)


@router.put("/objectives/{objective_id}", response_model=StrategicObjectiveResponse)
async def update_objective(
    objective_id: UUID,
    body: StrategicObjectiveUpdate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategicObjectiveResponse:
    """Update a strategic objective."""
    return await service.update_objective(objective_id, body)


@router.delete("/objectives/{objective_id}", status_code=204)
async def delete_objective(
    objective_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategic objective."""
    await service.delete_objective(objective_id)


# --- Strategy OKR ---

@router.post("/okrs", response_model=StrategyOKRResponse, status_code=201)
async def create_okr(
    body: StrategyOKRCreate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyOKRResponse:
    """Create a new strategy OKR."""
    return await service.create_okr(body)


@router.put("/okrs/{okr_id}", response_model=StrategyOKRResponse)
async def update_okr(
    okr_id: UUID,
    body: StrategyOKRUpdate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyOKRResponse:
    """Update a strategy OKR."""
    return await service.update_okr(okr_id, body)


@router.delete("/okrs/{okr_id}", status_code=204)
async def delete_okr(
    okr_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy OKR."""
    await service.delete_okr(okr_id)


# --- Strategy Key Result ---

@router.post("/key-results", response_model=StrategyKeyResultResponse, status_code=201)
async def create_key_result(
    body: StrategyKeyResultCreate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyKeyResultResponse:
    """Create a new key result."""
    return await service.create_key_result(body)


@router.put("/key-results/{key_result_id}", response_model=StrategyKeyResultResponse)
async def update_key_result(
    key_result_id: UUID,
    body: StrategyKeyResultUpdate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyKeyResultResponse:
    """Update a key result."""
    return await service.update_key_result(key_result_id, body)


@router.delete("/key-results/{key_result_id}", status_code=204)
async def delete_key_result(
    key_result_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a key result."""
    await service.delete_key_result(key_result_id)


# --- Strategy Initiative ---

@router.post("/initiatives", response_model=StrategyInitiativeResponse, status_code=201)
async def create_initiative(
    body: StrategyInitiativeCreate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyInitiativeResponse:
    """Create a new strategy initiative."""
    return await service.create_initiative(body)


@router.put("/initiatives/{initiative_id}", response_model=StrategyInitiativeResponse)
async def update_initiative(
    initiative_id: UUID,
    body: StrategyInitiativeUpdate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyInitiativeResponse:
    """Update a strategy initiative."""
    return await service.update_initiative(initiative_id, body)


@router.delete("/initiatives/{initiative_id}", status_code=204)
async def delete_initiative(
    initiative_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy initiative."""
    await service.delete_initiative(initiative_id)


# --- Strategy Assumption ---

@router.post("/assumptions", response_model=StrategyAssumptionResponse, status_code=201)
async def create_assumption(
    body: StrategyAssumptionCreate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyAssumptionResponse:
    """Create a new strategy assumption."""
    return await service.create_assumption(body)


@router.put("/assumptions/{assumption_id}", response_model=StrategyAssumptionResponse)
async def update_assumption(
    assumption_id: UUID,
    body: StrategyAssumptionUpdate,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> StrategyAssumptionResponse:
    """Update a strategy assumption."""
    return await service.update_assumption(assumption_id, body)


@router.delete("/assumptions/{assumption_id}", status_code=204)
async def delete_assumption(
    assumption_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(get_service),
) -> None:
    """Delete a strategy assumption."""
    await service.delete_assumption(assumption_id)
