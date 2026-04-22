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
    is_personal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """List signal events with tenant filtering.

    When ``is_personal`` is true the caller only sees items they created
    in Personal mode (owner_user_id == current user). Otherwise the
    response is scoped to the provided space/crew and excludes any
    other user's Personal events.
    """
    await RBACService(db).assert_permission(current_user, "connections.view")
    return await service.list_events(
        space_id=space_id,
        crew_id=crew_id,
        is_personal=is_personal,
        user_id=current_user.id,
    )


@router.post("/", response_model=SignalEventResponse, status_code=status.HTTP_201_CREATED)
async def create_signal_event(
    event_in: SignalEventCreate,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    is_personal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Create a new signal event.

    Personal scope persists ``owner_user_id=current_user.id`` with NULL
    space/crew. Space/Crew scope persists the space/crew with
    ``owner_user_id=NULL`` — the two flavours never overlap.
    """
    await RBACService(db).assert_permission(current_user, "connections.edit")
    return await service.create_event(
        event_in,
        space_id=space_id,
        crew_id=crew_id,
        is_personal=is_personal,
        user_id=current_user.id,
    )


@router.get("/{event_id}", response_model=SignalEventResponse)
async def get_signal_event(
    event_id: UUID,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    is_personal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific signal event with scope validation."""
    await RBACService(db).assert_permission(current_user, "connections.view")
    return await service.get_event(
        event_id,
        space_id=space_id,
        crew_id=crew_id,
        is_personal=is_personal,
        user_id=current_user.id,
    )


@router.put("/{event_id}", response_model=SignalEventResponse)
async def update_signal_event(
    event_id: UUID,
    event_in: SignalEventUpdate,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    is_personal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Update a signal event with scope validation."""
    await RBACService(db).assert_permission(current_user, "connections.edit")
    return await service.update_event(
        event_id,
        event_in,
        space_id=space_id,
        crew_id=crew_id,
        is_personal=is_personal,
        user_id=current_user.id,
    )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_signal_event(
    event_id: UUID,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    is_personal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    service: SignalEventService = Depends(get_signal_event_service),
    db: AsyncSession = Depends(get_db),
):
    """Delete a signal event with scope validation."""
    await RBACService(db).assert_permission(current_user, "connections.edit")
    await service.delete_event(
        event_id,
        space_id=space_id,
        crew_id=crew_id,
        is_personal=is_personal,
        user_id=current_user.id,
    )
    return None
