from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.signal_event import SignalEventCreate, SignalEventResponse, SignalEventUpdate
from src.services.signal_event_service import SignalEventService
from src.services.rbac_service import RBACService

router = APIRouter()


async def get_signal_event_service(
    db: AsyncSession = Depends(get_db),
) -> SignalEventService:
    return SignalEventService(db)


@router.get("/", response_model=List[SignalEventResponse])
async def list_signal_events(
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """List signal events with tenant filtering."""
    await RBACService(db).assert_permission(current_user, "strategy.view")
    return await service.list_events(space_id=space_id, crew_id=crew_id)


@router.post("/", response_model=SignalEventResponse, status_code=status.HTTP_201_CREATED)
async def create_signal_event(
    event_in: SignalEventCreate,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Create a new signal event within a tenant context."""
    await RBACService(db).assert_permission(current_user, "strategy.pillars.edit")
    return await service.create_event(event_in, space_id=space_id, crew_id=crew_id)


@router.get("/{event_id}", response_model=SignalEventResponse)
async def get_signal_event(
    event_id: UUID,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific signal event by ID with tenant validation."""
    await RBACService(db).assert_permission(current_user, "strategy.view")
    return await service.get_event(event_id, space_id=space_id, crew_id=crew_id)


@router.put("/{event_id}", response_model=SignalEventResponse)
async def update_signal_event(
    event_id: UUID,
    event_in: SignalEventUpdate,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Update a signal event with tenant validation."""
    await RBACService(db).assert_permission(current_user, "strategy.pillars.edit")
    return await service.update_event(event_id, event_in, space_id=space_id, crew_id=crew_id)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_signal_event(
    event_id: UUID,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Delete a signal event with tenant validation."""
    await RBACService(db).assert_permission(current_user, "strategy.pillars.edit")
    await service.delete_event(event_id, space_id=space_id, crew_id=crew_id)
    return None
