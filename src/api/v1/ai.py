"""AI endpoints."""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.api.deps import get_current_user, get_db_session, require_service_principal
from src.config.settings import settings
from src.core.locale import DEFAULT_LOCALE, get_message
from src.middleware.request_limits import depth_guard_dependency
from src.models.user import User
from src.rate_limit.core import (
    RateLimitExceeded,
    RedisFixedWindowRateLimiter,
    default_buckets_for_request,
    resolve_tenant_key,
)
from src.repositories.conversation import ConversationRepository
from src.repositories.message import MessageRepository
from src.repositories.page import PageRepository
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
from src.schemas.chat_stream import (
    done_event,
    error_event,
    meta_event,
    normalize_event,
    parse_sse_data_line,
    progress_event,
    sse,
    with_heartbeat,
)
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.scan_insight import ScanInsightNotifyRequest, ScanInsightNotifyResponse
from src.services import pricing_service
from src.services.ai_service import AIService
from src.services.beats_service import BeatsService
from src.services.rbac_service import RBACService
from src.services.scan_insight_service import record_scan_finding

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/query",
    response_model=AIQueryResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Process AI query",
    description="Process a natural language question and return answer",
    dependencies=[Depends(depth_guard_dependency)],
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
    # RBAC enforcement: pick the right key based on whether the caller
    # provided a space_id.
    #   • space_id present → "ai.query"           (("space","viewer"))
    #     Caller must be at least a viewer of that Space.
    #   • space_id absent  → "ai.query.personal"  (("tenant","any_member"))
    #     Personal scope: any authenticated platform user can ask the
    #     AI against their own aggregated data. Cross-tenant leakage
    #     is prevented at the connection layer, not at this gate.
    # Pre-PR2 the Personal path was unguarded — the FE resolver still
    # required ai.query.personal because the space-scoped rule
    # short-circuits without a space_id, surfacing as "You don't
    # have permission to use AI in this workspace." for Members on
    # first SSO login.
    rbac = RBACService(db)
    space_uuid: Optional[UUID] = None
    if query_data.space_id:
        try:
            space_uuid = UUID(query_data.space_id)
        except Exception:
            space_uuid = None
    permission_key = "ai.query" if space_uuid is not None else "ai.query.personal"
    await rbac.assert_permission(current_user, permission_key, space_id=space_uuid)

    # Space→Crew security boundary (2026-06): in collaborative mode a
    # question MUST target a crew, never a bare space. A query with a
    # space_id but no crew_id (and not Personal mode) would otherwise fall
    # back to "all crews the user belongs to in this space" — which leaks
    # the union of every crew's tables instead of the explicitly selected
    # crew's surface. Reject it here, server-side. Personal mode
    # (is_personal=True, no space) is exempt. Every space has a default
    # "General" crew, so a valid crew is always selectable in the FE.
    if settings.CREW_REQUIRED_FOR_QUERY and space_uuid is not None:
        is_personal_q = bool(getattr(query_data, "is_personal", False))
        if not is_personal_q and not query_data.crew_id:
            from src.core.exceptions import BadRequestError

            raise BadRequestError(
                "A crew must be selected to ask questions in a space. "
                "Pick a crew — every space has a default 'General' crew."
            )

    # Content-plane membership gate (Option B, 2026-06): querying a Space/Crew's
    # data requires REAL membership of that specific crew (or space) — platform
    # admins do NOT bypass content. This is stricter than the ai.query RBAC key
    # (which only requires "some membership in the space"): here we gate the
    # EXACT crew whose data is requested, so an admin who belongs to crew A
    # cannot read crew B's data. Personal mode is exempt.
    if space_uuid is not None and not bool(getattr(query_data, "is_personal", False)):
        from src.services.authorization import Authorization

        crew_uuid: Optional[UUID] = None
        if query_data.crew_id:
            try:
                crew_uuid = UUID(query_data.crew_id)
            except Exception:
                crew_uuid = None
        await Authorization(db).assert_content_access(
            current_user, space_id=space_uuid, crew_id=crew_uuid
        )

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

    # Resolve and validate page_id
    if not query_data.page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        query_data.page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(query_data.page_id, current_user.id)

    # Locale fallback — same pattern as /chat and /chat/stream.
    prefs = current_user.preferences or {}
    if query_data.locale is None:
        query_data.locale = prefs.get("language", DEFAULT_LOCALE)

    # Beats quota gate — fires AFTER rate limit (cheap Redis check)
    # and AFTER page validation, so users near their cap aren't
    # charged when those earlier gates would have rejected the call
    # anyway. Raises 402 PaymentRequiredError before the LLM runs;
    # records 20 beats on success. Demo: 500 beats / 7d. Starter:
    # 5K / 30d. See src/config/plan_quotas.py.
    await BeatsService(db).check_and_record(
        current_user,
        kind="chat",
        source_id=None,
    )

    response = await ai_service.process_query(current_user.id, query_data)
    # Pricing Fase 1 — bump the monthly query counter at the end of
    # the request so failed queries (LLM error, etc.) don't get
    # charged against the tenant's quota.
    try:
        await pricing_service.record_query_usage(db)
    except Exception:  # pragma: no cover — accounting failure is non-fatal
        logger.exception("pricing_record_query_usage_failed")
    return response


@router.post(
    "/scan-insights/notify",
    response_model=ScanInsightNotifyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Record a structured scan finding (engine → backend)",
    description=(
        "The autonomous scan agent posts a structured finding here so it lands "
        "in the mobile Insights feed. Validated strictly — a missing or "
        "out-of-enum field is rejected 422 with no partial row (BE-03)."
    ),
)
async def scan_insights_notify(
    body: ScanInsightNotifyRequest,
    # Serviço, não pessoa. Com `get_current_user` qualquer funcionário
    # autenticado podia forjar um insight em qualquer espaço do seu
    # cliente — o `space_id` vem no corpo e não era confrontado com nada.
    _service: User = Depends(require_service_principal),
    db: AsyncSession = Depends(get_db_session),
) -> ScanInsightNotifyResponse:
    finding = await record_scan_finding(db, body)
    await db.commit()
    # ``is_live`` is derived at read time (BE-02); a freshly-recorded scan
    # finding is, by definition, live.
    return ScanInsightNotifyResponse(
        id=str(finding.id),
        source=finding.source,
        type=finding.type,
        severity=finding.severity,
        is_live=True,
    )


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
    crew_id: Optional[str] = Query(
        None,
        description="Active crew ID. When provided, the AI suggestions are scoped to that crew (collaborative mode).",
    ),
    language: Optional[str] = Query(None, description="Optional language hint (e.g. en, pt, es)"),
    max_suggestions: int = Query(4, ge=1, le=8),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatBootstrapResponse:
    """
    Returns greeting + suggestion cards for a new chat session.

    Current behavior:
    - Only enabled when the active page is in Personal mode (page.type == 'personal').
    - Uses the first active DataConnection for the user (Option A).
    """
    try:
        # 1) Mode hint (Personal mode is a client-side toggle today).
        # We don't hard-block here because the frontend is the source of truth for the
        # current "work mode" and we still need to return suggestions even if the
        # active page in DB isn't synced yet.
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        is_personal = getattr(active_page, "type", None) == "personal"

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
                    "active_page_type": getattr(active_page, "type", None),
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
                    "active_page_type": getattr(active_page, "type", None),
                },
            )

        # 4) Resolve crew_ids for this user in this space
        #    Collaborative mode: restrict to active crew_id if provided and user is a member
        if crew_id:
            all_user_crew_ids = await ai_service._get_user_crew_ids(  # noqa: SLF001
                current_user.id, resolved_space_id
            )
            if crew_id in all_user_crew_ids:
                crew_ids = [crew_id]
            else:
                logger.warning(
                    f"[chat_bootstrap] User {current_user.id} not member of crew {crew_id}, "
                    "falling back to all crews"
                )
                crew_ids = all_user_crew_ids
        else:
            crew_ids = await ai_service._get_user_crew_ids(  # noqa: SLF001
                current_user.id, resolved_space_id
            )

        # 5) Mandatory Permission Filtering: Get authorized tables
        permission_service = ai_service.permission_service
        try:
            from uuid import UUID

            authorized_tables = await permission_service.get_authorized_tables(
                user_id=current_user.id,
                connection_id=UUID(connection_id),
                space_id=UUID(resolved_space_id) if resolved_space_id else None,
                crew_ids=[UUID(cid) for cid in crew_ids] if crew_ids else None,
            )
        except Exception as e:
            logger.error(f"[chat_bootstrap] Error checking authorized tables: {e}", exc_info=True)
            authorized_tables = []  # Fail closed

        # 6) Call AI Engine
        client = AIServiceHTTPClient()
        payload = await client.chat_bootstrap(
            connection_id=connection_id,
            user_id=str(current_user.id),
            space_id=resolved_space_id,
            crew_ids=crew_ids if crew_ids else None,
            language=language,
            max_suggestions=max_suggestions,
            is_personal=is_personal,
            authorized_tables=list(authorized_tables),
        )

        # 7) Return as schema (enforce non-null keys if AI service is flaky)
        if not payload or not isinstance(payload, dict):
            logger.warning(f"[chat_bootstrap] AI service returned invalid payload: {payload}")
            return ChatBootstrapResponse(
                greeting=get_message("how_can_i_help", language),
                suggestions=[
                    {
                        "title": "Available data",
                        "kind": "question",
                        "question": "What data do I have access to?",
                    },
                    {
                        "title": "Examples",
                        "kind": "question",
                        "question": "Give me examples of questions I can ask.",
                    },
                ][:max_suggestions],
                meta={"enabled": True, "reason": "AI_SERVICE_EMPTY_PAYLOAD"},
            )

        # Ensure required fields are present even if payload is a dict
        if "greeting" not in payload:
            payload["greeting"] = get_message("how_can_i_help", language)
        if "suggestions" not in payload or not payload["suggestions"]:
            payload["suggestions"] = [
                {
                    "title": "Available data",
                    "kind": "question",
                    "question": "What data do I have access to?",
                },
                {
                    "title": "Examples",
                    "kind": "question",
                    "question": "Give me examples of questions I can ask.",
                },
            ][:max_suggestions]

        out = ChatBootstrapResponse.model_validate(payload)
        out.meta = {
            **(out.meta or {}),
            "active_page_type": getattr(active_page, "type", None),
        }
        return out
    except Exception as e:
        return ChatBootstrapResponse(
            greeting=get_message("how_can_i_help_data", language),
            suggestions=[
                {
                    "title": "Create dashboard",
                    "kind": "action",
                    "action_id": "create_dashboard",
                },
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
    dependencies=[Depends(depth_guard_dependency)],
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
    # Resolve and validate page_id
    if not message_data.page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        message_data.page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(message_data.page_id, current_user.id)

    # AI Customization fallback: if the client didn't pass tone/style/locale in
    # the request, pull them from the user's saved preferences (Settings → AI
    # Customization). Request-level values always win over saved defaults.
    prefs = current_user.preferences or {}
    if message_data.ai_tone is None:
        message_data.ai_tone = prefs.get("ai_tone")
    if message_data.ai_style is None:
        message_data.ai_style = prefs.get("ai_style")
    if message_data.locale is None:
        message_data.locale = prefs.get("language", "pt")

    ai_service = AIService(db)
    response = await ai_service.send_chat_message(current_user.id, message_data)
    # Pricing Fase 1 — counter bump on success only.
    try:
        await pricing_service.record_query_usage(db)
    except Exception:  # pragma: no cover — accounting failure is non-fatal
        logger.exception("pricing_record_query_usage_failed")
    return response


@router.post(
    "/chat/upload",
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
    summary="Upload a document to attach to a chat message",
)
async def upload_chat_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a document, extract its text, and return a ``file_id``.

    The client passes that id back on the next chat message as
    ``context.file_id`` (see ``/chat/stream``), and the extracted text is
    injected as grounding so Sky can answer about the document. Only the
    text is kept — we don't persist the raw bytes.
    """
    import uuid as _uuid

    from src.models.file import FileUpload
    from src.services.file_extract import extract_text

    data = await file.read()
    max_bytes = 10 * 1024 * 1024  # 10 MB
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")

    text = extract_text(file.filename, file.content_type, data)
    fid = _uuid.uuid4()
    row = FileUpload(
        id=fid,
        user_id=current_user.id,
        filename=file.filename or "upload",
        original_name=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        size=len(data),
        url=f"inline://chat/{fid}",  # text-only; no blob stored
        storage="inline",
        parsed_data={"text": text, "chars": len(text)},
    )
    db.add(row)
    await db.commit()
    return {
        "file_id": str(fid),
        "filename": row.original_name,
        "chars": len(text),
        "extracted": bool(text),
    }


@router.post(
    "/chat/stream",
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Send chat message (SSE streaming)",
    dependencies=[Depends(depth_guard_dependency)],
    description=(
        "Same contract as POST /chat but streams the AI response back as "
        "Server-Sent Events. Each event is a `data: {...}` line with a "
        "`type` field, locked to: 'progress', 'chunk', 'meta', 'error', "
        "'done' (see src/schemas/chat_stream.py — the single source of "
        "truth). Any other engine-internal event is dropped, and idle "
        "connections get a periodic ': keepalive' comment. Lets the UI "
        "render tokens as they arrive — first-visible-content typically "
        "2-3 seconds vs. ~8-30s end-to-end."
    ),
)
async def send_chat_message_stream(
    message_data: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Stream chat response via SSE.

    Resolution rules mirror POST /chat: page_id, tone/style fallback,
    and the same scope-to-connection resolution the non-streaming path
    uses. The difference is the response is forwarded from the AI
    service's streaming endpoint (stream_query_connection) line-by-line
    instead of waiting for the final JSON.
    """
    # Page resolution — same as /chat.
    if not message_data.page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        message_data.page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(message_data.page_id, current_user.id)

    # Tone/style/locale fallback — same as /chat.
    prefs = current_user.preferences or {}
    if message_data.ai_tone is None:
        message_data.ai_tone = prefs.get("ai_tone")
    if message_data.ai_style is None:
        message_data.ai_style = prefs.get("ai_style")
    if message_data.locale is None:
        message_data.locale = prefs.get("language", "pt")

    # Resolve scope inline. We can't reuse AIService.send_chat_message
    # because it persists and returns a single blob; streaming needs us
    # to flush events as they arrive. Connection resolution uses the
    # same fallbacks as the non-streaming path: explicit field → first
    # active connection for the user.
    ai_service = AIService(db)
    resolved_connection_id: Optional[str] = None
    resolved_all_connection_ids: List[str] = []
    try:
        if getattr(message_data, "space_id", None):
            resolved_all_connection_ids = await ai_service._get_all_connections_for_space(
                current_user.id, str(message_data.space_id)
            )
        elif getattr(message_data, "is_personal", False):
            # Personal mode: use user_datasets connections so the AI sees all
            # demo tables and can do cross-DB joins — same logic as /ai/query.
            resolved_all_connection_ids = await ai_service._get_user_dataset_connection_ids(
                current_user.id
            )
        if resolved_all_connection_ids:
            resolved_connection_id = resolved_all_connection_ids[0]
        if not resolved_connection_id:
            resolved_connection_id = await ai_service._get_first_active_connection(current_user.id)
            if resolved_connection_id:
                resolved_all_connection_ids = [resolved_connection_id]
    except Exception as exc:
        logger.warning(f"Chat stream — connection resolution failed: {exc}")

    scope_is_personal = bool(getattr(message_data, "is_personal", False))
    scope_space_id = getattr(message_data, "space_id", None) or "default"

    # Resolve the caller's crew membership so the RAG restricts the
    # retrieval to their own crews (or crew_id IS NULL). Without this,
    # a Space member asking a question inside their own Crew page would
    # silently miss Crew-scoped embeddings because the AI defaults to
    # crew_ids=[] → crew_id IS NULL only. See collaborative RAG audit.
    resolved_crew_ids: List[str] = []
    if not scope_is_personal:
        explicit_crew_id = getattr(message_data, "crew_id", None)
        if explicit_crew_id:
            # Trust the page-level crew signal but intersect with the
            # user's actual membership so a compromised client can't
            # read a Crew they don't belong to.
            user_crews = await ai_service._get_user_crew_ids(current_user.id, str(scope_space_id))
            if str(explicit_crew_id) in user_crews:
                resolved_crew_ids = [str(explicit_crew_id)]
            # else: the client asked for a Crew the user doesn't belong
            # to — fall back to the space-wide view (no crew filter).
        else:
            resolved_crew_ids = await ai_service._get_user_crew_ids(
                current_user.id, str(scope_space_id)
            )

    import json as _json

    ai_client = AIServiceHTTPClient()

    # Load knowledge context (OKRs, strategies, table relationships) and merge
    # into instructions — same as process_query and send_chat_message do.
    stream_instructions = getattr(message_data, "instructions", None) or ""
    try:
        from src.services.knowledge_context_loader import (
            load_knowledge_context_for_user,
            render_knowledge_for_prompt,
        )

        _kc = await load_knowledge_context_for_user(db, current_user)
        _rendered = render_knowledge_for_prompt(_kc)
        if _rendered:
            stream_instructions = (
                f"{_rendered}\n\n{stream_instructions}" if stream_instructions else _rendered
            )
    except Exception as _kc_err:
        logger.debug("[chat/stream] knowledge_context_loader skipped: %s", _kc_err)

    # BE-08 (T-08.3) — "Ask Sky about this": when the client passes
    # context.insight_id, load that finding (scoped to the caller — out-of-scope
    # ids are ignored) and prepend it so the answer is grounded in the insight.
    _ctx = getattr(message_data, "context", None) or {}
    _insight_id = _ctx.get("insight_id") if isinstance(_ctx, dict) else None
    if _insight_id:
        try:
            from src.services.insight_feed_service import InsightFeedService

            _insight = await InsightFeedService(db).detail(current_user.id, str(_insight_id))
            if _insight is not None:
                _lead = (
                    f"The user is asking about this insight — "
                    f'"{_insight.title}": {_insight.summary}'
                )
                stream_instructions = (
                    f"{_lead}\n\n{stream_instructions}" if stream_instructions else _lead
                )
        except Exception as _ins_err:
            logger.debug("[chat/stream] insight context skipped: %s", _ins_err)

    # Attachment ("+") — when the client passes context.file_id, load the
    # extracted text (scoped to the caller so one user can't read another's
    # upload) and prepend it so the answer is grounded in the document.
    _file_id = _ctx.get("file_id") if isinstance(_ctx, dict) else None
    if _file_id:
        try:
            import uuid as _uuid

            from src.models.file import FileUpload

            _fu = await db.get(FileUpload, _uuid.UUID(str(_file_id)))
            if _fu is not None and _fu.user_id == current_user.id:
                _ftext = ((_fu.parsed_data or {}).get("text") or "").strip()
                if _ftext:
                    _flead = (
                        f'The user attached a document named "{_fu.original_name}". '
                        f'Use its contents to answer:\n"""\n{_ftext[:100000]}\n"""'
                    )
                    stream_instructions = (
                        f"{_flead}\n\n{stream_instructions}" if stream_instructions else _flead
                    )
        except Exception as _file_err:
            logger.debug("[chat/stream] file context skipped: %s", _file_err)

    # Multi-turn threading (mobile, opt-in). Resolve or create the conversation
    # up front so its id is stable; the turn's messages are saved once the
    # answer has fully streamed. Web callers set neither flag and skip all this.
    from datetime import datetime as _dt

    persist_turn = bool(message_data.persist or message_data.conversation_id)
    conv_repo = ConversationRepository(db)
    conv_id = None
    if persist_turn:
        if message_data.conversation_id:
            existing = await conv_repo.get_by_id(message_data.conversation_id)
            # Only append to a thread the caller owns; otherwise start fresh.
            if existing is not None and existing.created_by == current_user.id:
                conv_id = existing.id
        if conv_id is None:
            title = (message_data.message or "").strip()[:60] or "New chat"
            conv = await conv_repo.create(
                page_id=message_data.page_id, created_by=current_user.id, title=title
            )
            conv_id = conv.id
            await db.commit()

    async def event_stream():
        """Normalize AI-engine SSE events onto the locked mobile contract
        (src/schemas/chat_stream.py) and forward only those. The backend owns
        the single terminal 'done'; engine debug/unknown events are dropped so
        mobile never sees an event outside the documented contract."""
        started = False
        try:
            if not resolved_connection_id:
                yield sse(
                    error_event(
                        get_message("no_data_source", message_data.locale),
                        code="no_data_source",
                    )
                )
                return

            yield sse(progress_event("starting", get_message("thinking", message_data.locale)))
            started = True

            answer_parts: List[str] = []
            async for line in ai_client.stream_query_connection(
                connection_id=str(resolved_connection_id),
                question=message_data.message,
                user_id=str(current_user.id),
                space_id=str(scope_space_id),
                instructions=stream_instructions or None,
                is_personal=scope_is_personal,
                crew_ids=resolved_crew_ids or None,
                connection_ids=(
                    resolved_all_connection_ids if len(resolved_all_connection_ids) > 1 else None
                ),
                locale=message_data.locale,
            ):
                event = normalize_event(parse_sse_data_line(line))
                if event is not None:
                    if persist_turn and event.get("type") == "chunk":
                        answer_parts.append(event.get("content") or "")
                    yield sse(event)

            # Save the completed turn and hand the conversation id back so the
            # client threads its next message into the same conversation.
            if persist_turn and conv_id is not None:
                try:
                    msg_repo = MessageRepository(db)
                    await msg_repo.create(
                        conversation_id=conv_id,
                        role="user",
                        kind="question",
                        content=message_data.message,
                        user_id=current_user.id,
                    )
                    await msg_repo.create(
                        conversation_id=conv_id,
                        role="assistant",
                        kind="ai_response",
                        content="".join(answer_parts),
                    )
                    await conv_repo.update(conv_id, updated_at=_dt.utcnow())
                    await db.commit()
                except Exception as _perr:  # persistence must never break the stream
                    logger.warning("[chat/stream] persist failed: %s", _perr)
                yield sse(meta_event({"conversation_id": str(conv_id)}))

            yield sse(done_event())
        except Exception as exc:
            logger.error(f"Chat stream failed: {exc}", exc_info=True)
            if started:
                yield sse(error_event(str(exc)[:200], code="stream_failed"))
            else:
                yield sse(
                    error_event(
                        get_message("unable_to_start_stream", message_data.locale),
                        code="unable_to_start",
                    )
                )

    # Wrap with a heartbeat so idle mobile SSE connections aren't reaped.
    return StreamingResponse(with_heartbeat(event_stream()), media_type="text/event-stream")


@router.get(
    "/popular-questions",
    response_model=List[dict],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List popular AI questions (anonymised)",
    description=(
        "Returns the most-asked questions across the org over the last 30 days, "
        "grouped by normalised question text and ordered by count desc. No user "
        "attribution — used to seed the chat bootstrap suggestions with what "
        "other people in the same space have actually been asking."
    ),
)
async def get_popular_questions(
    limit: int = Query(5, ge=1, le=20),
    space_id: Optional[UUID] = Query(None, description="Restrict to a Space (optional)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[dict]:
    """List popular questions, anonymised. Each row: {question, count}."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from src.models.ai import AIQuery

    # Last 30 days, completed only — incomplete/error queries shouldn't drive
    # recommendations because we're inferring "this question worked".
    since = datetime.now(timezone.utc) - timedelta(days=30)
    # Normalise to lowercase trimmed text so "What is MRR?" and "what is mrr"
    # collapse into one bucket. We keep the original-cased question of the
    # most recent occurrence as the displayed string.
    norm = func.lower(func.trim(AIQuery.question))
    stmt = (
        select(
            norm.label("norm"),
            func.count().label("cnt"),
            func.max(AIQuery.question).label("display"),
        )
        .where(AIQuery.status == "completed")
        .where(AIQuery.created_at >= since)
        .where(AIQuery.user_id != current_user.id)  # exclude my own
        .group_by(norm)
        .order_by(func.count().desc())
        .limit(limit * 3)
    )
    rows = (await db.execute(stmt)).all()
    out: List[dict] = []
    for r in rows:
        q = (r.display or "").strip()
        if not q or len(q) < 8:
            continue
        # Filter out boring stuff that shouldn't be surfaced as a suggestion.
        if q.lower() in {"hi", "hello", "test", "what?"}:
            continue
        out.append({"question": q, "count": int(r.cnt)})
        if len(out) >= limit:
            break
    return out


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
    crew_id: Optional[str] = Query(
        None, description="Filter history by active crew (collaborative mode)"
    ),
    space_id: Optional[str] = Query(None, description="Filter history by space"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    page_id: Optional[UUID] = Query(None, description="Page ID for filtering"),
    is_personal: bool = Query(False, description="Whether to fetch personal history"),
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
    # Resolve and validate page_id
    resolved_page_id = page_id
    if crew_id:
        # Collaborative crew mode: page_id is optional.
        # History is scoped by crew_id, no page ownership check needed.
        # If page_id is provided alongside crew_id, use it as-is (no validation required).
        pass
    elif not resolved_page_id:
        # Personal mode with no page_id: resolve the active page
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        resolved_page_id = active_page.id
    else:
        # Personal mode with explicit page_id: validate ownership
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(resolved_page_id, current_user.id)

    ai_service = AIService(db)
    return await ai_service.get_history(
        current_user.id,
        page_id=resolved_page_id,
        filter_type=filter,
        search=search,
        category=category,
        skip=skip,
        limit=limit,
        crew_id=crew_id,
        space_id=space_id,
        is_personal=is_personal,
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
    # Resolve and validate page_id
    if not history_data.page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        history_data.page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(history_data.page_id, current_user.id)

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
    page_id: Optional[UUID] = Query(None, description="Page ID for isolation"),
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
    # Resolve and validate page_id
    resolved_page_id = page_id
    if not resolved_page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        resolved_page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(resolved_page_id, current_user.id)

    ai_service = AIService(db)
    return await ai_service.get_history_by_id(history_id, current_user.id, resolved_page_id)


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
    page_id: Optional[UUID] = Query(None, description="Page ID for isolation"),
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
    # Resolve and validate page_id
    resolved_page_id = page_id
    if not resolved_page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        resolved_page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(resolved_page_id, current_user.id)

    ai_service = AIService(db)
    await ai_service.delete_history(history_id, current_user.id, resolved_page_id)
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
    page_id: Optional[UUID] = Query(None, description="Page ID for isolation"),
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
    # Resolve and validate page_id
    resolved_page_id = page_id
    if not resolved_page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        resolved_page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(resolved_page_id, current_user.id)

    ai_service = AIService(db)
    return await ai_service.pin_history(history_id, current_user.id, resolved_page_id)


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
    page_id: Optional[UUID] = Query(None, description="Page ID for isolation"),
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
    # Resolve and validate page_id
    resolved_page_id = page_id
    if not resolved_page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        resolved_page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(resolved_page_id, current_user.id)

    ai_service = AIService(db)
    return await ai_service.unpin_history(history_id, current_user.id, resolved_page_id)


@router.get(
    "/history/export",
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Export history",
    description="Export history as CSV",
)
async def export_history(
    page_id: Optional[UUID] = Query(None, description="Page ID for isolation"),
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
    # Resolve and validate page_id
    resolved_page_id = page_id
    if not resolved_page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        resolved_page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(resolved_page_id, current_user.id)

    ai_service = AIService(db)
    csv_content = await ai_service.export_history(current_user.id, resolved_page_id)

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
    # Resolve and validate page_id
    if not request.page_id:
        page_repo = PageRepository(db)
        active_page = await page_repo.get_active_page(current_user.id)
        if not active_page:
            from src.core.exceptions import NotFoundError

            raise NotFoundError("No active page found for user")
        request.page_id = active_page.id
    else:
        from src.services.page_service import PageService

        page_service = PageService(db)
        await page_service.get_user_page_or_404(request.page_id, current_user.id)

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
    if request.locale is None:
        prefs = current_user.preferences or {}
        request.locale = prefs.get("language", DEFAULT_LOCALE)

    ai_service = AIService(db)
    return await ai_service.generate_sql(current_user.id, request)


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
    logger.info(
        f"Generating infographic for user {current_user.id}, question: {str(request.question)[:50]}..."
    )

    try:
        raw = await ai_service.generate_infographic(current_user.id, request)
        logger.info(f"AI service returned raw data type: {type(raw)}")

        # The AI service returns a plain dict; validate it into the typed schema.
        from src.schemas.ai import InfographicData

        if isinstance(raw, (dict, GenerateInfographicResponse)):
            # If it's already a response (fallback from AIService), use its data
            if hasattr(raw, "data") and isinstance(raw.data, InfographicData):
                infographic_data = raw.data
            elif isinstance(raw, dict):
                try:
                    infographic_data = InfographicData.model_validate(raw)
                    logger.info("Successfully validated infographic data")
                except Exception as val_err:
                    logger.error(f"Validation error for infographic data: {val_err}")
                    logger.debug(f"Raw data that failed validation: {raw}")
                    # Fallback to empty but with title
                    infographic_data = InfographicData()
            else:
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
                summary=f"Error: {str(e)}. Please check backend logs.",
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
    # Personal-mode parity with /query — see the rationale at the top of the
    # /query handler. Same key-selection logic.
    rbac = RBACService(db)
    space_uuid: Optional[UUID] = None
    if body.space_id:
        try:
            space_uuid = UUID(body.space_id)
        except Exception:
            space_uuid = None
    permission_key = "ai.query" if space_uuid is not None else "ai.query.personal"
    await rbac.assert_permission(current_user, permission_key, space_id=space_uuid)

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

    # Beats quota gate — fires AFTER rate limit so users near their
    # cap aren't charged when 429 would have rejected anyway.
    # suggest_title is 5 beats (single gpt-4o-mini call, much cheaper
    # than the L3 chat path).
    await BeatsService(db).check_and_record(
        current_user,
        kind="suggest_title",
        source_id=None,
    )

    client = AIServiceHTTPClient()
    suggested = await client.suggest_widget_title(
        question=body.question,
        data_sample=body.data_sample,
        answer=body.answer,
        current_title=body.current_title,
        language=body.language or "pt",
    )
    return SuggestWidgetTitleResponse(title=suggested)
