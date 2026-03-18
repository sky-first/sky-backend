"""Template endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.template import (
    TemplateApplyRequest,
    TemplateApplyResponse,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)
from src.services.template_service import TemplateService

router = APIRouter()


@router.get(
    "",
    response_model=List[TemplateResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List templates",
    description="Get list of available templates",
)
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search query"),
    popular: Optional[bool] = Query(None, description="Filter popular templates"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[TemplateResponse]:
    """
    List templates.

    Args:
        category: Optional category filter
        search: Optional search query
        popular: Optional popular filter
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[TemplateResponse]: List of templates
    """
    template_service = TemplateService(db)
    return await template_service.list_templates(
        current_user,
        category=category,
        search=search,
        popular=popular,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get template",
    description="Get template by ID",
)
async def get_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TemplateResponse:
    """
    Get template by ID.

    Args:
        template_id: Template ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        TemplateResponse: Template data
    """
    template_service = TemplateService(db)
    return await template_service.get_template(template_id, current_user)


@router.post(
    "",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create template",
    description="Create a new template (Admin only)",
)
async def create_template(
    template_data: TemplateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TemplateResponse:
    """
    Create a new template.

    Args:
        template_data: Template creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        TemplateResponse: Created template
    """
    template_service = TemplateService(db)
    return await template_service.create_template(current_user, template_data)


@router.put(
    "/{template_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update template",
    description="Update template information (Admin only)",
)
async def update_template(
    template_id: UUID,
    template_data: TemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TemplateResponse:
    """
    Update template.

    Args:
        template_id: Template ID
        template_data: Template update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        TemplateResponse: Updated template
    """
    template_service = TemplateService(db)
    return await template_service.update_template(
        template_id, current_user, template_data
    )


@router.delete(
    "/{template_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete template",
    description="Delete template (Admin only)",
)
async def delete_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete template.

    Args:
        template_id: Template ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    template_service = TemplateService(db)
    await template_service.delete_template(template_id, current_user)
    return SuccessResponse(message="Template deleted successfully")


@router.get(
    "/categories",
    response_model=List[str],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get template categories",
    description="Get list of all template categories",
)
async def get_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[str]:
    """
    Get template categories.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[str]: List of categories
    """
    template_service = TemplateService(db)
    return await template_service.get_categories(current_user)


@router.post(
    "/{template_id}/apply",
    response_model=TemplateApplyResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Apply template",
    description="Apply template to a dashboard",
)
async def apply_template(
    template_id: UUID,
    apply_data: TemplateApplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TemplateApplyResponse:
    """
    Apply template to a dashboard.

    Args:
        template_id: Template ID
        apply_data: Template apply data
        current_user: Current authenticated user
        db: Database session

    Returns:
        TemplateApplyResponse: Created widgets
    """
    template_service = TemplateService(db)
    return await template_service.apply_template(template_id, current_user, apply_data)
