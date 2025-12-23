"""AI endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.ai import (
    AIHistoryItem,
    AIQueryRequest,
    AIQueryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    GenerateSQLRequest,
    GenerateSQLResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResponse,
)
from src.schemas.common import ErrorResponse, SuccessResponse
from src.services.ai_service import AIService

router = APIRouter()


@router.post(
    "/query",
    response_model=AIQueryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Process AI query",
    description="Process a natural language question and generate an answer",
)
async def process_query(
    query_data: AIQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIQueryResponse:
    """
    Process AI query endpoint.

    Args:
        query_data: Query data
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIQueryResponse: Query response
    """
    ai_service = AIService(db)
    return await ai_service.process_query(current_user.id, query_data)


@router.post(
    "/chat",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Send chat message",
    description="Send a chat message to AI and get response",
)
async def send_chat_message(
    message_data: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessageResponse:
    """
    Send chat message endpoint.

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
    summary="Get AI history",
    description="Get history of AI interactions",
)
async def get_history(
    filter_type: Optional[str] = Query(None, description="Filter: today, week, pinned"),
    search: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None, description="Category filter"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[AIHistoryItem]:
    """
    Get AI history endpoint.

    Args:
        filter_type: Filter type
        search: Search query
        category: Category filter
        skip: Number of records to skip
        limit: Maximum number of records
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[AIHistoryItem]: History items
    """
    ai_service = AIService(db)
    return await ai_service.get_history(
        current_user.id,
        filter_type=filter_type,
        search=search,
        category=category,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/history/{history_id}",
    response_model=AIHistoryItem,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get AI history item",
    description="Get specific AI history item by ID",
)
async def get_history_item(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AIHistoryItem:
    """
    Get AI history item endpoint.

    Args:
        history_id: History item ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        AIHistoryItem: History item
    """
    from src.repositories.base import BaseRepository
    from src.models.ai import AIHistory

    history_repo = BaseRepository(db, AIHistory)
    history_item = await history_repo.get_by_id(history_id)

    if not history_item or history_item.user_id != current_user.id:
        from src.core.exceptions import NotFoundError
        raise NotFoundError("History item not found")

    return AIHistoryItem.model_validate(history_item)


@router.delete(
    "/history/{history_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Delete AI history item",
    description="Delete AI history item",
)
async def delete_history_item(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete AI history item endpoint.

    Args:
        history_id: History item ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    from src.repositories.base import BaseRepository
    from src.models.ai import AIHistory

    history_repo = BaseRepository(db, AIHistory)
    history_item = await history_repo.get_by_id(history_id)

    if not history_item or history_item.user_id != current_user.id:
        from src.core.exceptions import NotFoundError
        raise NotFoundError("History item not found")

    await history_repo.delete(history_id)
    await db.commit()

    return SuccessResponse(message="History item deleted successfully")


@router.post(
    "/history/{history_id}/pin",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Pin AI history item",
    description="Pin an AI history item",
)
async def pin_history_item(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Pin history item endpoint.

    Args:
        history_id: History item ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    from src.repositories.base import BaseRepository
    from src.models.ai import AIHistory

    history_repo = BaseRepository(db, AIHistory)
    history_item = await history_repo.get_by_id(history_id)

    if not history_item or history_item.user_id != current_user.id:
        from src.core.exceptions import NotFoundError
        raise NotFoundError("History item not found")

    await history_repo.update(history_id, pinned=True)
    await db.commit()

    return SuccessResponse(message="History item pinned successfully")


@router.post(
    "/history/{history_id}/unpin",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Unpin AI history item",
    description="Unpin an AI history item",
)
async def unpin_history_item(
    history_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Unpin history item endpoint.

    Args:
        history_id: History item ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    from src.repositories.base import BaseRepository
    from src.models.ai import AIHistory

    history_repo = BaseRepository(db, AIHistory)
    history_item = await history_repo.get_by_id(history_id)

    if not history_item or history_item.user_id != current_user.id:
        from src.core.exceptions import NotFoundError
        raise NotFoundError("History item not found")

    await history_repo.update(history_id, pinned=False)
    await db.commit()

    return SuccessResponse(message="History item unpinned successfully")


@router.post(
    "/generate-sql",
    response_model=GenerateSQLResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Generate SQL",
    description="Generate SQL query from natural language question",
)
async def generate_sql(
    request: GenerateSQLRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GenerateSQLResponse:
    """
    Generate SQL endpoint.

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
    "/pipeline/execute",
    response_model=PipelineExecuteResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Execute AI pipeline",
    description="Execute complete AI pipeline",
)
async def execute_pipeline(
    request: PipelineExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PipelineExecuteResponse:
    """
    Execute pipeline endpoint.

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
    "/pipeline/{pipeline_id}",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get pipeline",
    description="Get pipeline by ID",
)
async def get_pipeline(
    pipeline_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PipelineResponse:
    """
    Get pipeline endpoint.

    Args:
        pipeline_id: Pipeline ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        PipelineResponse: Pipeline data
    """
    ai_service = AIService(db)
    return await ai_service.get_pipeline(pipeline_id)


@router.get(
    "/pipeline/{pipeline_id}/status",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get pipeline status",
    description="Get pipeline status",
)
async def get_pipeline_status(
    pipeline_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get pipeline status endpoint.

    Args:
        pipeline_id: Pipeline ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Pipeline status
    """
    ai_service = AIService(db)
    pipeline = await ai_service.get_pipeline(pipeline_id)
    return {"status": pipeline.status, "current_step": pipeline.current_step}

