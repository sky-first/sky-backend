from typing import List

from fastapi import APIRouter, Depends, Query, status, HTTPException

from src.api.deps import get_current_user
from src.models.user import User
from src.repositories.signal_event import get_signal_event_repo, SignalEventRepository
from src.schemas.signal_event import SignalEventCreate, SignalEventUpdate, SignalEventResponse

router = APIRouter()


@router.get("/", response_model=List[SignalEventResponse])
async def list_signal_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    repo: SignalEventRepository = Depends(get_signal_event_repo),
):
    """List all signal events."""
    return await repo.get_all(skip=skip, limit=limit, order_by="created_at")


@router.post("/", response_model=SignalEventResponse, status_code=status.HTTP_201_CREATED)
async def create_signal_event(
    event_in: SignalEventCreate,
    current_user: User = Depends(get_current_user),
    repo: SignalEventRepository = Depends(get_signal_event_repo),
):
    """Create a new signal event."""
    return await repo.create(**event_in.model_dump())


@router.get("/{event_id}", response_model=SignalEventResponse)
async def get_signal_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    repo: SignalEventRepository = Depends(get_signal_event_repo),
):
    """Get a specific signal event by ID."""
    event = await repo.get_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Signal event not found")
    return event


@router.put("/{event_id}", response_model=SignalEventResponse)
async def update_signal_event(
    event_id: str,
    event_in: SignalEventUpdate,
    current_user: User = Depends(get_current_user),
    repo: SignalEventRepository = Depends(get_signal_event_repo),
):
    """Update a signal event."""
    event = await repo.get_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Signal event not found")

    return await repo.update(event_id, **event_in.model_dump(exclude_unset=True))


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_signal_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    repo: SignalEventRepository = Depends(get_signal_event_repo),
):
    """Delete a signal event."""
    event = await repo.get_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Signal event not found")

    await repo.delete(event_id)
    return None
