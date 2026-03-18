from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.repositories.intelligence_signal import (
    IntelligenceSignalRepository,
    get_intelligence_signal_repo,
)
from src.repositories.planet import PlanetRepository
from src.schemas.intelligence_signal import IntelligenceSignalCreate, IntelligenceSignalResponse
from src.services.rbac_service import RBACService

router = APIRouter()


@router.get("/", response_model=List[IntelligenceSignalResponse])
async def list_signals(
    planet_id: UUID = Query(..., description="Planet ID to filter signals"),
    category: Optional[str] = Query(None, description="Category filter (now, smart, explore)"),
    include_dismissed: bool = Query(False, description="Whether to include dismissed signals"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    repo: IntelligenceSignalRepository = Depends(get_intelligence_signal_repo),
):
    """List intelligence signals for a planet."""
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "viewPlanets")

    # Check if user has access to the planet
    planet_repo = PlanetRepository(db)
    planet = await planet_repo.get_by_id(planet_id)
    if not planet:
        raise HTTPException(status_code=404, detail="Planet not found")

    # In a real scenario, we'd check if user is a member of the planet via RBAC or PlanetMember repo
    # For now, following the simple pattern used in dashboards.py

    return await repo.get_by_planet(
        planet_id, category=category, include_dismissed=include_dismissed
    )


@router.post("/", response_model=IntelligenceSignalResponse, status_code=status.HTTP_201_CREATED)
async def create_signal(
    signal_in: IntelligenceSignalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    repo: IntelligenceSignalRepository = Depends(get_intelligence_signal_repo),
):
    """
    Create a new intelligence signal.
    Typically called by the AI service. Requires editPlanets permission.
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "editPlanets")

    return await repo.create(**signal_in.model_dump())


@router.patch("/{signal_id}/dismiss", response_model=IntelligenceSignalResponse)
async def dismiss_signal(
    signal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    repo: IntelligenceSignalRepository = Depends(get_intelligence_signal_repo),
):
    """Mark a signal as dismissed."""
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "viewPlanets")

    signal = await repo.get_by_id(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    return await repo.update(
        signal_id, is_dismissed=datetime.now(timezone.utc).replace(tzinfo=None)
    )


@router.delete("/{signal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_signal(
    signal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    repo: IntelligenceSignalRepository = Depends(get_intelligence_signal_repo),
):
    """Delete a signal."""
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "editPlanets")

    signal = await repo.get_by_id(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    await repo.delete(signal_id)
    return None
