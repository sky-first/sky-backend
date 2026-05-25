"""Comment API endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_current_user
from src.config.database import get_db
from src.models.user import User
from src.schemas.comment import CommentCreate, CommentResponse
from src.services.comment_service import CommentService
from src.services.rbac_service import RBACService

router = APIRouter()


@router.post("", response_model=CommentResponse, status_code=201)
async def create_comment(
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Create a new comment."""
    await RBACService(db).assert_permission(current_user, "pages.view")
    service = CommentService(db)
    return await service.create(current_user.id, comment_data)


@router.get("", response_model=List[CommentResponse])
async def list_comments(
    page_id: UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """List comments for a page."""
    await RBACService(db).assert_permission(current_user, "pages.view")
    service = CommentService(db)
    return await service.get_by_page(page_id)
