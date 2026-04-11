import logging
import uuid
from typing import List, Optional, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.api.deps import get_current_user, get_db_session
from src.models.dashboard_build_job import DashboardBuildJob
from src.models.user import User
from src.repositories.base import BaseRepository
from src.repositories.page import PageRepository
from src.repositories.space import SpaceRepository
from src.schemas.ai import AIQueryRequest, ConfigureData
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import (
    DashboardCreate,
    DashboardDuplicateRequest,
    DashboardExportResponse,
    DashboardResponse,
    DashboardUpdate,
    WidgetCreate,
    WidgetResponse,
    WidgetUpdate,
)
from src.schemas.dashboard_ai import (
    DashboardAIBuildAsyncRequest,
    DashboardAIBuildAsyncResponse,
    DashboardAIBuildRequest,
    DashboardAIBuildResponse,
    DashboardAIBuildWidgetResult,
    DashboardAIPlanRequest,
    DashboardAIPlanResponse,
    DashboardAIPlanWidget,
    DashboardBuildJobStatusResponse,
)
from src.services.ai_service import AIService
from src.services.dashboard_service import DashboardService
from src.services.rbac_service import RBACService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_textual_layout() -> list[dict]:
    """Return the exact 6-widget layout derived from Image 2 (orange boxes)."""
    # G = 24px (grid unit)
    return [
        {"x": 72.0, "y": 72.0, "w": 456.0, "h": 96.0},  # w1: Header
        {"x": 120.0, "y": 192.0, "w": 576.0, "h": 168.0},  # w2: Summary
        {"x": 144.0, "y": 384.0, "w": 264.0, "h": 504.0},  # w3: Detail A
        {"x": 432.0, "y": 384.0, "w": 216.0, "h": 360.0},  # w4: Detail B
        {"x": 696.0, "y": 96.0, "w": 336.0, "h": 720.0},  # w5: Column 1
        {"x": 1056.0, "y": 96.0, "w": 336.0, "h": 720.0},  # w6: Column 2
    ]


@router.get(
    "",
    response_model=List[DashboardResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List dashboards",
    description="Get list of dashboards (optionally filtered by workspace)",
)
async def list_dashboards(
    page_id: Optional[UUID] = Query(None, description="Filter by page ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[DashboardResponse]:
    """
    List dashboards.

    Args:
        page_id: Optional page ID to filter
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[DashboardResponse]: List of dashboards
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "pages.view")
    dashboard_service = DashboardService(db)
    return await dashboard_service.list_dashboards(
        current_user, page_id=page_id, skip=skip, limit=limit
    )


@router.get(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get dashboard",
    description="Get dashboard by ID",
)
async def get_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Get dashboard by ID.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Dashboard data
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "pages.view")
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_dashboard(dashboard_id, current_user)


@router.post(
    "",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create dashboard",
    description="Create a new dashboard",
)
async def create_dashboard(
    dashboard_data: DashboardCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Create a new dashboard.

    Args:
        dashboard_data: Dashboard creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Created dashboard
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "pages.create")
    dashboard_service = DashboardService(db)
    return await dashboard_service.create_dashboard(current_user, dashboard_data)


@router.put(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update dashboard",
    description="Update dashboard information",
)
async def update_dashboard(
    dashboard_id: UUID,
    dashboard_data: DashboardUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Update dashboard.

    Args:
        dashboard_id: Dashboard ID
        dashboard_data: Dashboard update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Updated dashboard
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "pages.edit")
    dashboard_service = DashboardService(db)
    return await dashboard_service.update_dashboard(dashboard_id, current_user, dashboard_data)


@router.delete(
    "/{dashboard_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete dashboard",
    description="Delete dashboard (soft delete)",
)
async def delete_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "pages.delete")
    dashboard_service = DashboardService(db)
    await dashboard_service.delete_dashboard(dashboard_id, current_user)
    return SuccessResponse(message="Dashboard deleted successfully")


@router.get(
    "/{dashboard_id}/widgets",
    response_model=List[WidgetResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get dashboard widgets",
    description="Get all widgets in a dashboard",
)
async def get_dashboard_widgets(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WidgetResponse]:
    """
    Get all widgets in a dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[WidgetResponse]: List of widgets
    """
    dashboard_service = DashboardService(db)
    # Verify dashboard exists
    await dashboard_service.get_dashboard(dashboard_id, current_user)
    return await dashboard_service.get_dashboard_widgets(dashboard_id, current_user)


@router.post(
    "/{dashboard_id}/widgets",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create widget",
    description="Create a new widget in a dashboard",
)
async def create_widget(
    dashboard_id: UUID,
    widget_data: WidgetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Create a new widget in a dashboard.

    Args:
        dashboard_id: Dashboard ID
        widget_data: Widget creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Created widget
    """
    dashboard_service = DashboardService(db)
    # Ensure widget is created for the correct dashboard
    widget_data.dashboard_id = dashboard_id
    return await dashboard_service.create_widget(current_user, widget_data)


@router.put(
    "/{dashboard_id}/widgets/{widget_id}",
    response_model=WidgetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update widget",
    description="Update a widget in a dashboard",
)
async def update_widget(
    dashboard_id: UUID,
    widget_id: UUID,
    widget_data: WidgetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Update a widget in a dashboard.

    Args:
        dashboard_id: Dashboard ID
        widget_id: Widget ID
        widget_data: Widget update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Updated widget
    """
    dashboard_service = DashboardService(db)
    # Verify dashboard exists and user has access
    await dashboard_service.get_dashboard(dashboard_id, current_user)
    # Update widget
    return await dashboard_service.update_widget(widget_id, current_user, widget_data)


@router.delete(
    "/{dashboard_id}/widgets/{widget_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete widget",
    description="Delete a widget from a dashboard",
)
async def delete_widget(
    dashboard_id: UUID,
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete a widget from a dashboard.

    Args:
        dashboard_id: Dashboard ID
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    dashboard_service = DashboardService(db)
    # Verify dashboard exists and user has access
    await dashboard_service.get_dashboard(dashboard_id, current_user)
    # Delete widget
    await dashboard_service.delete_widget(widget_id, current_user)
    return SuccessResponse(message="Widget deleted successfully")


@router.get(
    "/{dashboard_id}/export",
    response_model=DashboardExportResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Export dashboard",
    description="Export dashboard with all widgets and connections",
)
async def export_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardExportResponse:
    """
    Export dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardExportResponse: Dashboard export data
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.export_dashboard(dashboard_id, current_user)


@router.post(
    "/ai/plan",
    response_model=DashboardAIPlanResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Generate dashboard plan (Davinci)",
    description="Generate a dashboard plan (no execution). Personal mode only.",
)
async def ai_plan_dashboard(
    body: DashboardAIPlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardAIPlanResponse:
    page_repo = PageRepository(db)
    active_page = await page_repo.get_active_page(current_user.id)
    if not active_page or getattr(active_page, "type", None) != "personal":
        raise HTTPException(
            status_code=400,
            detail="Dashboard AI planning is available in Personal mode only.",
        )

    # Resolve space context (required by AI engine)
    resolved_space_id = body.space_id
    if not resolved_space_id:
        space_repo = SpaceRepository(db)
        spaces = await space_repo.get_by_user(current_user.id, limit=1)
        if spaces:
            resolved_space_id = str(spaces[0].id)
    if not resolved_space_id:
        raise HTTPException(status_code=400, detail="No space context available for this user.")

    ai_service = AIService(db)
    connection_id = (
        body.connection_id
        or await ai_service._get_first_active_connection_for_space(  # noqa: SLF001
            current_user.id, resolved_space_id
        )
    )
    if not connection_id:
        raise HTTPException(status_code=400, detail="No active connection available for this user.")

    # Personal mode: include ALL crews the user belongs to (across spaces),
    # otherwise the AI engine will only see public (crew_id IS NULL) metadata.
    crew_ids = await ai_service._get_user_crew_ids(  # noqa: SLF001
        current_user.id, resolved_space_id, all_spaces=True
    )

    client = AIServiceHTTPClient()
    # Detect textual format early to cap max_widgets if needed
    # Force textual/infographic mode for AI-built dashboards as requested by USER
    max_widgets = min(int(body.max_widgets or 8), 6)

    # Build override schema summary from backend connection_metadata so Davinci can plan even if the AI Engine
    # can't access DB catalog directly.
    logical_tables_override = None
    schema_summary_override = None
    try:
        meta = await ai_service.metadata_repo.get_by_connection_id(
            UUID(connection_id)
        )  # noqa: SLF001
        tables = (meta.tables or []) if meta else []
        logical_tables: list[str] = []
        schema_lines: list[str] = []
        for t in tables[:12] if isinstance(tables, list) else []:
            if not isinstance(t, dict):
                continue
            schema = str(t.get("schema") or "").strip()
            name = str(t.get("name") or "").strip()
            if not name:
                continue
            logical = f"{schema}.{name}" if schema else name
            logical_tables.append(logical)
            cols = t.get("columns") or []
            col_names = []
            if isinstance(cols, list):
                for c in cols[:10]:
                    if isinstance(c, dict) and c.get("name"):
                        col_names.append(str(c["name"]))
            schema_lines.append(
                f"- {logical} cols: {', '.join(col_names)}" if col_names else f"- {logical}"
            )
        seen = set()
        logical_tables_override = [x for x in logical_tables if not (x in seen or seen.add(x))]
        schema_summary_override = "\n".join(schema_lines)
    except Exception:
        logical_tables_override = None
        schema_summary_override = None

    # Mandatory Permission Filtering: Get authorized tables
    permission_service = ai_service.permission_service
    try:
        authorized_tables = await permission_service.get_authorized_tables(
            user_id=current_user.id,
            connection_id=UUID(connection_id),
            space_id=UUID(resolved_space_id) if resolved_space_id else None,
            crew_ids=[UUID(cid) for cid in crew_ids] if crew_ids else None,
        )
    except Exception as e:
        logger.error(f"[ai_plan_dashboard] Error checking authorized tables: {e}", exc_info=True)
        authorized_tables = []  # Fail closed

    payload = await client.dashboard_plan(
        connection_id=connection_id,
        user_id=str(current_user.id),
        space_id=resolved_space_id,
        crew_ids=crew_ids if crew_ids else None,
        language=body.language,
        goal=body.goal,
        original_question=(body.original_question or body.goal),
        max_widgets=max_widgets,
        logical_tables_override=logical_tables_override,
        schema_summary_override=schema_summary_override,
        initial_ai_response=body.initial_ai_response,
        context_spaces=body.context_spaces,
        context_crews=body.context_crews,
        context_tables=body.context_tables,
        authorized_tables=list(authorized_tables),
    )

    # Validate / normalize into our schema
    widgets = [DashboardAIPlanWidget(**w) for w in (payload.get("widgets") or [])]
    return DashboardAIPlanResponse(
        dashboard_name=str(payload.get("dashboard_name") or body.goal),
        description=payload.get("description"),
        widgets=widgets,
        meta={
            **(payload.get("meta") or {}),
            "space_id": resolved_space_id,
            "connection_id": connection_id,
            "active_page_type": getattr(active_page, "type", None),
        },
    )


@router.post(
    "/ai/build",
    response_model=DashboardAIBuildResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Build dashboard from plan (Davinci)",
    description="Executes planned widget questions, creates dashboard + widgets. Personal mode only.",
)
async def ai_build_dashboard(
    body: DashboardAIBuildRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardAIBuildResponse:
    page_repo = PageRepository(db)
    active_page = await page_repo.get_active_page(current_user.id)
    if not active_page or getattr(active_page, "type", None) != "personal":
        raise HTTPException(
            status_code=400,
            detail="Dashboard AI build is available in Personal mode only.",
        )

    active_page_id = cast(UUID, active_page.id)

    # Resolve space context (required by AI engine)
    resolved_space_id = body.space_id
    if not resolved_space_id:
        space_repo = SpaceRepository(db)
        spaces = await space_repo.get_by_user(current_user.id, limit=1)
        if spaces:
            resolved_space_id = str(spaces[0].id)
    if not resolved_space_id:
        raise HTTPException(status_code=400, detail="No space context available for this user.")

    ai_service = AIService(db)
    connection_id = (
        body.connection_id
        or await ai_service._get_first_active_connection_for_space(  # noqa: SLF001
            current_user.id, resolved_space_id
        )
    )
    if not connection_id:
        raise HTTPException(status_code=400, detail="No active connection available for this user.")

    # Get plan (either provided or generated)
    # Force textual/infographic mode for AI-built dashboards as requested by USER
    is_textual = True
    max_widgets = min(int(body.max_widgets or 8), 6)

    plan = body.plan
    if not plan:
        # Reuse plan endpoint logic
        plan = await ai_plan_dashboard(
            DashboardAIPlanRequest(
                space_id=resolved_space_id,
                connection_id=connection_id,
                goal=body.goal,
                original_question=body.original_question,
                language=body.language,
                max_widgets=max_widgets,
                initial_ai_response=body.initial_ai_response,
                context_spaces=body.context_spaces,
                context_crews=body.context_crews,
                context_tables=body.context_tables,
            ),
            current_user=current_user,
            db=db,
        )

    # Create dashboard
    dashboard_service = DashboardService(db)
    dashboard = await dashboard_service.create_dashboard(
        current_user,
        DashboardCreate(
            name=plan.dashboard_name,
            description=plan.description,
            page_id=active_page_id,
        ),
    )

    # Execute widget questions and create widgets
    results: list[DashboardAIBuildWidgetResult] = []
    textual_layout = _get_textual_layout()

    # Layout parameters
    GRID_COLS = 12
    COL_W = 96
    GAP_X = 24
    STEP_X = COL_W + GAP_X
    BASE_X = 72
    BASE_Y = 72
    ROW_STEP = 360

    def _widget_grid_span(widget_type: str) -> int:
        # Always 4 widgets per row (12 cols / 3 col span)
        return 3

    def _widget_height(widget_type: str) -> float:
        if widget_type == "table":
            return float(360)  # 15 * GRID
        if widget_type == "kpi":
            return float(216)  # 9 * GRID
        if widget_type == "text":
            return float(216)  # 9 * GRID
        # chart (default)
        return float(312)  # 13 * GRID

    def _span_width_px(span_cols: int) -> float:
        # width = cols * COL_W + (cols-1) * GAP_X
        return float(span_cols * COL_W + max(0, span_cols - 1) * GAP_X)

    cursor_col = 0
    cursor_row = 0

    for idx, w in enumerate(plan.widgets[:max_widgets]):
        wtype = w.type or "chart"
        if is_textual:
            wtype = "insight"

        # Apply fixed textual layout if available and applicable
        if is_textual and idx < len(textual_layout):
            pos_info = textual_layout[idx]
            x, y = pos_info["x"], pos_info["y"]
            width, height = pos_info["w"], pos_info["h"]
        else:
            span = _widget_grid_span(wtype)
            if cursor_col + span > GRID_COLS:
                cursor_row += 1
                cursor_col = 0

            x = float(BASE_X + cursor_col * STEP_X)
            y = float(BASE_Y + cursor_row * ROW_STEP)
            width = _span_width_px(span)
            height = _widget_height(wtype)
            cursor_col += span

        # For text widgets, don't execute queries.
        if wtype == "text":
            content = None
            if isinstance(w.viz, dict):
                content = w.viz.get("content")
            widget_data = {"content": content or w.title}
            created = await dashboard_service.create_widget(
                current_user,
                WidgetCreate(
                    dashboard_id=dashboard.id,
                    type="text",
                    title=w.title,
                    position={"x": x, "y": y},
                    size={"width": width, "height": height},
                    data=widget_data,
                    config={"viz": w.viz or {}},
                    connection_id=UUID(connection_id),
                    query_id=None,
                ),
            )
            results.append(
                DashboardAIBuildWidgetResult(
                    widget_id=created.id,
                    query_id=None,
                    widget_key=w.widget_key,
                )
            )
            continue

        # Execute through existing AI pipeline; ensure 1 connection and chart-safe result sizes.
        query_req = AIQueryRequest(
            question=w.question,
            knowledge=[connection_id],
            space_id=resolved_space_id,
            configure_data=ConfigureData(
                question=w.question,
                knowledge=[connection_id],
                response_format="text",
                creativity=15,
                length=35,
                sql_instructions=(
                    "If you generate SQL for a chart, prefer aggregated results with <= 15 rows. "
                    "Always LIMIT the result set to 15 rows or fewer."
                ),
            ),
        )
        query_resp = await ai_service.process_query(cast(UUID, current_user.id), query_req)

        widget_data = {
            "question": w.question,
            "answer": query_resp.answer,
            "data": query_resp.data_sample or [],
            "sql": query_resp.sql,
            # Persist what the AI actually used so the UI can show it per-widget.
            "chosen_table": getattr(query_resp, "chosen_table", None),
            "chosen_datasets": getattr(query_resp, "chosen_datasets", None),
        }
        # Also persist a best-effort list of logical tables referenced in the widget question.
        # Davinci planner wraps logical tables in backticks (e.g., Using `invoices` JOIN `customers` ...).
        try:
            import re

            qtxt = str(w.question or "")
            # Only capture table names, not columns (e.g. ignore `customer_id` in "on `customer_id`").
            used_tables = [
                m.group(1).strip()
                for m in re.finditer(
                    r"(?:\\busing\\b|\\bjoin\\b)\\s+`([^`]+)`",
                    qtxt,
                    flags=re.IGNORECASE,
                )
                if m.group(1) and m.group(1).strip()
            ]
            # unique preserving order
            seen = set()
            used_tables_unique = []
            for t in used_tables:
                if t not in seen:
                    seen.add(t)
                    used_tables_unique.append(t)
            widget_data["used_tables"] = used_tables_unique
        except Exception:
            widget_data["used_tables"] = None
        widget_config = {"viz": w.viz or {}}

        # Populate specific structure for Insight cards
        if wtype == "insight":
            # Map query result to Insight data structure
            # Wide widgets get text_beside_chart, tall get text_above_chart
            layout_type = "text_beside_chart" if idx < 2 else "text_above_chart"

            # Simple heuristic for icon priority
            priority = "medium"
            answer_lower = (query_resp.answer or "").lower()
            if "critical" in answer_lower or "urgent" in answer_lower or "fail" in answer_lower:
                priority = "critical"
            elif (
                "high" in answer_lower
                or "important" in answer_lower
                or "significant" in answer_lower
            ):
                priority = "high"

            # Chart type fallback
            chart_type = cast(
                str, w.viz.get("type") if (w.viz and isinstance(w.viz, dict)) else "bar"
            )

            widget_data.update(
                {
                    "isInsight": True,
                    "insightTitle": w.title,
                    "layout_type": layout_type,
                    "section_id": f"insight-{idx}-{uuid.uuid4()}",
                    "content": {
                        "text_block": {
                            "title": "Analysis",
                            "body": query_resp.answer or "No insight generated.",
                            "priority": priority,
                        },
                        "chart_block": {
                            "chartType": chart_type,
                            "data": query_resp.data_sample or [],
                            "chartTitle": "Supporting Data",
                        },
                    },
                }
            )

        elif wtype == "chart" and isinstance(w.viz, dict) and w.viz.get("type"):
            # Backward-compatible path for current frontend ChartWidget
            widget_data["type"] = w.viz.get("type")
            if isinstance(w.viz.get("mapping"), dict):
                widget_data["mapping"] = w.viz.get("mapping")

        created = await dashboard_service.create_widget(
            current_user,
            WidgetCreate(
                dashboard_id=dashboard.id,
                type=wtype,
                title=w.title,
                position={"x": x, "y": y},
                size={"width": width, "height": height},
                data=widget_data,
                config=widget_config,
                connection_id=UUID(connection_id),
                query_id=query_resp.id,
            ),
        )
        results.append(
            DashboardAIBuildWidgetResult(
                widget_id=created.id,
                query_id=query_resp.id,
                widget_key=w.widget_key,
            )
        )

    return DashboardAIBuildResponse(
        dashboard_id=dashboard.id,
        widgets=results,
        meta={
            "space_id": resolved_space_id,
            "connection_id": connection_id,
            "active_page_type": getattr(active_page, "type", None),
        },
    )


@router.post(
    "/ai/build-async",
    response_model=DashboardAIBuildAsyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Build dashboard in background (Davinci)",
    description="Enqueues a background job (Celery) and returns immediately. Personal mode only.",
)
async def ai_build_dashboard_async(
    body: DashboardAIBuildAsyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardAIBuildAsyncResponse:
    page_repo = PageRepository(db)
    active_page = await page_repo.get_active_page(current_user.id)
    if not active_page or getattr(active_page, "type", None) != "personal":
        raise HTTPException(
            status_code=400,
            detail="Dashboard AI build is available in Personal mode only.",
        )

    user_id = cast(UUID, current_user.id)
    active_page_id = cast(UUID, active_page.id)

    # Resolve space context (required by AI engine)
    resolved_space_id = body.space_id
    if not resolved_space_id:
        space_repo = SpaceRepository(db)
        spaces = await space_repo.get_by_user(current_user.id, limit=1)
        if spaces:
            resolved_space_id = str(spaces[0].id)
    if not resolved_space_id:
        raise HTTPException(status_code=400, detail="No space context available for this user.")

    ai_service = AIService(db)
    connection_id = (
        body.connection_id
        or await ai_service._get_first_active_connection_for_space(  # noqa: SLF001
            user_id, resolved_space_id
        )
    )
    if not connection_id:
        raise HTTPException(status_code=400, detail="No active connection available for this user.")

    # Detect textual format early to cap max_widgets if needed
    # Force textual/infographic mode for AI-built dashboards as requested by USER
    max_widgets = min(int(body.max_widgets or 8), 6)

    job_repo = BaseRepository(db, DashboardBuildJob)
    context: dict | None = None
    if (
        body.initial_ai_response
        or (isinstance(body.context_spaces, list) and body.context_spaces)
        or (isinstance(body.context_crews, list) and body.context_crews)
        or (isinstance(body.context_tables, list) and body.context_tables)
    ):
        context = {
            "original_question": body.original_question or body.goal,
            "initial_ai_response": body.initial_ai_response,
            "context_spaces": body.context_spaces,
            "context_crews": body.context_crews,
            "context_tables": body.context_tables,
        }
    job = await job_repo.create(
        user_id=user_id,
        page_id=active_page_id,
        space_id=UUID(resolved_space_id),
        connection_id=UUID(connection_id),
        goal=body.original_question or body.goal,
        language=body.language,
        max_widgets=max_widgets,
        status="queued",
        total_widgets=max_widgets,
        completed_widgets=0,
        plan={"_context": context} if context else None,
    )
    await db.commit()
    await db.refresh(job)

    # Enqueue celery task
    from src.workers.ai_worker import build_dashboard_job

    # We don't need Celery result backend for this flow; avoid touching it (deploy passwords contain '/').
    build_dashboard_job.apply_async(args=[str(job.id)], ignore_result=True)

    return DashboardAIBuildAsyncResponse(
        job_id=cast(UUID, job.id),
        status=cast(str, job.status),
        total_widgets=int(job.total_widgets or 0),
        completed_widgets=int(job.completed_widgets or 0),
        dashboard_id=cast(Optional[UUID], job.dashboard_id),
        error=cast(Optional[str], job.error),
    )


@router.get(
    "/ai/build-jobs/{job_id}",
    response_model=DashboardBuildJobStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Get background dashboard build status",
)
async def get_dashboard_build_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardBuildJobStatusResponse:
    job_repo = BaseRepository(db, DashboardBuildJob)
    job = await job_repo.get_by_id(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Build job not found")

    created_ids = None
    try:
        if isinstance(job.created_widget_ids, list):
            created_ids = [UUID(str(x)) for x in job.created_widget_ids]
    except Exception:
        created_ids = None

    return DashboardBuildJobStatusResponse(
        job_id=cast(UUID, job.id),
        status=cast(str, job.status),
        total_widgets=int(job.total_widgets or 0),
        completed_widgets=int(job.completed_widgets or 0),
        dashboard_id=cast(Optional[UUID], job.dashboard_id),
        created_widget_ids=created_ids,
        error=cast(Optional[str], job.error),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


@router.post(
    "/{dashboard_id}/duplicate",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Duplicate dashboard",
    description="Create a duplicate of the dashboard with all widgets",
)
async def duplicate_dashboard(
    dashboard_id: UUID,
    duplicate_data: Optional[DashboardDuplicateRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Duplicate dashboard.

    Args:
        dashboard_id: Dashboard ID to duplicate
        duplicate_data: Optional duplicate configuration
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Duplicated dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.duplicate_dashboard(dashboard_id, current_user, duplicate_data)


@router.post(
    "/{dashboard_id}/lock",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Lock dashboard",
    description="Lock dashboard to prevent modifications",
)
async def lock_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Lock dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Locked dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.lock_dashboard(dashboard_id, current_user)


@router.post(
    "/{dashboard_id}/unlock",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Unlock dashboard",
    description="Unlock dashboard to allow modifications",
)
async def unlock_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Unlock dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Unlocked dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.unlock_dashboard(dashboard_id, current_user)
