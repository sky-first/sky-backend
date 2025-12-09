"""AI endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.ai import (
    AIHistoryItem,
    AIQueryRequest,
    AIQueryResponse,
    AnalyzeQuestionRequest,
    AnalyzeQuestionResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    GenerateAnswerRequest,
    GenerateAnswerResponse,
    GenerateSQLRequest,
    GenerateSQLResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResponse,
)
from src.schemas.common import ErrorResponse, PaginatedResponse, SuccessResponse
from src.services.ai_service import AIService

router = APIRouter()


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
    ai_service = AIService(db)
    return await ai_service.process_query(current_user.id, query_data)


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
    from src.repositories.base import BaseRepository
    from src.models.ai import AIQuery
    
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
    answer = await ai_service.generate_answer(
        request.question, request.knowledge, request.context
    )
    return GenerateAnswerResponse(answer=answer, timestamp=datetime.now(timezone.utc))


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

