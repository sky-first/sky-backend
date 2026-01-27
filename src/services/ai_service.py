"""AI service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.mock import MockAIService
from src.ai.real_service import RealAIService
from src.config.settings import settings
from src.core.exceptions import NotFoundError
from src.models.ai import AIFeedback, AIHistory, AIQuery, Pipeline
from src.models.user import User
from src.repositories.base import BaseRepository
from src.repositories.connection import ConnectionMetadataRepository, ConnectionRepository
from src.repositories.crew import CrewMemberRepository
from src.schemas.ai import (
    AIHistoryItem,
    AIQueryRequest,
    AIQueryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ConfigureData,
    CreateHistoryRequest,
    FeedbackRequest,
    GenerateSQLRequest,
    GenerateSQLResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResponse,
    ValidateSQLRequest,
    ValidateSQLResponse,
)
from src.utils.cache import CacheService, ai_response_cache_key

logger = logging.getLogger(__name__)


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
        self.real_ai = RealAIService() if settings.AI_SERVICE_TYPE == "real" else None
        self.query_repo = BaseRepository(db, AIQuery)
        self.history_repo = BaseRepository(db, AIHistory)
        self.pipeline_repo = BaseRepository(db, Pipeline)
        self.feedback_repo = BaseRepository(db, AIFeedback)
        self.connection_repo = ConnectionRepository(db)
        self.metadata_repo = ConnectionMetadataRepository(db)
        self.crew_member_repo = CrewMemberRepository(db)

    async def _get_first_active_connection(self, user_id: UUID) -> Optional[str]:
        """
        Get the first active connection for a user.

        Args:
            user_id: User ID

        Returns:
            Optional[str]: First active connection_id, or None
        """
        try:
            connections = await self.connection_repo.get_by_user(
                user_id, filters={"status": "active"}, limit=1
            )
            if connections:
                logger.info(
                    f"Using first active connection: {connections[0].id} ({connections[0].name})"
                )
                return str(connections[0].id)
            return None
        except Exception as e:
            logger.error(f"Error getting first active connection: {str(e)}", exc_info=True)
            # Ensure the session isn't left in a broken transaction state
            try:
                await self.db.rollback()
            except Exception:
                pass
            return None

    async def _get_first_active_connection_for_space(
        self, user_id: UUID, space_id: str
    ) -> Optional[str]:
        """
        Prefer the first active connection that is linked to the given space.
        Falls back to the general first active connection when none is linked.
        """
        try:
            from uuid import UUID as UUIDType

            from src.repositories.space import SpaceRepository

            space_uuid = UUIDType(space_id)
            space_repo = SpaceRepository(self.db)
            space_links = await space_repo.get_space_connections(space_uuid)
            allowed_ids = {str(link.connection_id) for link in space_links}

            if not allowed_ids:
                return await self._get_first_active_connection(user_id)

            # get active connections for user and pick the first that is linked to the space
            active = await self.connection_repo.get_by_user(
                user_id, filters={"status": "active"}, limit=100
            )
            for c in active:
                if str(c.id) in allowed_ids:
                    logger.info(
                        f"Using first active connection in space {space_id}: {c.id} ({c.name})"
                    )
                    return str(c.id)

            return await self._get_first_active_connection(user_id)
        except Exception as e:
            logger.error(
                f"Error getting first active connection for space {space_id}: {str(e)}",
                exc_info=True,
            )
            # Ensure the session isn't left in a broken transaction state
            try:
                await self.db.rollback()
            except Exception:
                pass
            return await self._get_first_active_connection(user_id)

    async def _resolve_connection_id_from_tables(
        self, table_names: List[str], user_id: UUID
    ) -> Optional[str]:
        """
        Resolve table names to connection_id by querying connection_metadata.

        Args:
            table_names: List of table names to search for
            user_id: User ID to filter connections

        Returns:
            Optional[str]: First connection_id that contains any of the tables, or None
        """
        if not table_names:
            return None

        try:
            # Get all connections for this user
            connections = await self.connection_repo.get_by_user(user_id)

            # Check each connection's metadata for the requested tables
            for connection in connections:
                metadata = await self.metadata_repo.get_by_connection_id(connection.id)
                if not metadata or not metadata.tables:
                    continue

                # Check if any of the requested tables exist in this connection
                connection_table_names = [
                    table.get("name") if isinstance(table, dict) else getattr(table, "name", None)
                    for table in metadata.tables
                ]

                # Normalize table names (case-insensitive comparison)
                connection_table_names_lower = [
                    t.lower() if t else "" for t in connection_table_names
                ]
                requested_tables_lower = [t.lower() for t in table_names]

                # If any requested table matches, return this connection_id
                if any(
                    req_table in connection_table_names_lower
                    for req_table in requested_tables_lower
                ):
                    logger.info(
                        f"Resolved tables {table_names} to connection_id {connection.id} "
                        f"(connection: {connection.name})"
                    )
                    return str(connection.id)

            logger.warning(
                f"Could not resolve tables {table_names} to any connection_id for user {user_id}"
            )
            return None
        except Exception as e:
            logger.error(f"Error resolving connection_id from tables: {str(e)}", exc_info=True)
            return None

    async def _get_user_crew_ids(
        self,
        user_id: UUID,
        space_id: Optional[str] = None,
        *,
        all_spaces: bool = False,
    ) -> List[str]:
        """
        Get crew IDs for a user in a specific space.

        Args:
            user_id: User ID
            space_id: Optional space ID. If provided, filters crews by space.

        Returns:
            List[str]: List of crew IDs as strings
        """
        try:
            from uuid import UUID as UUIDType

            if all_spaces:
                crew_ids = await self.crew_member_repo.get_crew_ids_by_user(user_id)
            else:
                if not space_id:
                    # If no space_id provided, return empty list
                    # (user will only see global data, crew_id IS NULL)
                    return []

                space_uuid = UUIDType(space_id) if isinstance(space_id, str) else space_id
                crew_ids = await self.crew_member_repo.get_crew_ids_by_user_and_space(
                    user_id, space_uuid
                )

            # Convert UUIDs to strings for API
            crew_ids_str = [str(crew_id) for crew_id in crew_ids]

            context_label = "(all spaces)" if all_spaces else f"in space {space_id}"
            logger.info(
                f"User {user_id} has access to {len(crew_ids_str)} crews {context_label}: {crew_ids_str}"
            )

            return crew_ids_str
        except Exception as e:
            logger.error(
                f"Error getting crew_ids for user {user_id} in space {space_id}: {str(e)}",
                exc_info=True,
            )
            # Return empty list on error - user will only see global data
            return []

    async def _resolve_space_id_for_connection(
        self, user_id: UUID, connection_id: str
    ) -> Optional[str]:
        """
        Resolve a space_id context for a given connection_id.

        In Personal mode, the frontend may not send a space_id. However, the AI engine
        expects a space_id to scope metadata/permissions. This tries to find a space where:
        - the user is a member, and
        - the connection is linked to that space (space_connections).
        """
        try:
            from uuid import UUID as UUIDType

            from sqlalchemy import or_, select

            from src.models.space import Space, SpaceConnection, SpaceMember

            conn_uuid = UUIDType(connection_id)

            stmt = (
                select(SpaceConnection.space_id)
                .join(Space, Space.id == SpaceConnection.space_id)
                .outerjoin(SpaceMember, SpaceMember.space_id == SpaceConnection.space_id)
                .where(SpaceConnection.connection_id == conn_uuid)
                .where(or_(Space.created_by == user_id, SpaceMember.user_id == user_id))
                .limit(1)
            )
            space_uuid = await self.db.scalar(stmt)
            return str(space_uuid) if space_uuid else None
        except Exception as e:
            logger.error(
                f"Error resolving space_id for connection {connection_id}: {str(e)}",
                exc_info=True,
            )
            return None

    async def process_query(self, user_id: UUID, query_data: AIQueryRequest) -> AIQueryResponse:
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

        # Process query - ALWAYS try to use real AI service first if configured
        try:
            if self.real_ai:
                # Use real AI service - need connection_id
                # Strategy:
                # 1. Try to get connection_id from knowledge (UUIDs or table names)
                # 2. If not found, use first active connection
                # 3. If still not found, fall back to mock
                connection_id = None
                table_names = []

                # First, try to detect UUIDs (connection_ids) in knowledge
                if configure_data.knowledge:
                    for item in configure_data.knowledge:
                        # Check if it looks like a UUID (connection_id)
                        if len(item) == 36 and item.count("-") == 4:
                            connection_id = item
                            break
                        else:
                            # Assume it's a table name
                            table_names.append(item)

                    # If no UUID found, try to resolve table names to connection_id
                    if not connection_id and table_names:
                        resolved_connection_id = await self._resolve_connection_id_from_tables(
                            table_names, user_id
                        )
                        if resolved_connection_id:
                            connection_id = resolved_connection_id

                # If still no connection_id, try to get first active connection
                if not connection_id:
                    space_id = getattr(query_data, "space_id", None)
                    if space_id:
                        connection_id = await self._get_first_active_connection_for_space(
                            user_id, space_id
                        )
                    else:
                        connection_id = await self._get_first_active_connection(user_id)
                    if connection_id:
                        logger.info(
                            f"No connection_id in knowledge, using first active connection: {connection_id}"
                        )

                if connection_id:
                    # Get space_id from query_data (may be missing in Personal mode)
                    space_id = getattr(query_data, "space_id", None)
                    if not space_id:
                        space_id = await self._resolve_space_id_for_connection(
                            user_id, connection_id
                        )

                    if space_id:
                        # Cache: short-lived response cache to avoid repeated expensive calls (e.g., Databricks spin-up)
                        cache_key: Optional[str] = None
                        cached_payload: Optional[Dict[str, Any]] = None
                        if settings.AI_RESPONSE_CACHE_TTL_SECONDS > 0:
                            try:
                                cache_key = ai_response_cache_key(
                                    space_id=space_id,
                                    connection_id=connection_id,
                                    question=configure_data.question,
                                )
                                cached_payload = await CacheService.get_json(cache_key)
                            except Exception:
                                cached_payload = None
                                logger.warning(
                                    "AI response cache check failed (ignored)",
                                    exc_info=True,
                                )

                        # Get crew_ids for this user (Personal mode => all crews across spaces)
                        is_personal = bool(getattr(query_data, "is_personal", False))
                        crew_ids = await self._get_user_crew_ids(
                            user_id,
                            space_id,
                            all_spaces=is_personal,
                        )
                        # Forward user-selected datasets/tables to AI engine when present.
                        # Frontend stores manual table selection in configure_data.knowledge.
                        selected_datasets: Optional[List[str]] = None
                        try:
                            if configure_data.knowledge:
                                table_names: List[str] = []
                                for item in configure_data.knowledge:
                                    # keep only non-UUIDs (UUIDs represent connection_id)
                                    if isinstance(item, str) and not (
                                        len(item) == 36 and item.count("-") == 4
                                    ):
                                        table_names.append(item)
                                selected_datasets = table_names or None
                        except Exception:
                            selected_datasets = None

                        logger.info(
                            f"Calling real AI service with connection_id={connection_id}, "
                            f"space_id={space_id}, crew_ids={crew_ids}, question='{configure_data.question[:50]}...'"
                        )
                        result = await self.real_ai.process_query(
                            connection_id=connection_id,
                            question=configure_data.question,
                            user_id=str(user_id),
                            space_id=space_id,
                            crew_ids=crew_ids if crew_ids else None,
                            thread_id=str(query.id),
                            is_personal=is_personal,
                            selected_datasets=selected_datasets,
                            instructions=configure_data.instructions,
                        )

                        # Update query with real AI results
                        query.answer = result.get("answer", "")
                        query.data_sample = result.get("data_sample", [])
                        query.sql = result.get("sql")
                        query.status = "completed"

                        # Store chosen table/datasets in configure_data for frontend
                        chosen_table = result.get("chosen_table")
                        chosen_datasets = result.get("chosen_datasets", [])
                        dynamic_title = result.get("title")
                        detected_language = result.get("detected_language")

                        # Debug log
                        logger.info(
                            f"Real AI service result: chosen_table={chosen_table}, "
                            f"chosen_datasets={chosen_datasets}, "
                            f"result_keys={list(result.keys())}"
                        )

                        if chosen_table or chosen_datasets or dynamic_title or detected_language:
                            # Get current config and ensure it's a dict
                            current_config = (
                                dict(query.configure_data) if query.configure_data else {}
                            )

                            if chosen_table:
                                current_config["chosen_table"] = chosen_table
                            if chosen_datasets:
                                current_config["chosen_datasets"] = chosen_datasets
                            elif chosen_table:
                                # Fallback: if only chosen_table exists, create array
                                current_config["chosen_datasets"] = [chosen_table]
                            if dynamic_title:
                                current_config["title"] = dynamic_title
                            if detected_language:
                                current_config["detected_language"] = detected_language

                            # Assign new dict to ensure SQLAlchemy detects the change
                            query.configure_data = current_config

                            # Mark as modified to ensure SQLAlchemy tracks the change
                            from sqlalchemy.orm.attributes import flag_modified

                            flag_modified(query, "configure_data")

                            logger.info(
                                f"Saved to configure_data: chosen_table={current_config.get('chosen_table')}, "
                                f"chosen_datasets={current_config.get('chosen_datasets')}, "
                                f"title={current_config.get('title')}, "
                                f"full_config_keys={list(current_config.keys())}"
                            )
                        else:
                            logger.warning(
                                f"No chosen_table or chosen_datasets in result. "
                                f"Result keys: {list(result.keys())}"
                            )

                        logger.info(
                            f"Real AI service returned answer (length: {len(query.answer or '')}, "
                            f"chosen_table: {chosen_table}, chosen_datasets: {chosen_datasets})"
                        )

                        # Cache write (best-effort)
                        if settings.AI_RESPONSE_CACHE_TTL_SECONDS > 0 and cache_key:
                            try:
                                payload = {
                                    "answer": query.answer,
                                    "data_sample": query.data_sample,
                                    "sql": query.sql,
                                    "chosen_table": chosen_table,
                                    "chosen_datasets": chosen_datasets,
                                    "title": dynamic_title,
                                    "detected_language": detected_language,
                                }
                                await CacheService.set_json(
                                    cache_key,
                                    payload,
                                    ttl=settings.AI_RESPONSE_CACHE_TTL_SECONDS,
                                )
                                logger.info(
                                    f"AI response cache SET key={cache_key} ttl={settings.AI_RESPONSE_CACHE_TTL_SECONDS}s"
                                )
                            except Exception:
                                logger.warning(
                                    "AI response cache set failed (ignored)",
                                    exc_info=True,
                                )
                    else:
                        # Fallback to mock if no space_id
                        logger.warning(
                            f"space_id not provided, falling back to mock AI service. "
                            f"connection_id={connection_id}"
                        )
                        result = await self.mock_ai.process_pipeline(
                            str(query.id), configure_data.model_dump()
                        )
                        query.answer = (
                            result.get("steps", [])[-1].get("content", "")
                            if result.get("steps")
                            else "Answer generated"
                        )
                        query.status = "completed"
                else:
                    # No connection_id found, use mock
                    logger.info(
                        f"No connection_id found in knowledge {configure_data.knowledge}, "
                        f"using mock AI service"
                    )
                    result = await self.mock_ai.process_pipeline(
                        str(query.id), configure_data.model_dump()
                    )
                    query.answer = (
                        result.get("steps", [])[-1].get("content", "")
                        if result.get("steps")
                        else "Answer generated"
                    )
                    query.status = "completed"
            else:
                # Use mock AI service (either not configured or no knowledge provided)
                if not self.real_ai:
                    logger.debug(
                        "Real AI service not configured (AI_SERVICE_TYPE != 'real'), using mock"
                    )
                elif not configure_data.knowledge:
                    logger.debug("No knowledge provided, using mock AI service")

                result = await self.mock_ai.process_pipeline(
                    str(query.id), configure_data.model_dump()
                )

                # Update query with answer
                query.answer = (
                    result.get("steps", [])[-1].get("content", "")
                    if result.get("steps")
                    else "Answer generated"
                )
                query.status = "completed"
        except Exception as e:
            query.status = "error"
            query.answer = f"Error: {str(e)}"

        await self.db.commit()
        await self.db.refresh(query)

        # Build response with chosen datasets from configure_data
        response_dict = query.__dict__.copy()

        # Debug: log what's in configure_data after refresh
        configure_data_raw = query.configure_data
        logger.info(
            f"After refresh - configure_data type: {type(configure_data_raw)}, "
            f"configure_data value: {configure_data_raw}"
        )

        configure_data = configure_data_raw or {}

        # Ensure configure_data is a dict (it might be a string or other type)
        if isinstance(configure_data, str):
            import json

            try:
                configure_data = json.loads(configure_data)
            except Exception:
                configure_data = {}
        elif not isinstance(configure_data, dict):
            configure_data = {}

        chosen_table = configure_data.get("chosen_table")
        chosen_datasets = configure_data.get("chosen_datasets", [])
        title = configure_data.get("title")
        detected_language = configure_data.get("detected_language")

        # Ensure chosen_datasets is a list
        if not isinstance(chosen_datasets, list):
            chosen_datasets = [chosen_datasets] if chosen_datasets else []

        # Fallback: if only chosen_table exists, create array
        if not chosen_datasets and chosen_table:
            chosen_datasets = [chosen_table]

        response_dict["chosen_table"] = chosen_table
        response_dict["chosen_datasets"] = chosen_datasets
        if title or detected_language:
            response_dict["meta"] = {
                "title": title,
                "detected_language": detected_language,
            }

        logger.info(
            f"Returning AIQueryResponse with chosen_table={chosen_table}, "
            f"chosen_datasets={chosen_datasets}, "
            f"configure_data_keys={list(configure_data.keys()) if isinstance(configure_data, dict) else 'not_dict'}"
        )

        return AIQueryResponse.model_validate(response_dict)

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

        await self.db.commit()
        await self.db.refresh(user_message)

        # Extract context and knowledge
        context = message_data.context or {}
        configure_data_dict = context.get("configure_data", {}) or context
        knowledge = configure_data_dict.get("knowledge", []) or []

        # Try to use real AI service if configured
        answer = None
        try:
            if self.real_ai:
                # Use real AI service - need connection_id
                # Strategy (same as process_query):
                # 1. Try to get connection_id from knowledge (UUIDs or table names)
                # 2. If not found, use first active connection
                # 3. If still not found, fall back to mock
                connection_id = None
                table_names = []

                # First, try to detect UUIDs (connection_ids) in knowledge
                if knowledge:
                    for item in knowledge:
                        # Check if it looks like a UUID (connection_id)
                        if isinstance(item, str) and len(item) == 36 and item.count("-") == 4:
                            connection_id = item
                            break
                        elif isinstance(item, str):
                            # Assume it's a table name
                            table_names.append(item)

                    # If no UUID found, try to resolve table names to connection_id
                    if not connection_id and table_names:
                        resolved_connection_id = await self._resolve_connection_id_from_tables(
                            table_names, user_id
                        )
                        if resolved_connection_id:
                            connection_id = resolved_connection_id

                # If still no connection_id, try to get first active connection
                if not connection_id:
                    # Try to get space_id from context
                    space_id = context.get("space_id") or configure_data_dict.get("space_id")
                    if space_id:
                        connection_id = await self._get_first_active_connection_for_space(
                            user_id, space_id
                        )
                    else:
                        connection_id = await self._get_first_active_connection(user_id)
                    if connection_id:
                        logger.info(
                            f"[send_chat_message] No connection_id in knowledge, using first active connection: {connection_id}"
                        )

                if connection_id:
                    # Get space_id from context or resolve from connection
                    space_id = context.get("space_id") or configure_data_dict.get("space_id")
                    if not space_id:
                        space_id = await self._resolve_space_id_for_connection(
                            user_id, connection_id
                        )

                    if space_id:
                        # Get crew_ids for this user
                        is_personal = bool(context.get("is_personal", False))
                        crew_ids = await self._get_user_crew_ids(
                            user_id,
                            space_id,
                            all_spaces=is_personal,
                        )

                        # Forward user-selected datasets/tables to AI engine when present
                        selected_datasets: Optional[List[str]] = None
                        try:
                            if knowledge:
                                table_names_list: List[str] = []
                                for item in knowledge:
                                    # keep only non-UUIDs (UUIDs represent connection_id)
                                    if isinstance(item, str) and not (
                                        len(item) == 36 and item.count("-") == 4
                                    ):
                                        table_names_list.append(item)
                                selected_datasets = table_names_list or None
                        except Exception:
                            selected_datasets = None

                        logger.info(
                            f"[send_chat_message] Calling real AI service with connection_id={connection_id}, "
                            f"space_id={space_id}, crew_ids={crew_ids}, question='{message_data.message[:50]}...'"
                        )

                        result = await self.real_ai.process_query(
                            connection_id=connection_id,
                            question=message_data.message,
                            user_id=str(user_id),
                            space_id=space_id,
                            crew_ids=crew_ids if crew_ids else None,
                            thread_id=str(user_message.id),
                            is_personal=is_personal,
                            selected_datasets=selected_datasets,
                        )

                        answer = result.get("answer", "")
                        logger.info(
                            f"[send_chat_message] Real AI service returned answer (length: {len(answer)})"
                        )
                    else:
                        # Fallback to mock if no space_id
                        logger.warning(
                            f"[send_chat_message] space_id not provided, falling back to mock AI service. "
                            f"connection_id={connection_id}"
                        )
                        answer = await self.mock_ai.generate_answer(
                            message_data.message, knowledge, context
                        )
                else:
                    # No connection_id found, use mock
                    logger.info(
                        f"[send_chat_message] No connection_id found in knowledge {knowledge}, "
                        f"using mock AI service"
                    )
                    answer = await self.mock_ai.generate_answer(
                        message_data.message, knowledge, context
                    )
            else:
                # Use mock AI service (not configured)
                logger.debug(
                    "[send_chat_message] Real AI service not configured (AI_SERVICE_TYPE != 'real'), using mock"
                )
                answer = await self.mock_ai.generate_answer(
                    message_data.message, knowledge, context
                )
        except Exception as e:
            logger.error(
                f"[send_chat_message] Error calling real AI service: {str(e)}", exc_info=True
            )
            # Fallback to mock on error
            answer = await self.mock_ai.generate_answer(message_data.message, knowledge, context)

        # Save AI response
        ai_message = await BaseRepository(self.db, ChatMessage).create(
            widget_id=message_data.widget_id,
            type="assistant",
            content=answer or "No answer generated",
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
            filter_type: Filter type (today, week, pinned, all)
            search: Search query
            category: Category filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[AIHistoryItem]: History items
        """
        from sqlalchemy import select

        # Build base query
        query = select(AIHistory).where(AIHistory.user_id == user_id)

        # Apply date filters
        now = datetime.now(timezone.utc)
        if filter_type == "today":
            # Last 24 hours
            yesterday = now - timedelta(hours=24)
            query = query.where(AIHistory.date >= yesterday)
        elif filter_type == "week":
            # Last 7 days
            week_ago = now - timedelta(days=7)
            query = query.where(AIHistory.date >= week_ago)
        elif filter_type == "pinned":
            # Only pinned items
            query = query.where(AIHistory.pinned.is_(True))
        # "all" or None: no date filter, show everything

        # Apply category filter
        if category:
            query = query.where(AIHistory.category == category)

        # Order by date descending (most recent first)
        query = query.order_by(AIHistory.date.desc())

        # Apply pagination
        query = query.offset(skip).limit(limit)

        # Execute query
        result = await self.db.execute(query)
        history_items = list(result.scalars().all())
        # Apply search filter if provided (client-side for better UX)
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

        return PipelineExecuteResponse(pipeline_id=pipeline.id, status=pipeline.status)

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
            writer.writerow(
                [
                    str(item.id),
                    item.query,
                    item.answer,
                    item.date.isoformat(),
                    item.category or "",
                    "Yes" if item.pinned else "No",
                ]
            )

        return output.getvalue()

    async def create_history(
        self, user_id: UUID, history_data: CreateHistoryRequest
    ) -> AIHistoryItem:
        """
        Create AI history entry.

        Args:
            user_id: User ID
            history_data: History data

        Returns:
            AIHistoryItem: Created history item
        """
        # Criar preview (primeiros 200 chars da resposta)
        preview = (
            history_data.answer[:200] + "..."
            if len(history_data.answer) > 200
            else history_data.answer
        )

        history = await self.history_repo.create(
            user_id=user_id,
            query=history_data.query,
            preview=preview,
            answer=history_data.answer,
            category=history_data.category,
            tags=history_data.tags or [],
            date=datetime.now(timezone.utc),
        )

        await self.db.commit()
        await self.db.refresh(history)

        return AIHistoryItem.model_validate(history)

    async def submit_feedback(self, user_id: UUID, feedback_data: FeedbackRequest) -> None:
        """
        Submit feedback for AI response.

        Args:
            user_id: User ID
            feedback_data: Feedback data
        """
        # Retrocompat: clientes antigos enviavam `message_id` (string local). Isso não
        # é mapeável de forma confiável para `ai_queries.id`, então apenas logamos.
        if not feedback_data.query_id:
            logger.info(
                "Ignoring AI feedback without query_id (deprecated message_id=%s, feedback=%s, user_id=%s)",
                feedback_data.message_id,
                feedback_data.feedback,
                user_id,
            )
            return

        query = await self.query_repo.get_by_id(feedback_data.query_id)
        if not query or query.user_id != user_id:
            # NotFound para não vazar existência/ownership
            raise NotFoundError("Query not found")

        # Upsert por (query_id, user_id)
        existing_res = await self.db.execute(
            select(AIFeedback).where(
                AIFeedback.query_id == feedback_data.query_id,
                AIFeedback.user_id == user_id,
            )
        )
        existing = existing_res.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if existing:
            existing.rating = feedback_data.feedback
            existing.comment = feedback_data.comment
            existing.updated_at = now
        else:
            self.db.add(
                AIFeedback(
                    query_id=feedback_data.query_id,
                    user_id=user_id,
                    rating=feedback_data.feedback,
                    comment=feedback_data.comment,
                    created_at=now,
                    updated_at=now,
                )
            )

        await self.db.commit()
        logger.info(
            "Stored AI feedback (query_id=%s, user_id=%s, rating=%s, has_comment=%s)",
            str(feedback_data.query_id),
            str(user_id),
            feedback_data.feedback,
            bool(feedback_data.comment),
        )

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

    async def analyze_question(self, question: str, knowledge: List[str]) -> Dict[str, Any]:
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

    async def validate_sql(self, request: ValidateSQLRequest, user: User) -> ValidateSQLResponse:
        """
        Validate SQL by calling AI Engine.

        Args:
            request: Validate SQL request
            user: Current user

        Returns:
            ValidateSQLResponse: Validation result

        Raises:
            HTTPException: If AI service is not available or call fails
        """
        import httpx
        from fastapi import HTTPException

        if not self.real_ai:
            raise HTTPException(
                status_code=503, detail="AI service is not available (not configured as 'real')"
            )

        try:
            # Resolve space_id if not provided
            space_id = request.space_id
            if not space_id and request.connection_id:
                space_id = await self._resolve_space_id_for_connection(
                    user.id, request.connection_id
                )

            # If still no space_id, raise error (space_id is required for AI Engine)
            if not space_id:
                raise HTTPException(
                    status_code=400, detail="space_id is required for SQL validation"
                )

            # Chama AI Engine via HTTP client
            result = await self.real_ai.http_client.validate_sql(
                connection_id=request.connection_id,
                sql=request.sql,
                user_id=str(user.id),
                space_id=space_id,
                crew_ids=request.crew_ids,
                is_personal=request.is_personal,
                include_explanation=request.include_explanation,
                question=request.question,
            )

            return ValidateSQLResponse(**result)
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"AI service HTTP error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=502, detail=f"AI service error: {str(e)}")
        except Exception as e:
            logger.error(f"Error validating SQL: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error validating SQL: {str(e)}")
