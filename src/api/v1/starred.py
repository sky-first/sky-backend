"""Starred items endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.services.starred_service import StarredItemService

router = APIRouter()


@router.get(
    "",
    response_model=List[dict],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List starred items",
    description="Get list of all starred items for the current user",
)
async def list_starred_items(
    item_type: Optional[str] = Query(None, pattern="^(planet|space|crew)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[dict]:
    """
    List all starred items for the current user.

    Args:
        item_type: Optional filter by item type (planet, space, or crew)
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[dict]: List of starred items
    """
    starred_service = StarredItemService(db)
    return await starred_service.get_user_starred_items(current_user, item_type)


@router.get(
    "/check/{item_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Check if item is starred",
    description="Check if a specific item is starred by the current user",
)
async def check_starred(
    item_id: UUID,
    item_type: str = Query(..., pattern="^(planet|space|crew)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Check if an item is starred by the current user.

    Args:
        item_id: Item ID to check
        item_type: Item type (planet, space, or crew)
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Object with is_starred boolean
    """
    starred_service = StarredItemService(db)
    is_starred = await starred_service.is_item_starred(current_user, item_id, item_type)
    return {"is_starred": is_starred, "item_id": str(item_id), "item_type": item_type}
