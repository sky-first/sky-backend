"""AI service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.chat_pipeline import ChatPipeline
from src.ai.evidence_extractor import extract_evidence
from src.ai.mock import MockAIService
from src.ai.real_service import RealAIService
from src.core.errors.chat_errors import ChatError
from src.schemas.ai_transparency import EvidenceChunkOut, ReasoningStepOut
from src.config.redis import get_redis
from src.config.settings import settings
from src.core.exceptions import NotFoundError
from src.models.ai import AIFeedback, AIHistory, AIQuery, ChatMessage, Pipeline
from src.models.user import User
from src.repositories.base import BaseRepository
from src.repositories.connection import ConnectionMetadataRepository, ConnectionRepository
from src.repositories.crew import CrewMemberRepository
from src.repositories.page import PageMemberRepository, PageRepository
from src.schemas.ai import (
    AIHistoryItem,
    AIQueryRequest,
    AIQueryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ConfigureData,
    CreateHistoryRequest,
    FeedbackRequest,
    GenerateInfographicRequest,
    GenerateSQLRequest,
    GenerateSQLResponse,
    PipelineExecuteRequest,
    PipelineExecuteResponse,
    PipelineResponse,
    ValidateSQLRequest,
    ValidateSQLResponse,
)
from src.services.permission_service import PermissionService
from src.utils.cache import CacheService, ai_response_cache_key

logger = logging.getLogger(__name__)


async def _enrich_citations_with_provenance(
    citations: Optional[List[Dict[str, Any]]], db: AsyncSession
) -> Optional[List[Dict[str, Any]]]:
    """Decorate AI citations with uploader / approver names.

    Lucas's 2026-04-30 brief: when the AI cites a Knowledge Library
    file, the canvas card needs to show "uploaded by X / approved
    by Y" so a reviewer knows which human vouched for the data.

    Inputs are AI-side citation dicts (file_id, file_name, chunk_index,
    page_number, excerpt, score). Each dict is mutated in place to add
    uploaded_by_name / uploaded_at and, when present in audit_events,
    approved_by_name / approved_at.

    Designed to fail soft — any DB error returns the citations
    untouched so the chat answer never blocks on an audit lookup.
    """
    if not citations or not isinstance(citations, list):
        return citations

    file_ids: List[UUID] = []
    for c in citations:
        try:
            fid = c.get("file_id") if isinstance(c, dict) else None
            if fid:
                file_ids.append(UUID(str(fid)))
        except Exception:
            continue
    if not file_ids:
        return citations

    try:
        from src.models.audit import AuditEvent
        from src.models.knowledge import KnowledgeFile

        # Uploader join — files + users.
        files_q = await db.execute(
            select(
                KnowledgeFile.id,
                KnowledgeFile.created_at,
                User.name,
            )
            .join(User, User.id == KnowledgeFile.user_id)
            .where(KnowledgeFile.id.in_(file_ids))
        )
        uploader_by_file: Dict[str, Dict[str, Any]] = {}
        for row in files_q:
            uploader_by_file[str(row[0])] = {
                "uploaded_at": row[1].isoformat() if row[1] else None,
                "uploaded_by_name": row[2],
            }

        # Approver — earliest approve event per file.
        approver_q = await db.execute(
            select(
                AuditEvent.resource_id,
                AuditEvent.actor_email,
                AuditEvent.occurred_at,
            )
            .where(
                AuditEvent.action == "knowledge.upload.approved",
                AuditEvent.resource_kind == "knowledge_file",
                AuditEvent.resource_id.in_([str(fid) for fid in file_ids]),
            )
            .order_by(AuditEvent.occurred_at.asc())
        )
        approver_by_file: Dict[str, Dict[str, Any]] = {}
        for row in approver_q:
            rid = str(row[0])
            if rid in approver_by_file:
                # Keep the earliest approval — approver_q is already
                # asc-ordered so first wins.
                continue
            approver_by_file[rid] = {
                "approved_at": row[2].isoformat() if row[2] else None,
                "approved_by_email": row[1],
            }

        # Resolve approver email → user.name in one round-trip.
        approver_emails = [
            v["approved_by_email"]
            for v in approver_by_file.values()
            if v.get("approved_by_email")
        ]
        name_by_email: Dict[str, str] = {}
        if approver_emails:
            users_q = await db.execute(
                select(User.email, User.name).where(User.email.in_(approver_emails))
            )
            name_by_email = {row[0]: row[1] for row in users_q if row[1]}

        for c in citations:
            if not isinstance(c, dict):
                continue
            fid = str(c.get("file_id") or "")
            up = uploader_by_file.get(fid)
            if up:
                c.setdefault("uploaded_by_name", up.get("uploaded_by_name"))
                c.setdefault("uploaded_at", up.get("uploaded_at"))
            ap = approver_by_file.get(fid)
            if ap:
                c.setdefault("approved_at", ap.get("approved_at"))
                email = ap.get("approved_by_email")
                if email:
                    c.setdefault(
                        "approved_by_name", name_by_email.get(email, email)
                    )
    except Exception as exc:  # noqa: BLE001 — never block chat on audit lookup
        logger.warning(
            "citation_provenance_enrich_failed err=%s file_ids=%s", exc, file_ids
        )

    return citations


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
        self.chat_repo = BaseRepository(db, ChatMessage)
        self.connection_repo = ConnectionRepository(db)
        self.metadata_repo = ConnectionMetadataRepository(db)
        self.crew_member_repo = CrewMemberRepository(db)
        self.page_repo = PageRepository(db)
        self.member_repo = PageMemberRepository(db)
        self.permission_service = PermissionService(db)

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

    async def _get_user_space_ids(self, user_id: UUID) -> List[str]:
        """Resolve every Space the caller belongs to (owner OR member).

        Used by Personal mode to forward the caller's space list to the
        AI service: the RAG's Personal branch then surfaces (a) the
        caller's own embeddings (user_id-scoped), (b) shared/global
        rows (NULL space_id + NULL user_id), AND (c) space-scoped rows
        for any space the caller is a member of (NULL user_id +
        space_id IN (caller_space_ids)).

        Without this list, a member of S1 asking in Personal mode
        would not see the connection-metadata embeddings that S1's
        admin indexed under S1.id — Personal would only see shared +
        their own private rows.
        """
        try:
            from src.models.space import Space, SpaceMember

            stmt = (
                select(Space.id)
                .outerjoin(SpaceMember, SpaceMember.space_id == Space.id)
                .where(or_(Space.created_by == user_id, SpaceMember.user_id == user_id))
                .distinct()
            )
            rows = (await self.db.execute(stmt)).all()
            return [str(r[0]) for r in rows]
        except Exception as e:
            logger.error(
                "Error resolving user space_ids for %s: %s", user_id, e, exc_info=True
            )
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
        # ── W-wire: pre-flight security pipeline ──────────────────
        # Same contract as send_chat_message — input guard runs BEFORE
        # we touch the DB so blocked input never persists. The
        # sanitised text feeds the rest of the flow; transparency
        # bundle (trace_id + flags) is attached to the response.
        pipeline = ChatPipeline(user_id=user_id, endpoint="/ai/query")
        guarded_input = pipeline.preflight(query_data.question)
        sanitised_question = guarded_input.text
        # Evidence chunks extracted from the AI engine response (when
        # present). Flows through to the W7 transparency bundle.
        extracted_evidence: List[EvidenceChunkOut] = []

        # Create query record
        configure_data = query_data.configure_data or ConfigureData(
            question=sanitised_question, knowledge=query_data.knowledge or []
        )

        # ── Knowledge layer splice ─────────────────────────────────
        # Load Metrics + Glossary visible to the user and render them
        # into a markdown block the AI engine prepends to its system
        # prompt. Org-certified definitions surface first so the
        # answer prefers them over Personal duplicates (Knowledge
        # refactor §7). Failures are logged but never blow the chat
        # path — the loader is best-effort context, not a hard dep.
        try:
            from src.services.knowledge_context_loader import (
                load_knowledge_context_for_user,
                render_knowledge_for_prompt,
            )
            from sqlalchemy import select as _select
            from src.models.user import User as _User
            user_row = await self.db.execute(_select(_User).where(_User.id == user_id))
            user_obj = user_row.scalar_one_or_none()
            if user_obj is not None:
                knowledge_ctx = await load_knowledge_context_for_user(
                    self.db, user_obj
                )
                rendered = render_knowledge_for_prompt(knowledge_ctx)
                if rendered:
                    # Stash on configure_data so the engine can splice it
                    # into the system prompt template (the engine reads
                    # ``knowledge_context`` from configure_data when set).
                    cd_dict = configure_data.model_dump()
                    cd_dict["knowledge_context"] = rendered
                    configure_data = ConfigureData(**{
                        k: v for k, v in cd_dict.items() if k in ConfigureData.model_fields
                    })
        except Exception as exc:  # noqa: BLE001 — knowledge is best-effort context
            logger.debug("knowledge_context_loader skipped: %s", exc)

        query = await self.query_repo.create(
            user_id=user_id,
            page_id=query_data.page_id,
            widget_id=query_data.widget_id,
            question=sanitised_question,
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
                    # --- KILL SWITCH (HARD CAP) ---
                    try:
                        redis = await get_redis()
                        if redis:
                            kill_switch_key = f"tenant_llm_requests:day:{connection_id}"
                            req_count = await redis.incr(kill_switch_key)
                            if req_count == 1:
                                await redis.expire(kill_switch_key, 86400)

                            if req_count > 5000:
                                logger.warning(
                                    f"Kill switch activated for connection {connection_id}. Count: {req_count}"
                                )
                                query.status = "failed"
                                query.answer = "Error: Daily AI quota exceeded for this environment (Hard Cap reached). Please contact support or check for runaway processes."
                                await self.db.commit()
                                await self.db.refresh(query)

                                response_dict = query.__dict__.copy()
                                response_dict["chosen_table"] = None
                                response_dict["chosen_datasets"] = []
                                return AIQueryResponse.model_validate(response_dict)
                    except Exception as e:
                        logger.error(f"Error checking AI rate limit: {e}")
                    # ------------------------------

                    # Get space_id from query_data (may be missing in Personal mode)
                    space_id = getattr(query_data, "space_id", None)
                    if not space_id:
                        space_id = await self._resolve_space_id_for_connection(
                            user_id, connection_id
                        )
                    # Personal mode fallback: when the user has no space
                    # membership to back the query, scope the AI call to the
                    # user themselves. The downstream AI service only uses
                    # space_id as a cache / audit key — a user-scoped value
                    # is semantically equivalent and, crucially, keeps the
                    # query on the real AI path instead of dropping to the
                    # mock fallback (which now raises ServiceUnavailable).
                    # `space_id_is_personal_fallback` marks that the permission
                    # check must NOT treat this as a real Space context, so it
                    # falls through to the ownership branch and returns every
                    # table the user owns on this connection.
                    space_id_is_personal_fallback = False
                    if not space_id:
                        is_personal_flag = bool(
                            getattr(query_data, "is_personal", False)
                        )
                        if is_personal_flag:
                            space_id = str(user_id)
                            space_id_is_personal_fallback = True
                            logger.info(
                                "Personal mode without space membership — using user_id as space_id scope (user=%s, connection=%s)",
                                user_id,
                                connection_id,
                            )

                    if space_id:
                        # Cache: short-lived response cache to avoid repeated expensive calls (e.g., Databricks spin-up)
                        cache_key: Optional[str] = None
                        cached_payload: Optional[Dict[str, Any]] = None  # noqa: F841
                        if settings.AI_RESPONSE_CACHE_TTL_SECONDS > 0:
                            try:
                                cache_key = ai_response_cache_key(
                                    space_id=space_id,
                                    connection_id=connection_id,
                                    question=configure_data.question,
                                )
                                await CacheService.get_json(cache_key)
                            except Exception:
                                logger.warning(
                                    "AI response cache check failed (ignored)",
                                    exc_info=True,
                                )

                        # Get crew_ids for this user (Personal mode => all crews across spaces)
                        is_personal = bool(getattr(query_data, "is_personal", False))
                        active_crew_id = getattr(query_data, "crew_id", None)

                        if is_personal:
                            # Personal mode: full access across all crews
                            crew_ids = await self._get_user_crew_ids(
                                user_id, space_id, all_spaces=True
                            )
                        elif active_crew_id:
                            # Collaborative mode: validate membership and restrict to this crew
                            user_crew_ids = await self._get_user_crew_ids(user_id, space_id)
                            if active_crew_id in user_crew_ids:
                                crew_ids = [active_crew_id]
                            else:
                                logger.warning(
                                    f"User {user_id} is not a member of crew {active_crew_id}, "
                                    f"falling back to all crews"
                                )
                                crew_ids = user_crew_ids
                        else:
                            # No specific crew: use all crews the user belongs to in the space
                            crew_ids = await self._get_user_crew_ids(user_id, space_id)
                        # --- MANDATORY PERMISSION FILTERING ---
                        # 1. Get truly authorized tables for this context (space/crew/user).
                        # When space_id was backfilled from user_id (Personal
                        # mode without a real space), pass None so the
                        # permission check falls into the ownership branch
                        # and returns every table the user owns on the
                        # connection. Passing a non-Space UUID would match
                        # zero SpaceTable links and produce an empty list.
                        perm_space_id = (
                            None
                            if space_id_is_personal_fallback
                            else (UUID(space_id) if space_id else None)
                        )
                        perm_crew_ids = (
                            None
                            if space_id_is_personal_fallback
                            else ([UUID(cid) for cid in crew_ids] if crew_ids else None)
                        )
                        try:
                            authorized_tables = await self.permission_service.get_authorized_tables(
                                user_id=user_id,
                                connection_id=UUID(connection_id),
                                space_id=perm_space_id,
                                crew_ids=perm_crew_ids,
                            )
                        except Exception as e:
                            logger.error(f"Error checking authorized tables: {e}", exc_info=True)
                            authorized_tables = []  # Fail closed

                        # 2. Forward user-selected datasets/tables from configure_data.knowledge,
                        # BUT filter them against authorized_tables.
                        requested_datasets: List[str] = []
                        if configure_data.knowledge:
                            for item in configure_data.knowledge:
                                if isinstance(item, str) and not (
                                    len(item) == 36 and item.count("-") == 4
                                ):
                                    requested_datasets.append(item)

                        if requested_datasets:
                            # Intersect requested with authorized (case-sensitive as per DB storage)
                            selected_datasets = [
                                t for t in requested_datasets if t in authorized_tables
                            ]
                        else:
                            # If no specific requested tables, use all authorized tables
                            selected_datasets = authorized_tables

                        if not selected_datasets:
                            logger.warning(
                                f"No authorized tables found for user {user_id} on connection {connection_id}"
                            )
                            # We still pass an empty list or None to the AI engine so it can report "no access"
                            selected_datasets = []

                        # Build security config for row/column masking in AI service
                        from src.services.security_config_builder import build_security_config

                        sec_config = None
                        try:
                            sec_config = await build_security_config(
                                db=self.db,
                                user_id=user_id,
                                connection_id=UUID(connection_id),
                            )
                        except Exception as sec_err:
                            logger.warning("security_config.build_failed: %s", sec_err)

                        logger.info(
                            f"Calling real AI service with connection_id={connection_id}, "
                            f"space_id={space_id}, crew_ids={crew_ids}, question='{str(configure_data.question)[:50]}...'"
                        )
                        # Splice the rendered Knowledge block (Metrics +
                        # Glossary + Relationships) into the instructions
                        # the engine receives. This is the seam the AI
                        # service uses as its system-prompt addendum, so
                        # carrying knowledge_context here is what makes
                        # the answer actually reason over governed
                        # definitions instead of inventing them.
                        merged_instructions = configure_data.instructions or ""
                        knowledge_block = (
                            getattr(configure_data, "knowledge_context", None)
                            or (
                                configure_data.model_dump().get(
                                    "knowledge_context"
                                )
                                if hasattr(configure_data, "model_dump")
                                else None
                            )
                        )
                        if knowledge_block:
                            merged_instructions = (
                                f"{knowledge_block}\n\n{merged_instructions}"
                                if merged_instructions
                                else knowledge_block
                            )

                        # Personal mode: forward the caller's full Space
                        # membership so the AI RAG can surface
                        # space-scoped rows from every Space the caller
                        # belongs to. Skip outside Personal — the
                        # collaborative branch already scopes to
                        # `space_id` alone.
                        caller_space_ids: Optional[List[str]] = None
                        if is_personal:
                            caller_space_ids = await self._get_user_space_ids(user_id)

                        result = await self.real_ai.process_query(
                            connection_id=connection_id,
                            question=configure_data.question,
                            user_id=str(user_id),
                            space_id=space_id,
                            crew_ids=crew_ids if crew_ids else None,
                            space_ids=caller_space_ids,
                            thread_id=str(query.id),
                            is_personal=is_personal,
                            selected_datasets=selected_datasets,
                            authorized_tables=list(authorized_tables),
                            instructions=merged_instructions or None,
                            response_format=configure_data.response_format,
                            security_config=sec_config,
                            mentioned_file_ids=getattr(query_data, "mentioned_file_ids", None),
                        )

                        # Update query with real AI results
                        query.answer = result.get("answer", "")
                        query.data_sample = result.get("data_sample", [])
                        query.sql = result.get("sql")
                        query.status = "completed"

                        # W7 — extract evidence chunks. Knowledge specialist
                        # returns its own structured evidence (Sources tab),
                        # which we prefer; fall back to the heuristic
                        # extractor for legacy SQL/data answers.
                        try:
                            engine_evidence = result.get("evidence") or []
                            if engine_evidence:
                                from src.schemas.ai_transparency import EvidenceChunkOut as _EC
                                extracted_evidence = []
                                for raw in engine_evidence:
                                    if not isinstance(raw, dict):
                                        continue
                                    try:
                                        extracted_evidence.append(
                                            _EC(
                                                id=str(raw.get("id") or ""),
                                                kind=str(raw.get("kind") or "unknown"),
                                                source_label=str(raw.get("source_label") or "(unlabelled)"),
                                                snippet=str(raw.get("snippet") or "")[:400],
                                                href=raw.get("href"),
                                            )
                                        )
                                    except Exception:
                                        continue
                            else:
                                extracted_evidence = extract_evidence(result)
                        except Exception:
                            extracted_evidence = []

                        # W7 — emit user-readable reasoning steps the
                        # engine surfaced (Knowledge specialist does
                        # this; SQL flow doesn't yet). We deliberately
                        # never include model name / latency here.
                        try:
                            engine_steps = result.get("reasoning_steps") or []
                            for raw in engine_steps:
                                if not isinstance(raw, dict):
                                    continue
                                summary = str(raw.get("summary") or "").strip()
                                kind = str(raw.get("kind") or "step")
                                if summary:
                                    pipeline._reasoning.append(
                                        ReasoningStepOut(
                                            step=len(pipeline._reasoning) + 1,
                                            kind=kind,
                                            summary=summary,
                                        )
                                    )
                        except Exception as exc:
                            logger.debug("reasoning_steps splice skipped: %s", exc)

                        # Store chosen table/datasets in configure_data for frontend
                        chosen_table = result.get("chosen_table")
                        chosen_datasets = result.get("chosen_datasets", [])
                        dynamic_title = result.get("title")
                        detected_language = result.get("detected_language")
                        knowledge_citations = result.get("citations")

                        # Debug log
                        logger.info(
                            f"Real AI service result: chosen_table={chosen_table}, "
                            f"chosen_datasets={chosen_datasets}, "
                            f"result_keys={list(result.keys())}"
                        )

                        if chosen_table or chosen_datasets or dynamic_title or detected_language or knowledge_citations:
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
                            if knowledge_citations:
                                current_config["citations"] = knowledge_citations

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
            # User-facing message must NEVER leak internal URLs, pod IDs,
            # connection UUIDs, or httpx's default "for url 'http://...'"
            # preamble. Classify the exception into a platform_error key
            # the frontend PlatformErrorBanner can render cleanly, and log
            # the full detail server-side only.
            import httpx as _httpx

            error_key = "chat.server"
            friendly = "The AI service had a problem. Please try again."
            if isinstance(e, _httpx.TimeoutException):
                error_key = "chat.timeout"
                friendly = "The question took too long to answer. Try a simpler one or retry."
            elif isinstance(e, _httpx.HTTPStatusError):
                code = e.response.status_code
                if code == 429:
                    error_key = "chat.rate_limited"
                    friendly = "Too many AI requests in a short window. Please wait a few seconds and retry."
                elif 500 <= code < 600:
                    error_key = "chat.server"
                    friendly = (
                        "The AI service is temporarily unavailable. Please retry in a moment."
                    )
                elif code == 400:
                    error_key = "chat.server"
                    friendly = "I couldn't understand that question. Try rephrasing it."
                else:
                    error_key = "chat.server"
                    friendly = "The AI service rejected the request. Please retry or open a ticket."
            elif isinstance(e, (_httpx.ConnectError, _httpx.NetworkError)):
                error_key = "chat.network"
                friendly = "Couldn't reach the AI service. Check your connection and retry."

            query.status = "error"
            # Store the friendly message as `answer` so the chat bubble shows
            # something readable. Key + details go into a separate field if
            # the response schema supports it — the frontend reads `error_key`
            # when present to pick the PlatformErrorBanner template.
            query.answer = friendly
            try:
                # extra_data is a JSONB column used for misc metadata on
                # AIQuery; if it doesn't exist in older schemas this block
                # is a no-op (setattr on non-column is silently dropped by
                # SQLAlchemy declarative).
                extra = dict(getattr(query, "extra_data", None) or {})
                extra["error_key"] = error_key
                extra["exception_type"] = type(e).__name__
                query.extra_data = extra
            except Exception:
                pass
            logger.exception(
                "AI query pipeline failed (query_id=%s, connection_id=%s, error_key=%s)",
                query.id,
                locals().get("connection_id"),
                error_key,
            )

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
        citations = configure_data.get("citations") if isinstance(configure_data, dict) else None
        # Enrich each citation with uploader + approver names so the
        # canvas card can render the proveniência popover (Lucas's
        # 2026-04-30 brief). Read-only; failure-soft.
        citations = await _enrich_citations_with_provenance(citations, self.db)
        if title or detected_language or citations:
            response_dict["meta"] = {
                "title": title,
                "detected_language": detected_language,
                "citations": citations,
            }

        logger.info(
            f"Returning AIQueryResponse with chosen_table={chosen_table}, "
            f"chosen_datasets={chosen_datasets}, "
            f"configure_data_keys={list(configure_data.keys()) if isinstance(configure_data, dict) else 'not_dict'}"
        )

        # ── W-wire: post-flight security pipeline ─────────────────
        # Pass the answer text through the W5 output guard. On ACL
        # breach, ChatOutputACLBreach raises and the API handler
        # converts it to the CHAT_OUTPUT_ACL_BREACH envelope (502).
        # On secret/leak detection, the answer is rewritten in place
        # before serialization. Transparency bundle attached.
        raw_answer = response_dict.get("answer") or ""
        # When evidence ids are present, lock the output guard's
        # citation check to that authorised set so the LLM can't
        # hallucinate a foreign reference.
        authorised_ids = tuple(c.id for c in extracted_evidence if c.id)
        finalized = pipeline.finalize(
            raw_answer,
            evidence=extracted_evidence or None,
            evidence_count=len(extracted_evidence) or None,
            authorized_evidence_ids=authorised_ids,
        )
        response_dict["answer"] = finalized.answer

        ai_response = AIQueryResponse.model_validate(response_dict)
        ai_response.transparency = finalized.transparency
        return ai_response

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

        # ── W-wire: pre-flight security pipeline ──────────────────
        # Input guard runs BEFORE we touch the DB. Hard fail (empty,
        # too long, policy block) raises a ChatError that the API
        # handler turns into the right CHAT_* envelope. The trace_id
        # travels with every downstream log line.
        pipeline = ChatPipeline(user_id=user_id, endpoint="/ai/chat")
        guarded_input = pipeline.preflight(message_data.message)
        # Use the sanitised text downstream — strips control chars,
        # invisibles, NFC normalisation. Length limits already enforced.
        sanitised_message = guarded_input.text
        extracted_evidence: List[EvidenceChunkOut] = []

        # Save user message
        user_message = await self.chat_repo.create(
            widget_id=message_data.widget_id,
            page_id=message_data.page_id,
            type="user",
            content=sanitised_message,
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
                    # Personal mode fallback — see process_query for rationale.
                    space_id_is_personal_fallback = False
                    if not space_id:
                        is_personal_flag = bool(
                            message_data.is_personal
                            if message_data.is_personal is not None
                            else context.get("is_personal", False)
                        )
                        if is_personal_flag:
                            space_id = str(user_id)
                            space_id_is_personal_fallback = True
                            logger.info(
                                "[send_chat_message] Personal mode without space — using user_id as space_id (user=%s, connection=%s)",
                                user_id,
                                connection_id,
                            )

                    if space_id:
                        # Resolve crew_ids — prefer explicit crew_id from request (collaborative mode)
                        is_personal = bool(
                            message_data.is_personal
                            if message_data.is_personal is not None
                            else context.get("is_personal", False)
                        )
                        active_crew_id = message_data.crew_id or context.get("crew_id")

                        if is_personal:
                            crew_ids = await self._get_user_crew_ids(
                                user_id, space_id, all_spaces=True
                            )
                        elif active_crew_id:
                            user_crew_ids = await self._get_user_crew_ids(user_id, space_id)
                            crew_ids = (
                                [active_crew_id]
                                if active_crew_id in user_crew_ids
                                else user_crew_ids
                            )
                        else:
                            crew_ids = await self._get_user_crew_ids(user_id, space_id)

                        # --- MANDATORY PERMISSION FILTERING ---
                        # 1. Get truly authorized tables for this context.
                        # Mirror of the process_query fallback: skip Space /
                        # Crew context when space_id was backfilled from
                        # user_id in Personal mode so the ownership branch
                        # returns every table the user owns.
                        perm_space_id = (
                            None
                            if space_id_is_personal_fallback
                            else (UUID(space_id) if space_id else None)
                        )
                        perm_crew_ids = (
                            None
                            if space_id_is_personal_fallback
                            else ([UUID(cid) for cid in crew_ids] if crew_ids else None)
                        )
                        try:
                            authorized_tables = await self.permission_service.get_authorized_tables(
                                user_id=user_id,
                                connection_id=UUID(connection_id),
                                space_id=perm_space_id,
                                crew_ids=perm_crew_ids,
                            )
                        except Exception as e:
                            logger.error(
                                f"[send_chat_message] Error checking authorized tables: {e}",
                                exc_info=True,
                            )
                            authorized_tables = []  # Fail closed

                        # 2. Forward user-selected datasets/tables from knowledge,
                        # BUT filter them against authorized_tables.
                        requested_datasets: List[str] = []
                        if knowledge:
                            for item in knowledge:
                                if isinstance(item, str) and not (
                                    len(item) == 36 and item.count("-") == 4
                                ):
                                    requested_datasets.append(item)

                        if requested_datasets:
                            # Intersect requested with authorized
                            selected_datasets = [
                                t for t in requested_datasets if t in authorized_tables
                            ]
                        else:
                            # If no specific requested tables, use all authorized tables
                            selected_datasets = authorized_tables

                        if not selected_datasets:
                            logger.warning(
                                f"[send_chat_message] No authorized tables found for user {user_id} on connection {connection_id}"
                            )
                            selected_datasets = []

                        logger.info(
                            f"[send_chat_message] Calling real AI service with connection_id={connection_id}, "
                            f"space_id={space_id}, crew_ids={crew_ids}, question='{str(message_data.message)[:50]}...'"
                        )

                        # Personal mode: forward caller Space membership.
                        # See process_query branch for the full rationale.
                        caller_space_ids: Optional[List[str]] = None
                        if is_personal:
                            caller_space_ids = await self._get_user_space_ids(user_id)

                        result = await self.real_ai.process_query(
                            connection_id=connection_id,
                            question=message_data.message,
                            user_id=str(user_id),
                            space_id=space_id,
                            crew_ids=crew_ids if crew_ids else None,
                            space_ids=caller_space_ids,
                            thread_id=str(user_message.id),
                            is_personal=is_personal,
                            selected_datasets=selected_datasets,
                            authorized_tables=list(authorized_tables),
                            ai_tone=message_data.ai_tone,
                            ai_style=message_data.ai_style,
                        )

                        answer = result.get("answer", "")
                        try:
                            extracted_evidence = extract_evidence(result)
                        except Exception:
                            extracted_evidence = []
                        logger.info(
                            f"[send_chat_message] Real AI service returned answer (length: {len(answer)}, "
                            f"evidence_chunks={len(extracted_evidence)})"
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
                f"[send_chat_message] Error calling real AI service: {str(e)}",
                exc_info=True,
            )
            # Fallback to mock on error
            answer = await self.mock_ai.generate_answer(message_data.message, knowledge, context)

        # ── W-wire: post-flight security pipeline ─────────────────
        # Output guard scans for secrets, system-prompt leaks, and
        # ACL-cited evidence outside the authorised set. On a clear
        # ACL breach the pipeline raises ChatOutputACLBreach (502).
        # Otherwise we get back a (possibly redacted) answer plus the
        # transparency bundle that travels with the response.
        authorised_ids = tuple(c.id for c in extracted_evidence if c.id)
        finalized = pipeline.finalize(
            answer or "No answer generated",
            evidence=extracted_evidence or None,
            evidence_count=len(extracted_evidence) or None,
            authorized_evidence_ids=authorised_ids,
        )
        safe_answer = finalized.answer

        # Save AI response (post-redaction text — never persist a leaked secret)
        ai_message = await self.chat_repo.create(
            widget_id=message_data.widget_id,
            page_id=message_data.page_id,
            type="assistant",
            content=safe_answer,
        )

        await self.db.commit()
        await self.db.refresh(ai_message)

        response = ChatMessageResponse.model_validate(ai_message)
        # Attach the transparency bundle so the FE "Ver como foi gerado"
        # panel can render. Field is optional (W7) — old clients ignore.
        response.transparency = finalized.transparency
        return response

    async def generate_infographic(
        self,
        user_id: UUID,
        request: "GenerateInfographicRequest",
    ) -> Dict[str, Any]:
        """
        Generate structured infographic data using the real AI service (or mock).
        """

        if self.real_ai:
            try:
                return await self.real_ai.generate_infographic(
                    question=request.question,
                    answer=request.answer,
                    data_sample=request.data_sample,
                    language=request.language,
                    style=request.style,
                )
            except Exception as e:
                logger.error(f"Error calling real AI generate_infographic: {e}")
                # Fallback to mock if needed, or just return empty/partial
                pass

        # Fallback (mock or error)
        return await self.mock_ai.generate_infographic(
            question=request.question,
            answer=request.answer,
            data_sample=request.data_sample,
            language=request.language,
            style=request.style,
        )

    async def get_history(
        self,
        user_id: UUID,
        page_id: Optional[UUID] = None,
        filter_type: Optional[str] = None,
        search: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        crew_id: Optional[str] = None,
        space_id: Optional[str] = None,
        is_personal: bool = False,
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

        # ── Build base query based on context ──────────────────────────────────
        #
        # Priority:
        #   1. is_personal=True → scoped to (user_id + page_id), ignore crew
        #   2. crew_id present  → scoped to all interactions for that crew
        #   3. fallback         → scoped to (user_id + page_id)
        #
        base_query = select(AIHistory)

        if is_personal:
            # Strict personal isolation: only the current user's items on this page
            conditions = [AIHistory.user_id == user_id]
            if page_id is not None:
                conditions.append(AIHistory.page_id == page_id)
            base_query = base_query.where(*conditions)
        elif crew_id:
            # Collaborative crew mode: all interactions for this crew, any page, any user
            base_query = base_query.where(AIHistory.crew_id == crew_id)
        elif page_id is not None:
            # Personal fallback with known page_id
            base_query = base_query.where(
                AIHistory.user_id == user_id,
                AIHistory.page_id == page_id,
            )
        else:
            # No context at all — just return user's own history
            base_query = base_query.where(AIHistory.user_id == user_id)

        # ── Apply filter_type ──────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        if filter_type == "today":
            yesterday = now - timedelta(hours=24)
            base_query = base_query.where(AIHistory.date >= yesterday)
        elif filter_type == "week":
            week_ago = now - timedelta(days=7)
            base_query = base_query.where(AIHistory.date >= week_ago)
        elif filter_type == "pinned":
            base_query = base_query.where(AIHistory.pinned.is_(True))
        # "all" / None → no date filter

        # ── Apply additional filters ───────────────────────────────────────────
        if category:
            base_query = base_query.where(AIHistory.category == category)

        # ── Apply search (server-side for accuracy) ────────────────────────────
        if search:
            search_lower = f"%{search.lower()}%"
            base_query = base_query.where(
                or_(
                    AIHistory.query.ilike(search_lower),
                    AIHistory.preview.ilike(search_lower),
                    AIHistory.answer.ilike(search_lower),
                )
            )

        # ── Sort + paginate ────────────────────────────────────────────────────
        base_query = base_query.order_by(AIHistory.pinned.desc(), AIHistory.date.desc())
        base_query = base_query.offset(skip).limit(limit)

        result = await self.db.execute(base_query)
        history_items = list(result.scalars().all())

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
            page_id=request.page_id,
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

    async def get_history_by_id(
        self, history_id: UUID, user_id: UUID, page_id: UUID
    ) -> AIHistoryItem:
        """
        Get history item by ID.

        Args:
            history_id: History ID
            user_id: User ID
            page_id: Page ID

        Returns:
            AIHistoryItem: History item

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id or history.page_id != page_id:
            raise NotFoundError("History not found")

        return AIHistoryItem.model_validate(history)

    async def delete_history(self, history_id: UUID, user_id: UUID, page_id: UUID) -> None:
        """
        Delete history item.

        Args:
            history_id: History ID
            user_id: User ID
            page_id: Page ID

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id or history.page_id != page_id:
            raise NotFoundError("History not found")

        await self.history_repo.delete(history_id)
        await self.db.commit()

    async def pin_history(self, history_id: UUID, user_id: UUID, page_id: UUID) -> AIHistoryItem:
        """
        Pin history item.

        Args:
            history_id: History ID
            user_id: User ID
            page_id: Page ID

        Returns:
            AIHistoryItem: Updated history item

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id or history.page_id != page_id:
            raise NotFoundError("History not found")

        history = await self.history_repo.update(history_id, pinned=True)
        await self.db.commit()
        await self.db.refresh(history)

        return AIHistoryItem.model_validate(history)

    async def unpin_history(self, history_id: UUID, user_id: UUID, page_id: UUID) -> AIHistoryItem:
        """
        Unpin history item.

        Args:
            history_id: History ID
            user_id: User ID
            page_id: Page ID

        Returns:
            AIHistoryItem: Updated history item

        Raises:
            NotFoundError: If history not found
        """
        history = await self.history_repo.get_by_id(history_id)
        if not history or history.user_id != user_id or history.page_id != page_id:
            raise NotFoundError("History not found")

        history = await self.history_repo.update(history_id, pinned=False)
        await self.db.commit()
        await self.db.refresh(history)

        return AIHistoryItem.model_validate(history)

    async def export_history(self, user_id: UUID, page_id: UUID) -> str:
        """
        Export history as CSV.

        Args:
            user_id: User ID
            page_id: Page ID

        Returns:
            str: CSV content
        """
        import csv
        from io import StringIO

        history_items = await self.history_repo.get_all(
            filters={"user_id": user_id, "page_id": page_id}
        )

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
            page_id=history_data.page_id,
            query=history_data.query,
            preview=preview,
            answer=history_data.answer,
            category=history_data.category,
            tags=history_data.tags or [],
            date=datetime.now(timezone.utc),
            space_id=history_data.space_id,
            crew_id=history_data.crew_id,
            duration_ms=history_data.duration_ms,
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
        self,
        question: str,
        knowledge: List[str],
        context: Optional[Dict[str, Any]] = None,
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
                status_code=503,
                detail="AI service is not available (not configured as 'real')",
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
        except httpx.ConnectError as e:
            logger.error(f"AI service connection failed: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"AI service unavailable: Connection failed to {e.request.url}",
            )
        except httpx.TimeoutException as e:
            logger.error(f"AI service timeout: {e}")
            raise HTTPException(status_code=504, detail=f"AI service timeout: {e.request.url}")
        except httpx.HTTPStatusError as e:
            logger.error(f"AI service HTTP error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=502,
                detail=f"AI service error ({e.response.status_code}): {e.response.text}",
            )
        except Exception as e:
            error_msg = str(e) or repr(e) or "Unknown error"
            logger.error(f"Error validating SQL: {error_msg}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error validating SQL: {error_msg}")
