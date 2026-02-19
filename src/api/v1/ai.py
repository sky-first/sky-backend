"""AI endpoints."""

import logging

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.api.deps import get_current_user, get_db_session
from src.config.settings import settings
from src.models.user import User
from src.rate_limit.core import (
    RateLimitExceeded,
    RedisFixedWindowRateLimiter,
    default_buckets_for_request,
    resolve_tenant_key,
)
from src.repositories.planet import PlanetRepository
from src.repositories.space import SpaceRepository
from src.schemas.ai import (
    AIHistoryItem,
    AIQueryRequest,
    AIQueryResponse,
    AnalyzeQuestionRequest,
    AnalyzeQuestionResponse,
    ChatBootstrapResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    CreateHistoryRequest,
    FeedbackRequest,
    GenerateAnswerRequest,
    GenerateAnswerResponse,
    GenerateInfographicRequest,
    GenerateInfographicResponse,
    GenerateSQLRequest,
    GenerateSQLResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResponse,
    SuggestWidgetTitleRequest,
    SuggestWidgetTitleResponse,
    ValidateSQLRequest,
    ValidateSQLResponse,
)
from src.schemas.common import ErrorResponse, SuccessResponse
from src.services.ai_service import AIService
from src.services.rbac_service import RBACService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/query",
    response_model=AIQueryResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Process AI query",
    description="Process a natural language question and return answer",
)
async def process_query(
    query_data: AIQueryRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIQueryResponse:
    """
    Process AI query.

    Args:
        query_data: Query data
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIQueryResponse: Query response
    """
    # RBAC enforcement: require ability to run queries in this context.
    rbac = RBACService(db)
    space_uuid: Optional[UUID] = None
    if query_data.space_id:
        try:
            space_uuid = UUID(query_data.space_id)
        except Exception:
            space_uuid = None
    await rbac.assert_permission(current_user, "data.query.run", space_id=space_uuid)

    ai_service = AIService(db)

    # Tenant/user rate limiting (cost control). Enforced only for the costly path.
    if settings.RATE_LIMIT_ENABLED and settings.AI_RATE_LIMIT_ENABLED:
        try:
            is_personal = bool(getattr(query_data, "is_personal", False))
            space_id = getattr(query_data, "space_id", None)
            crew_ids = await ai_service._get_user_crew_ids(  # noqa: SLF001
                current_user.id,
                space_id,
                all_spaces=is_personal,
            )
            tenant_key = resolve_tenant_key(
                user_id=str(current_user.id),
                crew_ids=crew_ids,
                space_id=space_id,
                is_personal=is_personal,
            )

            limiter = RedisFixedWindowRateLimiter(enabled=True, key_prefix="rl:v1")
            buckets = default_buckets_for_request(
                tenant_key=tenant_key,
                user_id=str(current_user.id),
                route_key="ai.query",
                user_per_min=settings.AI_RATE_LIMIT_USER_PER_MINUTE,
                user_per_hour=settings.AI_RATE_LIMIT_USER_PER_HOUR,
                tenant_per_min=settings.AI_RATE_LIMIT_TENANT_PER_MINUTE,
                tenant_per_hour=settings.AI_RATE_LIMIT_TENANT_PER_HOUR,
                global_user_per_hour=settings.AI_RATE_LIMIT_GLOBAL_USER_PER_HOUR,
                key_prefix="rl:v1",
            )
            await limiter.enforce(buckets)
        except RateLimitExceeded as e:
            res = e.result
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=res.to_payload(),
                headers=res.to_headers(),
            )
            # Preserve CORS behavior (same as middleware) so browser clients can read 429.
            origin = request.headers.get("Origin")
            if origin and origin in settings.cors_origins_list:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers.add_vary_header("Origin")
            return response  # type: ignore[return-value]

    return await ai_service.process_query(current_user.id, query_data)


@router.get(
    "/chat/bootstrap",
    response_model=ChatBootstrapResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get greeting + suggestions for a new chat",
    description="Used by the frontend to render suggestion cards when opening a new chat session (Personal mode only).",
)
async def chat_bootstrap(
    space_id: Optional[str] = Query(
        None,
        description="Space ID used as context for permissions/catalog. In Personal mode, currentSpace is usually set.",
    ),
    language: Optional[str] = Query(None, description="Optional language hint (e.g. en, pt, es)"),
    max_suggestions: int = Query(4, ge=1, le=8),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatBootstrapResponse:
    """
    Returns greeting + suggestion cards for a new chat session.

    Current behavior:
    - Only enabled when the active planet is in Personal mode (planet.type == 'personal').
    - Uses the first active DataConnection for the user (Option A).
    """
    try:
        # 1) Mode hint (Personal mode is a client-side toggle today).
        # We don't hard-block here because the frontend is the source of truth for the
        # current "work mode" and we still need to return suggestions even if the
        # active planet in DB isn't synced yet.
        planet_repo = PlanetRepository(db)
        active_planet = await planet_repo.get_active_planet(current_user.id)
        is_personal = getattr(active_planet, "type", None) == "personal"

        # 2) Ensure we have a space_id (fallback: first space owned by user)
        resolved_space_id = space_id
        if not resolved_space_id:
            space_repo = SpaceRepository(db)
            spaces = await space_repo.get_by_user(current_user.id, limit=1)
            if spaces:
                resolved_space_id = str(spaces[0].id)

        if not resolved_space_id:
            return ChatBootstrapResponse(
                greeting="Connect a data source to get started.",
                suggestions=[
                    {
                        "title": "Create dashboard",
                        "kind": "action",
                        "action_id": "create_dashboard",
                    },
                    {
                        "title": "Connect data",
                        "kind": "question",
                        "question": "How do I connect a new data source?",
                    },
                    {
                        "title": "Refresh catalog",
                        "kind": "question",
                        "question": "How do I refresh my data catalog?",
                    },
                    {
                        "title": "What can you do?",
                        "kind": "question",
                        "question": "What can you help me with?",
                    },
                ],
                meta={
                    "enabled": True,
                    "reason": "NO_SPACE_CONTEXT",
                    "active_planet_type": getattr(active_planet, "type", None),
                },
            )

        # 3) Choose connection (Option A: first active)
        ai_service = AIService(db)
        connection_id = await ai_service._get_first_active_connection_for_space(  # noqa: SLF001
            current_user.id,
            resolved_space_id,
        )
        if not connection_id:
            return ChatBootstrapResponse(
                greeting="I can help once you connect a data source.",
                suggestions=[
                    {
                        "title": "Create dashboard",
                        "kind": "action",
                        "action_id": "create_dashboard",
                    },
                    {
                        "title": "Connect data",
                        "kind": "question",
                        "question": "How do I connect a new data source?",
                    },
                    {
                        "title": "Catalog",
                        "kind": "question",
                        "question": "Where do I see my available tables?",
                    },
                    {
                        "title": "Refresh",
                        "kind": "question",
                        "question": "How do I refresh my catalog after changes?",
                    },
                ],
                meta={
                    "enabled": True,
                    "space_id": resolved_space_id,
                    "reason": "NO_ACTIVE_CONNECTION",
                    "active_planet_type": getattr(active_planet, "type", None),
                },
            )

        # 4) Resolve crew_ids for this user in this space (Personal => all crews user belongs to)
        crew_ids = await ai_service._get_user_crew_ids(
            current_user.id, resolved_space_id
        )  # noqa: SLF001

        # 5) Call AI Engine
        client = AIServiceHTTPClient()
        payload = await client.chat_bootstrap(
            connection_id=connection_id,
            user_id=str(current_user.id),
            space_id=resolved_space_id,
            crew_ids=crew_ids if crew_ids else None,
            language=language,
            max_suggestions=max_suggestions,
            is_personal=is_personal,
        )

        # 6) Return as schema
        out = ChatBootstrapResponse.model_validate(payload)
        out.meta = {
            **(out.meta or {}),
            "active_planet_type": getattr(active_planet, "type", None),
        }
        return out
    except Exception as e:
        return ChatBootstrapResponse(
            greeting="How can I help you with your data?",
            suggestions=[
                {"title": "Create dashboard", "kind": "action", "action_id": "create_dashboard"},
                {
                    "title": "Available data",
                    "kind": "question",
                    "question": "What data do I have access to?",
                },
                {
                    "title": "Tables",
                    "kind": "question",
                    "question": "Which tables are available in my catalog?",
                },
                {
                    "title": "Examples",
                    "kind": "question",
                    "question": "Give me examples of questions I can ask about my data.",
                },
            ][:max_suggestions],
            meta={
                "enabled": True,
                "reason": "CHAT_BOOTSTRAP_ERROR",
                "error": str(e)[:500],
            },
        )


@router.post(
    "/chat",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Send chat message",
    description="Send a chat message in a widget",
)
async def send_chat_message(
    message_data: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessageResponse:
    """
    Send chat message.

    Args:
        message_data: Message data
        current_user: Current authenticated user
        db: Database session

    Returns:
        ChatMessageResponse: Chat response
    """
    ai_service = AIService(db)
    return await ai_service.send_chat_message(current_user.id, message_data)


@router.get(
    "/history",
    response_model=List[AIHistoryItem],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get AI history",
    description="Get history of AI interactions",
)
async def get_history(
    filter: Optional[str] = Query(None, description="Filter: today, week, pinned"),
    search: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None, description="Category filter"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[AIHistoryItem]:
    """
    Get AI history.

    Args:
        filter: Filter type (today, week, pinned)
        search: Search query
        category: Category filter
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[AIHistoryItem]: History items
    """
    ai_service = AIService(db)
    return await ai_service.get_history(
        current_user.id,
        filter_type=filter,
        search=search,
        category=category,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/history",
    response_model=AIHistoryItem,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create AI history entry",
    description="Create a new AI history entry",
)
async def create_history(
    history_data: CreateHistoryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIHistoryItem:
    """
    Create AI history entry.

    Args:
        history_data: History data (query, answer, category, tags)
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIHistoryItem: Created history item
    """
    ai_service = AIService(db)
    return await ai_service.create_history(current_user.id, history_data)


@router.get(
    "/history/{history_id}",
    response_model=AIHistoryItem,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get history item",
    description="Get a specific history item by ID",
)
async def get_history_by_id(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIHistoryItem:
    """
    Get history item by ID.

    Args:
        history_id: History ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIHistoryItem: History item
    """
    ai_service = AIService(db)
    return await ai_service.get_history_by_id(history_id, current_user.id)


@router.delete(
    "/history/{history_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete history item",
    description="Delete a history item",
)
async def delete_history(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete history item.

    Args:
        history_id: History ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    ai_service = AIService(db)
    await ai_service.delete_history(history_id, current_user.id)
    return SuccessResponse(message="History item deleted successfully")


@router.post(
    "/history/{history_id}/pin",
    response_model=AIHistoryItem,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Pin history item",
    description="Pin a history item",
)
async def pin_history(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIHistoryItem:
    """
    Pin history item.

    Args:
        history_id: History ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIHistoryItem: Updated history item
    """
    ai_service = AIService(db)
    return await ai_service.pin_history(history_id, current_user.id)


@router.post(
    "/history/{history_id}/unpin",
    response_model=AIHistoryItem,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Unpin history item",
    description="Unpin a history item",
)
async def unpin_history(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIHistoryItem:
    """
    Unpin history item.

    Args:
        history_id: History ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIHistoryItem: Updated history item
    """
    ai_service = AIService(db)
    return await ai_service.unpin_history(history_id, current_user.id)


@router.get(
    "/history/export",
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Export history",
    description="Export history as CSV",
)
async def export_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """
    Export history as CSV.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        StreamingResponse: CSV file
    """
    ai_service = AIService(db)
    csv_content = await ai_service.export_history(current_user.id)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ai_history.csv"},
    )


@router.post(
    "/pipeline/execute",
    response_model=PipelineExecuteResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Execute pipeline",
    description="Execute an AI pipeline",
)
async def execute_pipeline(
    request: PipelineExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PipelineExecuteResponse:
    """
    Execute pipeline.

    Args:
        request: Pipeline execute request
        current_user: Current authenticated user
        db: Database session

    Returns:
        PipelineExecuteResponse: Pipeline response
    """
    ai_service = AIService(db)
    return await ai_service.execute_pipeline(current_user.id, request)


@router.get(
    "/pipeline/{pipeline_id}/status",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get pipeline status",
    description="Get pipeline status and steps",
)
async def get_pipeline_status(
    pipeline_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PipelineResponse:
    """
    Get pipeline status.

    Args:
        pipeline_id: Pipeline ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        PipelineResponse: Pipeline status
    """
    ai_service = AIService(db)
    pipeline = await ai_service.get_pipeline(pipeline_id)

    # Verify ownership
    from src.models.ai import AIQuery
    from src.repositories.base import BaseRepository

    query_repo = BaseRepository(db, AIQuery)
    query = await query_repo.get_by_id(pipeline.query_id)
    if not query or query.user_id != current_user.id:
        from src.core.exceptions import ForbiddenError

        raise ForbiddenError("Access denied to this pipeline")

    return pipeline


@router.get(
    "/pipeline/{pipeline_id}/logs",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get pipeline logs",
    description="Get pipeline execution logs",
)
async def get_pipeline_logs(
    pipeline_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get pipeline logs.

    Args:
        pipeline_id: Pipeline ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Pipeline logs
    """
    ai_service = AIService(db)
    logs = await ai_service.get_pipeline_logs(pipeline_id, current_user.id)
    return {"logs": logs}


@router.post(
    "/generate-sql",
    response_model=GenerateSQLResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Generate SQL",
    description="Generate SQL query from natural language",
)
async def generate_sql(
    request: GenerateSQLRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GenerateSQLResponse:
    """
    Generate SQL from natural language.

    Args:
        request: Generate SQL request
        current_user: Current authenticated user
        db: Database session

    Returns:
        GenerateSQLResponse: Generated SQL
    """
    ai_service = AIService(db)
    return await ai_service.generate_sql(request)


@router.post(
    "/generate-answer",
    response_model=GenerateAnswerResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Generate answer",
    description="Generate answer from question",
)
async def generate_answer(
    request: GenerateAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GenerateAnswerResponse:
    """
    Generate answer from question.

    Args:
        request: Generate answer request
        current_user: Current authenticated user
        db: Database session

    Returns:
        GenerateAnswerResponse: Generated answer
    """
    from datetime import datetime, timezone

    ai_service = AIService(db)
    answer = await ai_service.generate_answer(request.question, request.knowledge, request.context)
    return GenerateAnswerResponse(answer=answer, timestamp=datetime.now(timezone.utc))


@router.post(
    "/generate-infographic",
    response_model=GenerateInfographicResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Generate infographic data",
    description="Generate structured JSON data for an infographic widget from a question and AI answer.",
)
async def generate_infographic(
    request: GenerateInfographicRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GenerateInfographicResponse:
    """
    Generate structured infographic data.

    Uses the real AI service when AI_SERVICE_TYPE=real, otherwise falls back to mock.

    Args:
        request: question, answer, optional data_sample, language, style
        current_user: Current authenticated user
        db: Database session

    Returns:
        GenerateInfographicResponse: Structured infographic data
    """
    from datetime import datetime, timezone

    ai_service = AIService(db)
    logger.info(f"Generating infographic for user {current_user.id}, question: {str(request.question)[:50]}...")
    
    try:
        raw = await ai_service.generate_infographic(current_user.id, request)
        logger.info(f"AI service returned raw data type: {type(raw)}")
        
        # The AI service returns a plain dict; validate it into the typed schema.
        from src.schemas.ai import InfographicData

        if isinstance(raw, dict):
            try:
                infographic_data = InfographicData.model_validate(raw)
                logger.info("Successfully validated infographic data")
            except Exception as val_err:
                logger.error(f"Validation error for infographic data: {val_err}")
                logger.debug(f"Raw data that failed validation: {raw}")
                # Fallback to empty but with title
                infographic_data = InfographicData()
        else:
            logger.warning(f"AI service returned non-dict: {type(raw)}")
            infographic_data = InfographicData()

        # ✅ ENSURE DATA FOR UI: If the AI failed to provide a title or summary, 
        # we provide minimal fallbacks to avoid the "Grey Box" empty state in the frontend.
        if not infographic_data.title:
            infographic_data.title = "Analysis Result"
        if not infographic_data.summary and not infographic_data.mainValue:
            infographic_data.summary = "Strategic analysis based on the provided query context."

        return GenerateInfographicResponse(
            data=infographic_data,
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.exception(f"Unexpected error in generating infographic: {e}")
        # Return a safe response instead of 500
        from src.schemas.ai import InfographicData
        return GenerateInfographicResponse(
            data=InfographicData(
                title="Analysis Error",
                summary=f"Error: {str(e)}. Please check backend logs."
            ),
            timestamp=datetime.now(timezone.utc),
        )


@router.post(
    "/analyze-question",
    response_model=AnalyzeQuestionResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Analyze question",
    description="Analyze a question to extract intent and entities",
)
async def analyze_question(
    request: AnalyzeQuestionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AnalyzeQuestionResponse:
    """
    Analyze question.

    Args:
        request: Analyze question request
        current_user: Current authenticated user
        db: Database session

    Returns:
        AnalyzeQuestionResponse: Analysis result
    """
    ai_service = AIService(db)
    analysis = await ai_service.analyze_question(request.question, request.knowledge)
    return AnalyzeQuestionResponse(**analysis)


@router.post(
    "/feedback",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Submit feedback",
    description="Submit feedback for an AI response",
)
async def submit_feedback(
    feedback_data: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Submit feedback.

    Args:
        feedback_data: Feedback data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    ai_service = AIService(db)
    await ai_service.submit_feedback(current_user.id, feedback_data)
    return SuccessResponse(message="Feedback submitted successfully")


@router.post(
    "/validate-sql",
    response_model=ValidateSQLResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Validate SQL",
    description="Validate SQL by executing a test query (LIMIT 5)",
)
async def validate_sql(
    request: ValidateSQLRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ValidateSQLResponse:
    """
    Validate SQL by calling AI Engine.

    Args:
        request: Validate SQL request
        current_user: Current authenticated user
        db: Database session

    Returns:
        ValidateSQLResponse: Validation result
    """
    ai_service = AIService(db)
    return await ai_service.validate_sql(request, current_user)


@router.post(
    "/suggest-title",
    response_model=SuggestWidgetTitleResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
    summary="Suggest widget title",
    description="Suggest a better title for a single widget created from an AI answer.",
)
async def suggest_widget_title(
    body: SuggestWidgetTitleRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuggestWidgetTitleResponse:
    # RBAC enforcement: same capability as querying (this still incurs AI cost).
    rbac = RBACService(db)
    space_uuid: Optional[UUID] = None
    if body.space_id:
        try:
            space_uuid = UUID(body.space_id)
        except Exception:
            space_uuid = None
    await rbac.assert_permission(current_user, "data.query.run", space_id=space_uuid)

    ai_service = AIService(db)

    # Rate limiting: count title suggestions as AI calls (cost control).
    if settings.RATE_LIMIT_ENABLED and settings.AI_RATE_LIMIT_ENABLED:
        try:
            is_personal = bool(getattr(body, "is_personal", False))
            space_id = getattr(body, "space_id", None)
            crew_ids = await ai_service._get_user_crew_ids(  # noqa: SLF001
                current_user.id,
                space_id,
                all_spaces=is_personal,
            )
            tenant_key = resolve_tenant_key(
                user_id=str(current_user.id),
                crew_ids=crew_ids,
                space_id=space_id,
                is_personal=is_personal,
            )
            limiter = RedisFixedWindowRateLimiter(enabled=True, key_prefix="rl:v1")
            buckets = default_buckets_for_request(
                tenant_key=tenant_key,
                user_id=str(current_user.id),
                route_key="ai.suggest_title",
                user_per_min=settings.AI_RATE_LIMIT_USER_PER_MINUTE,
                user_per_hour=settings.AI_RATE_LIMIT_USER_PER_HOUR,
                tenant_per_min=settings.AI_RATE_LIMIT_TENANT_PER_MINUTE,
                tenant_per_hour=settings.AI_RATE_LIMIT_TENANT_PER_HOUR,
                global_user_per_hour=settings.AI_RATE_LIMIT_GLOBAL_USER_PER_HOUR,
                key_prefix="rl:v1",
            )
            await limiter.enforce(buckets)
        except RateLimitExceeded as e:
            res = e.result
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=res.to_payload(),
                headers=res.to_headers(),
            )
            origin = request.headers.get("Origin")
            if origin and origin in settings.cors_origins_list:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers.add_vary_header("Origin")
            return response  # type: ignore[return-value]

    client = AIServiceHTTPClient()
    suggested = await client.suggest_widget_title(
        question=body.question,
        data_sample=body.data_sample,
        answer=body.answer,
        current_title=body.current_title,
        language=body.language or "pt",
    )
    return SuggestWidgetTitleResponse(title=suggested)


import logging as _logging  # noqa: E402

_logger = _logging.getLogger(__name__)


@router.post(
    "/generate-infographic",
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Generate infographic data",
    description="Generate structured infographic data from a question and AI answer.",
)
async def generate_infographic(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Generate infographic data using the AI service.

    Falls back to mock data if the real AI service is unavailable.
    """
    _logger.info(
        "generate_infographic called by user=%s question_len=%d",
        current_user.id,
        len(str(body.get("question", ""))),
    )
    _logger.debug("generate_infographic payload: %s", body)

    ai_service = AIService(db)
    try:
        from src.schemas.ai import GenerateInfographicRequest
        request = GenerateInfographicRequest(
            question=body.get("question", ""),
            answer=body.get("answer", ""),
            data_sample=body.get("data_sample"),
            language=body.get("language", "en"),
            style=body.get("style") or "mix",
        )
        result = await ai_service.generate_infographic(
            current_user.id, request
        )
        _logger.info("generate_infographic succeeded for user=%s", current_user.id)
        return result
    except Exception as exc:
        _logger.error(
            "generate_infographic failed for user=%s: %s",
            current_user.id,
            exc,
            exc_info=True,
        )
        raise
