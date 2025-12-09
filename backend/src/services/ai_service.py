"""AI service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.mock import MockAIService
from src.core.exceptions import NotFoundError
from src.models.ai import AIHistory, AIQuery, Pipeline
from src.repositories.base import BaseRepository
from src.schemas.ai import (
    AIHistoryItem,
    AIQueryRequest,
    AIQueryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ConfigureData,
    GenerateSQLRequest,
    GenerateSQLResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResponse,
)


class AIService:
    """AI service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize AI service.

        Args:
            db: Database session
        """
        self.db = db
        self.mock_ai = MockAIService()
        self.query_repo = BaseRepository(db, AIQuery)
        self.history_repo = BaseRepository(db, AIHistory)
        self.pipeline_repo = BaseRepository(db, Pipeline)

    async def process_query(
        self, user_id: UUID, query_data: AIQueryRequest
    ) -> AIQueryResponse:
        """
        Process AI query.

        Args:
            user_id: User ID
            query_data: Query data

        Returns:
            AIQueryResponse: Query response
        """
        # Create query record
        configure_data = query_data.configure_data or ConfigureData(
            question=query_data.question, knowledge=query_data.knowledge or []
        )

        query = await self.query_repo.create(
            user_id=user_id,
            widget_id=query_data.widget_id,
            question=query_data.question,
            configure_data=configure_data.model_dump(),
            status="processing",
        )

        await self.db.commit()
        await self.db.refresh(query)

        # Process query asynchronously (in real implementation, use Celery)
        # For now, process synchronously with mock
        try:
            result = await self.mock_ai.process_pipeline(
                str(query.id), configure_data.model_dump()
            )

            # Update query with answer
            query.answer = result.get("steps", [])[-1].get("content", "") if result.get("steps") else "Answer generated"
            query.status = "completed"
        except Exception as e:
            query.status = "error"
            query.answer = f"Error: {str(e)}"

        await self.db.commit()
        await self.db.refresh(query)

        return AIQueryResponse.model_validate(query)

    async def send_chat_message(
        self, user_id: UUID, message_data: ChatMessageRequest
    ) -> ChatMessageResponse:
        """
        Send chat message.

        Args:
            user_id: User ID
            message_data: Message data

        Returns:
            ChatMessageResponse: Chat response
        """
        from src.models.ai import ChatMessage

        # Save user message
        user_message = await BaseRepository(self.db, ChatMessage).create(
            widget_id=message_data.widget_id,
            type="user",
            content=message_data.message,
        )

        # Generate AI response
        answer = await self.mock_ai.generate_answer(
            message_data.message, [], message_data.context or {}
        )

        # Save AI response
        ai_message = await BaseRepository(self.db, ChatMessage).create(
            widget_id=message_data.widget_id,
            type="assistant",
            content=answer,
        )

        await self.db.commit()
        await self.db.refresh(ai_message)

        return ChatMessageResponse.model_validate(ai_message)

    async def get_history(
        self,
        user_id: UUID,
        filter_type: Optional[str] = None,
        search: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[AIHistoryItem]:
        """
        Get AI history.

        Args:
            user_id: User ID
            filter_type: Filter type (today, week, pinned)
            search: Search query
            category: Category filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[AIHistoryItem]: History items
        """
        filters = {"user_id": user_id}

        if filter_type == "pinned":
            filters["pinned"] = True

        if category:
            filters["category"] = category

        history_items = await self.history_repo.get_all(
            skip=skip, limit=limit, filters=filters
        )

        # Apply search filter if provided
        if search:
            history_items = [
                item
                for item in history_items
                if search.lower() in item.query.lower() or search.lower() in item.preview.lower()
            ]

        return [AIHistoryItem.model_validate(item) for item in history_items]

    async def generate_sql(self, request: GenerateSQLRequest) -> GenerateSQLResponse:
        """
        Generate SQL from natural language.

        Args:
            request: Generate SQL request

        Returns:
            GenerateSQLResponse: Generated SQL
        """
        context = {"tables": [{"name": table} for table in request.knowledge]}

        sql = await self.mock_ai.generate_sql(request.question, context)

        return GenerateSQLResponse(sql=sql, explanation="Generated SQL query")

    async def execute_pipeline(
        self, user_id: UUID, request: PipelineExecuteRequest
    ) -> PipelineExecuteResponse:
        """
        Execute AI pipeline.

        Args:
            user_id: User ID
            request: Pipeline execute request

        Returns:
            PipelineExecuteResponse: Pipeline response
        """
        # Create query
        query = await self.query_repo.create(
            user_id=user_id,
            question=request.question,
            configure_data=request.configure_data.model_dump(),
            status="processing",
        )

        # Create pipeline
        pipeline = await self.pipeline_repo.create(
            query_id=query.id,
            status="processing",
            steps=[],
        )

        await self.db.commit()
        await self.db.refresh(pipeline)

        # Process pipeline (in real implementation, use Celery)
        try:
            result = await self.mock_ai.process_pipeline(
                str(query.id), request.configure_data.model_dump()
            )

            pipeline.steps = result.get("steps", [])
            pipeline.status = "completed"
        except Exception as e:
            pipeline.status = "error"
            pipeline.errors = [{"message": str(e), "timestamp": str(datetime.now(timezone.utc))}]

        await self.db.commit()

        return PipelineExecuteResponse(
            pipeline_id=pipeline.id, status=pipeline.status
        )

    async def get_pipeline(self, pipeline_id: UUID) -> PipelineResponse:
        """
        Get pipeline by ID.

        Args:
            pipeline_id: Pipeline ID

        Returns:
            PipelineResponse: Pipeline data

        Raises:
            NotFoundError: If pipeline not found
        """
        pipeline = await self.pipeline_repo.get_by_id(pipeline_id)
        if not pipeline:
            raise NotFoundError("Pipeline not found")

        return PipelineResponse.model_validate(pipeline)

    async def get_history_by_id(self, history_id: UUID, user_id: UUID) -> AIHistoryItem:
        """
        Get history item by ID.

        Args:
            history_id: History ID
            user_id: User ID

        Returns:
            AIHistoryItem: History item

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id:
            raise NotFoundError("History not found")

        return AIHistoryItem.model_validate(history)

    async def delete_history(self, history_id: UUID, user_id: UUID) -> None:
        """
        Delete history item.

        Args:
            history_id: History ID
            user_id: User ID

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id:
            raise NotFoundError("History not found")

        await self.history_repo.delete(history_id)
        await self.db.commit()

    async def pin_history(self, history_id: UUID, user_id: UUID) -> AIHistoryItem:
        """
        Pin history item.

        Args:
            history_id: History ID
            user_id: User ID

        Returns:
            AIHistoryItem: Updated history item

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id:
            raise NotFoundError("History not found")

        history = await self.history_repo.update(history_id, pinned=True)
        await self.db.commit()
        await self.db.refresh(history)

        return AIHistoryItem.model_validate(history)

    async def unpin_history(self, history_id: UUID, user_id: UUID) -> AIHistoryItem:
        """
        Unpin history item.

        Args:
            history_id: History ID
            user_id: User ID

        Returns:
            AIHistoryItem: Updated history item

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id:
            raise NotFoundError("History not found")

        history = await self.history_repo.update(history_id, pinned=False)
        await self.db.commit()
        await self.db.refresh(history)

        return AIHistoryItem.model_validate(history)

    async def export_history(self, user_id: UUID) -> str:
        """
        Export history as CSV.

        Args:
            user_id: User ID

        Returns:
            str: CSV content
        """
        import csv
        from io import StringIO

        history_items = await self.history_repo.get_all(filters={"user_id": user_id})

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Query", "Answer", "Date", "Category", "Pinned"])

        for item in history_items:
            writer.writerow([
                str(item.id),
                item.query,
                item.answer,
                item.date.isoformat(),
                item.category or "",
                "Yes" if item.pinned else "No",
            ])

        return output.getvalue()

    async def get_pipeline_logs(self, pipeline_id: UUID, user_id: UUID) -> str:
        """
        Get pipeline logs.

        Args:
            pipeline_id: Pipeline ID
            user_id: User ID

        Returns:
            str: Pipeline logs

        Raises:
            NotFoundError: If pipeline not found
        """
        pipeline = await self.pipeline_repo.get_by_id(pipeline_id)
        if not pipeline:
            raise NotFoundError("Pipeline not found")

        # Check if user owns the query
        query = await self.query_repo.get_by_id(pipeline.query_id)
        if not query or query.user_id != user_id:
            raise NotFoundError("Pipeline not found")

        return pipeline.logs or ""

    async def generate_answer(
        self, question: str, knowledge: List[str], context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate answer from question.

        Args:
            question: Question
            knowledge: Knowledge base (connection IDs)
            context: Optional context

        Returns:
            str: Generated answer
        """
        answer = await self.mock_ai.generate_answer(question, knowledge, context or {})
        return answer

    async def analyze_question(
        self, question: str, knowledge: List[str]
    ) -> Dict[str, Any]:
        """
        Analyze question.

        Args:
            question: Question to analyze
            knowledge: Knowledge base (connection IDs)

        Returns:
            Dict[str, Any]: Analysis result
        """
        # TODO: Implement actual analysis
        # For now, return mock analysis
        return {
            "intent": "query",
            "entities": [],
            "category": "general",
            "confidence": 0.85,
        }

