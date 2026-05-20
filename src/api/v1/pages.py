"""Page endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.page import (
    PageCreate,
    PageMemberCreate,
    PageMemberResponse,
    PageMemberRoleUpdate,
    PageResponse,
    PageUpdate,
)
from src.schemas.widget import (
    PageExportResponse,
    WidgetCreate,
    WidgetResponse,
)
from src.services.widget_service import WidgetService
from src.services.page_service import PageService
from src.services.rbac_service import RBACService
from src.services.starred_service import StarredItemService

router = APIRouter()


@router.get(
    "",
    response_model=List[PageResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List pages",
    description="Get list of pages for the current user",
)
async def list_pages(
    type: Optional[str] = Query(None, pattern="^(personal|team)$"),
    search: Optional[str] = Query(None),
    context: Optional[str] = Query(
        None,
        pattern="^(personal|space|crew|all)$",
        description="Navigation context: personal, space, crew, or all",
    ),
    space_id: Optional[UUID] = Query(None, description="Required when context=space"),
    crew_id: Optional[UUID] = Query(None, description="Required when context=crew"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PageResponse]:
    """
    List pages filtered by navigation context.

    Contexts:
        personal — only personal pages (owner=me, no crew, no space)
        space — space-level pages (all space members see, not crew-specific)
        crew — crew-level pages (only crew members see)
        all — everything the user can access (default)
    """
    await RBACService(db).assert_permission(current_user, "pages.view")
    page_service = PageService(db)
    pages = await page_service.get_user_pages(
        current_user,
        context=context or "all",
        space_id=space_id,
        crew_id=crew_id,
    )

    # Apply additional filters
    if type:
        pages = [w for w in pages if w.type == type]
    if search:
        search_lower = search.lower()
        pages = [w for w in pages if search_lower in w.name.lower()]

    return pages


@router.get(
    "/{page_id}",
    response_model=PageResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get page",
    description="Get page by ID",
)
async def get_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    """
    Get page by ID.

    Args:
        page_id: Page ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        PageResponse: Page data
    """
    await RBACService(db).assert_permission(current_user, "pages.view")
    page_service = PageService(db)
    return await page_service.get_page(page_id, current_user)


@router.post(
    "",
    response_model=PageResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create page",
    description="Create a new page",
)
async def create_page(
    page_data: PageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    """
    Create a new page.

    Args:
        page_data: Page creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PageResponse: Created page
    """
    await RBACService(db).assert_permission(current_user, "pages.create")
    page_service = PageService(db)
    return await page_service.create_page(current_user, page_data)


@router.put(
    "/{page_id}",
    response_model=PageResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update page",
    description="Update page information",
)
async def update_page(
    page_id: UUID,
    page_data: PageUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    """
    Update page.

    Args:
        page_id: Page ID
        page_data: Page update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PageResponse: Updated page
    """
    await RBACService(db).assert_permission(current_user, "pages.edit")
    page_service = PageService(db)
    return await page_service.update_page(page_id, current_user, page_data)


@router.post(
    "/{page_id}/duplicate",
    response_model=PageResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Duplicate page",
    description=(
        "Create a copy of the page with all its dashboards and widgets "
        "(infographics included). The copy gets fresh UUIDs everywhere and "
        "its name is suffixed with ' (Copy)'."
    ),
)
async def duplicate_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    await RBACService(db).assert_permission(current_user, "pages.create")
    page_service = PageService(db)
    return await page_service.duplicate_page(page_id, current_user)


@router.delete(
    "/{page_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete page",
    description="Delete page (soft delete, owner only)",
)
async def delete_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete page.

    Args:
        page_id: Page ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    await RBACService(db).assert_permission(current_user, "pages.delete")
    page_service = PageService(db)
    await page_service.delete_page(page_id, current_user)
    return SuccessResponse(message="Page deleted successfully")


@router.get(
    "/{page_id}/members",
    response_model=List[PageMemberResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get page members",
    description="Get all members of a page",
)
async def get_page_members(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PageMemberResponse]:
    """
    Get all members of a page.

    Args:
        page_id: Page ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[PageMemberResponse]: List of page members
    """
    await RBACService(db).assert_permission(current_user, "pages.view")
    page_service = PageService(db)
    return await page_service.get_page_members(page_id, current_user)


@router.post(
    "/{page_id}/members",
    response_model=PageMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Add page member",
    description="Add a member to the page",
)
async def add_page_member(
    page_id: UUID,
    member_data: PageMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageMemberResponse:
    """
    Add a member to the page.

    Args:
        page_id: Page ID
        member_data: Member creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PageMemberResponse: Created member
    """
    page_service = PageService(db)
    return await page_service.add_member(page_id, current_user, member_data)


@router.delete(
    "/{page_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Remove page member",
    description="Remove a member from the page",
)
async def remove_page_member(
    page_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Remove a member from the page.

    Args:
        page_id: Page ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    page_service = PageService(db)
    await page_service.remove_member(page_id, user_id, current_user)
    return SuccessResponse(message="Member removed successfully")


@router.put(
    "/{page_id}/members/{user_id}/role",
    response_model=PageMemberResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update page member role",
    description="Update the role of a page member",
)
async def update_page_member_role(
    page_id: UUID,
    user_id: UUID,
    role_data: PageMemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageMemberResponse:
    """
    Update the role of a page member.

    Args:
        page_id: Page ID
        user_id: User ID to update
        role_data: Role update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PageMemberResponse: Updated member
    """
    page_service = PageService(db)
    return await page_service.update_member_role(page_id, user_id, role_data.role, current_user)


@router.get(
    "/{page_id}/widgets",
    response_model=List[WidgetResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get page widgets",
    description="Get all widgets in a page (replaces the legacy "
    "/dashboards/{id}/widgets endpoint).",
)
async def get_page_widgets(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get all widgets on a page."""
    await RBACService(db).assert_permission(current_user, "pages.view")
    page_service = PageService(db)
    await page_service.get_page(page_id, current_user)

    widget_service = WidgetService(db)
    return await widget_service.get_page_widgets(page_id, current_user)


@router.post(
    "/{page_id}/widgets",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create widget on page",
    description="Create a widget on this page (replaces the legacy "
    "/dashboards/{id}/widgets POST endpoint).",
)
async def create_page_widget(
    page_id: UUID,
    widget_data: WidgetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a widget on the given page."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    # Force path param to win over body
    widget_data.page_id = page_id
    widget_service = WidgetService(db)
    return await widget_service.create_widget(current_user, widget_data)


@router.post(
    "/{page_id}/lock",
    response_model=PageResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Lock page",
    description="Lock page so widgets can't be moved/resized.",
)
async def lock_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    """Lock the page (replaces /dashboards/{id}/lock)."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    page_service = PageService(db)
    return await page_service.update_page(
        page_id, current_user, PageUpdate(is_locked=True)
    )


@router.post(
    "/{page_id}/unlock",
    response_model=PageResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Unlock page",
    description="Unlock page so widgets can be moved/resized.",
)
async def unlock_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    """Unlock the page (replaces /dashboards/{id}/unlock)."""
    await RBACService(db).assert_permission(current_user, "pages.edit")
    page_service = PageService(db)
    return await page_service.update_page(
        page_id, current_user, PageUpdate(is_locked=False)
    )


@router.post(
    "/{page_id}/export",
    response_model=PageExportResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Export page",
    description="Export page with all widgets + connections.",
)
async def export_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Export page (replaces /dashboards/{id}/export)."""
    await RBACService(db).assert_permission(current_user, "pages.view")
    widget_service = WidgetService(db)
    return await widget_service.export_page(page_id, current_user)


@router.post(
    "/{page_id}/switch",
    response_model=PageResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Switch active page",
    description="Switch the active page for the current user",
)
async def switch_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PageResponse:
    """
    Switch the active page for the current user.

    Args:
        page_id: Page ID to switch to
        current_user: Current authenticated user
        db: Database session

    Returns:
        PageResponse: Active page
    """
    page_service = PageService(db)
    return await page_service.switch_page(page_id, current_user)


@router.post(
    "/{page_id}/star",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Star page",
    description="Star a page for the current user",
)
async def star_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Star a page for the current user.

    Args:
        page_id: Page ID to star
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    # Verify page exists and user has access
    page_service = PageService(db)
    await page_service.get_page(page_id, current_user)

    # Star the page
    starred_service = StarredItemService(db)
    await starred_service.star_item(current_user, page_id, "page")

    return SuccessResponse(message="Page starred successfully")


@router.delete(
    "/{page_id}/star",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Unstar page",
    description="Unstar a page for the current user",
)
async def unstar_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Unstar a page for the current user.

    Args:
        page_id: Page ID to unstar
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    # Unstar the page (idempotent - won't error if not starred)
    starred_service = StarredItemService(db)
    await starred_service.unstar_item(current_user, page_id, "page")

    return SuccessResponse(message="Page unstarred successfully")
