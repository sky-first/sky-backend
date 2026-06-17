"""Agent API endpoints — CRUD, pause/resume, findings, streaming execution."""

import asyncio
import json
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.api.deps import get_current_user, get_db
from src.core.locale import DEFAULT_LOCALE, get_message, normalize_locale
from src.models.agent import Agent, AgentExecution, AgentFinding
from src.models.user import User

logger = logging.getLogger(__name__)


def _extract_tables_from_sql(sql: str) -> List[str]:
    """Extract table names from a SQL query to guide the orchestrator's table selection.

    Returns both schema-qualified (schema.table) and bare (table) names so
    the orchestrator can match against either physical or logical table names.
    """
    if not sql:
        return []
    matches = re.findall(
        r"\b(?:FROM|JOIN)\s+((?:\w+\.)?\w+)",
        sql,
        re.IGNORECASE,
    )
    seen: dict = {}
    for m in matches:
        seen[m.lower()] = m.lower()
        # Also add the bare table name for schema-qualified refs (schema.table → table)
        bare = m.split(".")[-1].lower()
        if bare not in seen:
            seen[bare] = bare
    return list(seen.values())


from src.schemas.agent import (
    AddFindingToPageRequest,
    AddFindingToPageResponse,
    AgentCreate,
    AgentFindingResponse,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
)
from src.services import pricing_service
from src.services.agent_service import AgentService
from src.services.rbac_service import RBACService

router = APIRouter()


def _sanitize_json(obj: Any) -> Any:
    """Recursively convert Decimal/date/datetime to JSON-safe types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


async def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(db)


async def _assert_can_act_on_agent_scope(
    db: AsyncSession,
    user: User,
    *,
    scope: Optional[str],
    scope_id: Optional[str],
    permission: str,
) -> None:
    """RBAC for an agent action that may live in any scope.

    Personal agents are owned-by-creator: ``scope == "personal"`` and
    ``scope_id`` is the creator's user UUID. The Space-scoped permissions
    catalog doesn't apply to them — only the owner (and platform Owner /
    Admin) can act. This mirrors ``AgentService._require_can_mutate`` so
    the route-level gate doesn't 403 a user who would otherwise be
    allowed by the service-layer guard.

    For ``space`` (and crew/org via space_id resolution), the standard
    RBAC catalog applies — e.g. ``agents.create`` requires editor on the
    target Space.
    """
    scope_lower = (scope or "").lower()

    if scope_lower == "personal":
        platform = (user.role or "").lower()
        if platform in ("owner", "admin", "super_admin"):
            return
        try:
            owner_id = UUID(str(scope_id))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid personal-scope agent identity",
            )
        if owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Personal agents are owned by their creator",
            )
        return

    s_id: Optional[UUID] = None
    if scope_lower == "space" and scope_id:
        try:
            s_id = UUID(scope_id)
        except ValueError:
            pass
    await RBACService(db).assert_permission(user, permission, space_id=s_id)


async def _is_content_member(db: AsyncSession, user: User, scope, scope_id) -> bool:
    """Option B: is ``user`` a real member entitled to an agent's CONTENT
    (findings/insights)? No platform-role bypass. crew → crew membership;
    space → space or any-crew-in-space membership; personal → the creator.
    """
    sc = (scope or "").lower()
    if not scope_id:
        return sc == "personal"  # malformed scoped agent — treat as private
    from src.services.authorization import Authorization

    authz = Authorization(db)
    try:
        sid = UUID(str(scope_id))
    except (ValueError, TypeError):
        return False
    if sc == "crew":
        return await authz.get_crew_role(user.id, sid) is not None
    if sc == "space":
        if await authz.get_space_role(user.id, sid) is not None:
            return True
        return await authz.get_best_crew_role_in_space(user.id, sid) is not None
    # personal / organization — handled by the caller (creator check).
    return False


@router.get("/", response_model=List[AgentListResponse])
async def list_agents(
    scope: Optional[str] = Query(
        None, description="Filter by scope: personal, space, crew, organization"
    ),
    scope_id: Optional[str] = Query(None, description="Filter by scope entity ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """List agents. Filter by scope/scope_id or get all accessible agents."""
    # Scoped listings (scope=personal|space|crew|...) walk the unified
    # RBAC helper — personal is owner-by-creator, space goes through the
    # standard catalog. An unscoped listing is owner-or-admin only:
    # platform Owner/Admin see everything, Members get auto-narrowed to
    # their own personal agents below (so the unfiltered created_by=None
    # path doesn't leak).
    if scope:
        await _assert_can_act_on_agent_scope(
            db,
            current_user,
            scope=scope,
            scope_id=scope_id,
            permission="agents.view",
        )

    # SECURITY: when the caller doesn't pin a scope, default to their
    # own personal agents (created_by=current_user.id) instead of
    # returning every agent in the tenant. Previously the unfiltered
    # `created_by=None` path leaked cross-user personal agents
    # ("Monitor: AI Response..." etc. from other users) to anyone
    # with agents.view. Org admins/owners can still see the full
    # list — they bypass at assert_permission, so we keep the
    # unfiltered path for them. Scoped requests (space / crew) keep
    # the existing access-checked behaviour because the scope filter
    # itself constrains the visibility set.
    is_org_admin = (current_user.role or "").lower() in ("owner", "admin", "super_admin")
    if not scope and not is_org_admin:
        return await service.list_agents(scope=None, scope_id=None, created_by=current_user.id)
    return await service.list_agents(scope=scope, scope_id=scope_id, created_by=None)


@router.post("/", response_model=AgentListResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Create a new agent.

    Personal-scope agents are explicitly allowed: they are owned by
    their creator (scope_id == user.id) and walk the same FE wizard as
    Space agents. ``_assert_can_act_on_agent_scope`` enforces the
    "owner-or-platform-admin" rule for personal scope and the standard
    Space-RBAC for collaborative scopes.

    For personal scope, the route used to compare the posted scope_id
    to the caller's id and 403 on mismatch — but the FE wizard in modo
    PERSONAL frequently posts an empty / placeholder value, which
    blocked users from ever creating a personal agent. The route now
    short-circuits the RBAC check for personal scope (it implicitly
    targets the current user) and the service normalises scope_id
    back to user.id before the row is written.
    """
    scope_str = (
        data.scope.value if hasattr(data.scope, "value") else str(data.scope or "")
    ).lower()

    # Space→Crew security boundary (2026-06): agents are ALWAYS created at
    # the crew level, never on a bare space. A space-scoped agent would run
    # over the union of the space's crews' tables; the new model requires an
    # explicit crew so its data surface is the one the operator granted.
    # Personal / crew / organization scopes are still allowed. Gated by the
    # same flag as the query guard so FE + BE roll out together.
    from src.config.settings import settings as _crew_settings

    if _crew_settings.CREW_REQUIRED_FOR_QUERY and scope_str == "space":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Agents must be created at the crew level, not the space level. "
                "Select a crew — every space has a default 'General' crew."
            ),
        )

    if scope_str != "personal":
        if not data.scope_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"scope_id is required when scope={scope_str!r}",
            )
        await _assert_can_act_on_agent_scope(
            db,
            current_user,
            scope=data.scope,
            scope_id=data.scope_id,
            permission="agents.create",
        )

    # Demo guard: limit how many agents each user can create so token
    # consumption stays bounded. Platform owners/admins are exempt.
    from src.config.settings import settings as _settings

    _max = _settings.DEMO_MAX_AGENTS_PER_USER if _settings.DEMO_ENABLED else 0
    _role = (current_user.role or "").lower()
    if _max > 0 and _role not in ("owner", "admin", "super_admin"):
        _count_result = await db.execute(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.created_by == current_user.id,
            )
        )
        _count = _count_result.scalar() or 0
        if _count >= _max:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Agent limit reached. Demo accounts can have up to {_max} agents. "
                    "Delete an existing agent to create a new one."
                ),
            )

    # Pricing Fase 1 — tier enforcement. Raises TierLimitExceededError
    # (HTTP 402) BEFORE the agent row is created so we don't have to
    # clean up on the way out. The counter bump happens after the
    # service confirms the insert; if anything between here and the
    # bump fails, the row is gone (transaction rollback) and the
    # counter stays consistent.
    await pricing_service.check_can_create_agent(db)
    agent = await service.create_agent(data, user_id=current_user.id)
    await pricing_service.record_agent_created(db)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Get agent detail. Findings (content) are included only for members."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=agent.scope,
        scope_id=agent.scope_id,
        permission="agents.view",
    )
    # Option B (2026-06): findings are CONTENT. The scope check above lets a
    # platform admin SEE the agent (management plane), but its insights
    # require real membership — strip findings for non-members so an admin
    # who was not added to the crew sees the agent exists, not its insights.
    sc = (agent.scope or "").lower()
    if sc in ("personal", "organization"):
        is_member = agent.created_by == current_user.id
    else:
        is_member = await _is_content_member(db, current_user, agent.scope, agent.scope_id)
    if not is_member:
        agent.findings = []
        # Transient flag read by AgentResponse (from_attributes) so the UI can
        # show an "ask to be added" mask rather than an empty insights tab.
        agent.findings_restricted = True
    return agent


@router.put("/{agent_id}", response_model=AgentListResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Update agent configuration."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=agent.scope,
        scope_id=agent.scope_id,
        permission="agents.edit",
    )
    return await service.update_agent(agent_id, data, current_user)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Delete an agent and all its findings."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.delete",
    )
    await service.delete_agent(agent_id, current_user)
    return None


@router.post("/{agent_id}/pause", response_model=AgentListResponse)
async def pause_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Pause an active agent."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.pause",
    )
    return await service.pause_agent(agent_id)


@router.post("/{agent_id}/resume", response_model=AgentListResponse)
async def resume_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Resume a paused agent."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.resume",
    )
    return await service.resume_agent(agent_id)


@router.post("/{agent_id}/run")
async def run_agent_now(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate execution of the agent."""
    import logging

    from sqlalchemy import select

    from src.models.agent import Agent

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Agent not found")

    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.run",
    )

    try:
        from src.workers.agent_worker import execute_agent

        execute_agent.delay(str(agent_id))
    except Exception as e:
        logging.getLogger(__name__).warning(
            f"Could not enqueue agent task (Celery may not be running): {e}"
        )
    return {"message": "Agent execution started", "agent_id": str(agent_id)}


@router.post("/{agent_id}/run/stream")
async def run_agent_stream(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute an agent with SSE streaming — shows live progress as AI analyzes data.
    Returns Server-Sent Events with types: progress, datasets_selected, sql_generated, chunk, meta, done.
    """
    # RBAC: must have agents.run. The check was previously commented out
    # inside the docstring, so the endpoint was effectively public.
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.run",
    )

    if not agent.connection_ids:
        raise HTTPException(status_code=400, detail="Agent has no connections to analyze")

    # Create execution record
    execution = AgentExecution(agent_id=agent.id, status="running")
    db.add(execution)
    await db.flush()
    execution_id = execution.id
    await db.commit()

    ai_client = AIServiceHTTPClient()

    async def event_generator():
        """Stream SSE events from AI service, save findings on completion."""
        collected_answer = ""
        collected_meta = {}
        collected_rows: Optional[Dict[str, Any]] = None  # {columns, data, truncated?}
        all_conn_ids = [str(cid) for cid in (agent.connection_ids or [])]
        conn_id = all_conn_ids[0] if all_conn_ids else None

        # Phase 4.2: explicit handling of every monitor_type the schema
        # validator accepts. `scan` is the preferred name for autonomous
        # connection monitoring; `datasource` is a legacy alias. `context`
        # is reserved for Phase 5 full-context mode and currently behaves
        # like `scan` with an explicit label for audit logs.
        # Resolved up-front so the conn_id-fallback branch below can
        # reference it without tripping UnboundLocalError when the agent
        # has neither a pinned connection nor a context-mode flag.
        monitor_type = (agent.monitor_type or "question").lower()

        if not conn_id:
            # Fallback: resolve a connection based on the agent's scope.
            # Space-scoped agents must look up connections via the Space link
            # table — _get_first_active_connection only searches personal
            # connections owned by the user and misses shared Space connections,
            # returning None and producing a /connections/None/ 403 on the AI
            # service. Use _get_first_active_connection_for_space (which also
            # applies the colleague's keyword routing) for space/crew scopes.
            from src.services.ai_service import AIService

            _ai_svc = AIService(db)
            _scope = (agent.scope or "").lower()
            if _scope in ("space", "crew") and agent.scope_id:
                conn_id = await _ai_svc._get_first_active_connection_for_space(
                    current_user.id,
                    str(agent.scope_id),
                )
            else:
                conn_id = await _ai_svc._get_first_active_connection(current_user.id)

        if not conn_id and monitor_type != "context":
            _err_locale = normalize_locale(
                (current_user.preferences or {}).get("language", DEFAULT_LOCALE)
            )
            yield f"data: {json.dumps({'type': 'error', 'message': get_message('no_data_source_agent', _err_locale)})}\n\n"
            return

        # `focus` is the agent's objective/instructions, not a SQL question.
        # For autonomous scan modes, derive a concrete question the SQL pipeline
        # can act on and forward the focus as `instructions` so the AI applies
        # the user's specific intent when interpreting results.
        agent_instructions: Optional[str] = None
        sql_instructions: Optional[str] = None
        sql_table_hints: Optional[List[str]] = None

        if monitor_type == "question":
            # Direct question — focus IS the user's question.
            question = (
                agent.focus or "Analyze the data and surface insights, risks, and opportunities."
            )
        elif monitor_type == "sql":
            # The orchestrator gets a neutral analytical question so it can select
            # the right table. The specialist receives the user's exact SQL and must
            # execute it verbatim — only adding LIMIT if missing or replacing SELECT *
            # with explicit columns. It must NOT rewrite filters, add date ranges, or
            # otherwise deviate from the user's intent.
            question = "Analyze the key metrics and recent patterns in this dataset."
            agent_instructions = agent.focus or None
            if agent.custom_sql:
                sql_instructions = (
                    "⚠️ SQL MODE — USER-PROVIDED BASE QUERY:\n"
                    "Use the query below as the base. Apply ONLY these mandatory adaptations:\n"
                    "  1. Replace SELECT * with explicit column names from the schema shown above.\n"
                    "  2. Qualify bare table names with the schema prefix "
                    "(e.g., INVOICES → finance.invoices, invoices → finance.invoices).\n"
                    "  3. Add LIMIT 100 at the end if no LIMIT clause is present.\n"
                    "  4. Prefix with the required -- TITLE: comment.\n"
                    "DO NOT add date filters, change WHERE clauses, add JOINs, or rewrite any other logic.\n"
                    "NEVER return IMPOSSIBLE for SQL mode — always apply the adaptations and return SQL.\n"
                    "USER'S BASE QUERY:\n\n"
                    f"{agent.custom_sql}"
                )
                # Extract the table names from the user's SQL so the orchestrator
                # is guided to the same tables the SQL references. Without this
                # the generic question above causes the orchestrator to pick
                # unrelated tables and the specialist ignores the SQL template.
                sql_table_hints = _extract_tables_from_sql(agent.custom_sql)
        elif monitor_type in ("scan", "datasource"):
            # Ask a concrete analytical question so the orchestrator can pick
            # a specific table and generate SQL — not a structural "all tables"
            # command which the LLM table-selector can't parse into a choice.
            question = (
                "What are the most recent records and key aggregate metrics in this dataset? "
                "Highlight any notable changes, outliers, or patterns compared to typical values."
            )
            agent_instructions = agent.focus or None
        elif monitor_type == "context":
            question = (
                "What are the latest trends and key metrics in the available data? "
                "Show record counts, recent activity, and flag any anomalies or significant changes."
            )
            agent_instructions = agent.focus or None
            # Force the specialist to use a single SELECT with scalar subqueries —
            # one COUNT(*) per table. This avoids cross-schema JOINs that have no
            # FK path and always returns exactly 1 row regardless of data volume.
            # Scalar subqueries are a plain SELECT so they pass all validator rules.
            sql_instructions = (
                "Generate a single SELECT statement that returns exactly one row "
                "with the record count of every available table as a separate column. "
                "Use scalar subqueries, one per table. Example pattern:\n"
                "SELECT\n"
                "  (SELECT COUNT(*) FROM schema.table1) AS table1_count,\n"
                "  (SELECT COUNT(*) FROM schema.table2) AS table2_count,\n"
                "  ...\n"
                "Replace schema.tableN with the actual physical table names from the schema. "
                "Do NOT use UNION, JOIN, WHERE, or HAVING clauses. "
                "This must return exactly one row."
            )
        else:
            # Schema validator rejects unknown values before we get here,
            # but keep a graceful fallback so a stale row can still run.
            question = (
                f"You are an autonomous {agent.archetype or 'custom'} intelligence agent. "
                f"Analyze the data based on these instructions:\n\n"
                f"{agent.focus or 'Look for anomalies, trends, risks, and opportunities.'}"
            )

        if agent.last_answer:
            question += f'\n\nPrevious result: "{agent.last_answer[:500]}"\nHighlight any changes.'

        # Send initial progress. We emit two stage events back-to-back so
        # the UI moves immediately even if the AI service takes a few
        # seconds to start streaming (the first AI cold-start can be
        # well over a minute on GPU instances). Without the second
        # nudge the spotlight sits on "Connecting…" with no signal that
        # anything is happening, which Lucas's QA flagged as a bug.
        yield f"data: {json.dumps({'type': 'progress', 'stage': 'starting', 'message': f'Connecting to {agent.name}...'})}\n\n"
        yield f"data: {json.dumps({'type': 'progress', 'stage': 'orchestrator', 'message': 'Reaching the AI service…'})}\n\n"

        # Forward the agent's full Universe-Intelligence selection to the
        # AI service so the RAG can filter to the pinned subset across
        # every entity kind (Business Rules incl. glossary, Events,
        # Relationships, Outputs). Empty dict / missing kinds = no filter.
        selected_ctx: Optional[Dict[str, List[str]]] = (
            getattr(agent, "selected_context", None) or None
        )
        is_personal = (agent.scope or "").lower() == "personal"

        # Resolve crew_ids so the RAG scopes the retrieval correctly.
        # - Personal agent: no crew filter (agent sees only user-scoped data)
        # - Crew agent: the agent IS the crew; pass [scope_id]
        # - Space agent: collaborative — use the member's own crews in
        #   that space so the agent sees space-wide + crew-scoped data
        #   the running user is authorised for.
        resolved_crew_ids: List[str] = []
        agent_scope = (agent.scope or "").lower()
        if agent_scope == "crew" and agent.scope_id:
            resolved_crew_ids = [str(agent.scope_id)]
        elif agent_scope == "space" and agent.scope_id:
            from src.services.ai_service import AIService as _AIService

            resolved_crew_ids = await _AIService(db)._get_user_crew_ids(
                current_user.id, str(agent.scope_id)
            )

        # Resolve the REAL owning space for the metadata lookup. The AI filters
        # table_metadata by space_id; sending the raw scope_id is wrong for crew
        # (scope_id is a crew id) and personal (scope_id is a user id), which
        # caused a false "No metadata found" 404. See resolve_metadata_space_id.
        from src.services.agent_service import resolve_metadata_space_id

        effective_space_id = await resolve_metadata_space_id(db, agent, conn_id)

        # ── Normal single-query path ───────────────────────────────────────────
        try:
            table_ids: Optional[List[str]] = [str(t) for t in (agent.table_ids or [])] or None

            # table_ids are stored as "connectionId::schema.tableName" from the frontend.
            # The orchestrator matches by logical/physical name only (e.g. "accounts"),
            # so strip the "connId::" prefix and the "schema." prefix.
            def _extract_table_name(tid: str) -> str:
                name = tid.split("::", 1)[-1] if "::" in tid else tid
                return name.rsplit(".", 1)[-1] if "." in name else name

            table_names: Optional[List[str]] = (
                [_extract_table_name(tid) for tid in table_ids] if table_ids else None
            ) or None
            effective_datasets = sql_table_hints or table_names
            _agent_locale = normalize_locale(
                (current_user.preferences or {}).get("language", DEFAULT_LOCALE)
            )
            async for line in ai_client.stream_query_connection(
                connection_id=conn_id,
                question=question,
                user_id=str(current_user.id),
                space_id=effective_space_id or agent.scope_id or "default",
                instructions=agent_instructions,
                is_personal=is_personal,
                selected_context=selected_ctx,
                crew_ids=resolved_crew_ids or None,
                agent_mode=monitor_type,
                connection_ids=all_conn_ids if len(all_conn_ids) > 1 else None,
                selected_datasets=effective_datasets,
                sql_instructions=sql_instructions,
                locale=_agent_locale,
            ):
                # Forward SSE lines — they come as "data: {...}" from AI service
                if line.startswith("data: "):
                    raw = line[6:]
                    try:
                        event = json.loads(raw)
                        event_type = event.get("type", "")

                        if event_type == "chunk":
                            collected_answer += event.get("content", "")

                        if event_type == "meta":
                            collected_meta = event.get("meta") or {}

                        # Tabular data emitted by the AI after the SQL
                        # step (or the datasource scan). Capture a copy
                        # so we can persist it on the finding row; the
                        # event itself is still forwarded to the UI so
                        # the Cockpit can update the live preview.
                        if event_type == "rows":
                            raw_cols = event.get("columns")
                            raw_data = event.get("rows")
                            if isinstance(raw_cols, list) and isinstance(raw_data, list):
                                # Defensive: drop rows whose arity doesn't
                                # match columns. Matches the frontend
                                # unpackRows guard.
                                clean_data = [
                                    r
                                    for r in raw_data
                                    if isinstance(r, list) and len(r) == len(raw_cols)
                                ]
                                collected_rows = {
                                    "columns": raw_cols,
                                    "data": clean_data[:200],  # R6: hard cap
                                    "truncated": bool(event.get("truncated"))
                                    or len(clean_data) > 200,
                                }

                        # Suppress the AI service's own "done" — the backend
                        # emits its own after the finding is persisted, which
                        # is the only "done" the frontend should act on.
                        if event_type == "done":
                            continue

                        # Forward to frontend
                        yield f"data: {raw}\n\n"

                    except json.JSONDecodeError:
                        yield f"data: {raw}\n\n"
                elif line.strip():
                    yield f"{line}\n\n"

        except (Exception, asyncio.CancelledError) as e:
            logger.error(f"Agent stream failed for {agent_id}: {e}")
            if not isinstance(e, asyncio.CancelledError):
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        # Save finding — always create one row, even when the AI produced
        # no content, so the user sees a concrete result in the halo /
        # findings tab instead of a silent "Run" that looks like nothing
        # happened. The old behaviour only saved when collected_answer
        # was non-empty, which is exactly when run_agent feedback matters
        # least.
        saved_finding_id: Optional[UUID] = None
        try:
            from src.config.database import AsyncSessionLocal

            async with AsyncSessionLocal() as save_db:
                has_answer = bool(collected_answer and collected_answer.strip())
                # Finding type is always a member of the FindingType enum
                # ("insight", "opportunity", "risk"). A run that produced no
                # content is still an observation about the agent's state —
                # persist it as a low-severity "insight" with confidence=0
                # and a title that reads as "no output". Previously we stored
                # "error" here, which is NOT in FindingType, and that made
                # GET /agents/ explode during response serialization
                # (ResponseValidationError, 500 on the whole list).
                finding = AgentFinding(
                    agent_id=agent.id,
                    execution_id=execution_id,
                    type="insight",
                    severity="medium" if has_answer else "low",
                    title=(
                        (collected_meta.get("title") or f"Analysis from {agent.name}")[:500]
                        if has_answer
                        else f"Run produced no output ({agent.name})"[:500]
                    ),
                    description=(
                        collected_answer[:3000]
                        if has_answer
                        else "The AI service returned no content for this run. Check the agent's focus prompt, data sources, or retry."
                    ),
                    confidence=0.75 if has_answer else 0.0,
                    query=question[:500],
                    connection_id=UUID(conn_id) if conn_id else None,
                    data_sources=[s for s in [collected_meta.get("chosen_table"), conn_id] if s],
                    rows=_sanitize_json(collected_rows),
                )
                save_db.add(finding)
                await save_db.flush()
                saved_finding_id = finding.id

                # Update execution
                exec_result = await save_db.execute(
                    select(AgentExecution).where(AgentExecution.id == execution_id)
                )
                exec_obj = exec_result.scalar_one_or_none()
                if exec_obj:
                    exec_obj.status = "completed" if has_answer else "failed"
                    exec_obj.findings_count = 1
                    exec_obj.cycles_consumed = 3 if has_answer else 1
                    exec_obj.finished_at = datetime.now(timezone.utc)

                # Update agent stats
                agent_result = await save_db.execute(select(Agent).where(Agent.id == agent_id))
                agent_obj = agent_result.scalar_one_or_none()
                if agent_obj:
                    agent_obj.last_execution_at = datetime.now(timezone.utc)
                    agent_obj.executions_this_month += 1
                    agent_obj.cycles_consumed += 3 if has_answer else 1

                await save_db.commit()

            payload = {
                "type": "finding_saved",
                "finding_id": str(saved_finding_id) if saved_finding_id else None,
                "title": collected_meta.get("title", "Analysis complete"),
                "has_answer": bool(collected_answer),
            }
            try:
                yield f"data: {json.dumps(payload)}\n\n"
            except (GeneratorExit, asyncio.CancelledError):
                pass
        except (Exception, asyncio.CancelledError) as e:
            logger.exception("Failed to save agent finding")
            try:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Could not persist finding: {e}'})}\n\n"
            except (GeneratorExit, asyncio.CancelledError):
                pass

        try:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Findings ───


@router.get("/insights/all", response_model=List[AgentFindingResponse])
async def list_all_insights(
    scope: Optional[str] = Query(None),
    scope_id: Optional[str] = Query(None),
    include_dismissed: bool = Query(False),
    limit: int = Query(50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all insights across all agents, optionally filtered by scope.

    SECURITY (audit 2026-05-05): without a scope filter the previous
    implementation returned findings from every Agent in the tenant
    to any caller with global ``agents.findings.view``. Now: when the
    caller is not an org admin/owner AND no explicit scope is pinned,
    we restrict the agent list to ones they own or are members of.
    """
    await RBACService(db).assert_permission(current_user, "agents.findings.view")
    from sqlalchemy.orm import selectinload

    query = select(Agent)
    if scope:
        query = query.where(Agent.scope == scope)
    if scope_id:
        query = query.where(Agent.scope_id == scope_id)

    # Option B (2026-06): agent findings are CONTENT — even org admins only
    # see findings from agents they own or whose Space/Crew they belong to
    # (no platform-role bypass). A crew member sees their crew-agents'
    # findings; a non-member admin sees a count via the agents list but NOT
    # the insights here.
    from sqlalchemy import and_, or_

    from src.models.crew import CrewMember
    from src.models.space import SpaceMember

    member_space_ids = [
        str(sid)
        for sid in (
            await db.execute(
                select(SpaceMember.space_id).where(SpaceMember.user_id == current_user.id)
            )
        ).scalars().all()
    ]
    member_crew_ids = [
        str(cid)
        for cid in (
            await db.execute(
                select(CrewMember.crew_id).where(CrewMember.user_id == current_user.id)
            )
        ).scalars().all()
    ]
    clauses = [Agent.created_by == current_user.id]
    if member_space_ids:
        clauses.append(and_(Agent.scope == "space", Agent.scope_id.in_(member_space_ids)))
    if member_crew_ids:
        clauses.append(and_(Agent.scope == "crew", Agent.scope_id.in_(member_crew_ids)))
    query = query.where(or_(*clauses))

    result = await db.execute(query.options(selectinload(Agent.findings)))
    agents = result.scalars().all()

    all_findings: list = []
    for agent in agents:
        for f in agent.findings or []:
            if not include_dismissed and f.dismissed:
                continue
            all_findings.append(f)

    all_findings.sort(key=lambda f: f.created_at or "", reverse=True)
    return all_findings[:limit]


@router.get("/{agent_id}/findings", response_model=List[AgentFindingResponse])
async def list_findings(
    agent_id: UUID,
    include_dismissed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """List findings for an agent."""
    await RBACService(db).assert_permission(current_user, "agents.findings.view")
    # Content gate (Option B): a crew/space-scoped agent's findings require
    # membership of that crew/space — no platform-role bypass. Personal
    # agents: only the creator.
    agent_row = (
        await db.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent_row is not None:
        scope_str = (agent_row.scope or "").lower()
        scope_id_val = agent_row.scope_id
        if scope_str == "crew" and scope_id_val:
            from src.services.authorization import Authorization

            await Authorization(db).assert_content_access(
                current_user, crew_id=UUID(str(scope_id_val))
            )
        elif scope_str == "space" and scope_id_val:
            from src.services.authorization import Authorization

            await Authorization(db).assert_content_access(
                current_user, space_id=UUID(str(scope_id_val))
            )
        elif scope_str == "personal" and agent_row.created_by != current_user.id:
            from src.core.exceptions import ForbiddenError

            raise ForbiddenError("You cannot view this agent's findings.")
    return await service.list_findings(agent_id, include_dismissed=include_dismissed)


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-agent usage metrics.

    Two flavours of volume surface here:

    * `runs_*` and `data_bytes_*` — human-readable units shown to end
      users in the agent card. "This agent ran 12 times and analyzed
      8 MB of data this month."
    * `tokens_*` — technical LLM units, used only by admin-level
      billing screens and the customer invoice. Included in the
      response so the same endpoint powers both views, but the
      end-user UI never surfaces it.

    SECURITY (audit 2026-05-05): the previous implementation gated on
    a global ``agents.view`` check, never verifying the caller could
    actually access THIS specific agent. Resolve the agent first and
    pass its space scope into the RBAC check so the existing
    list-agents IDOR fix (which scopes to ``created_by`` for non-admins)
    is enforced here too.
    """
    agent_q_pre = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent_pre = agent_q_pre.scalar_one_or_none()
    if not agent_pre:
        raise HTTPException(status_code=404, detail="Agent not found")
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent_pre, "scope", None),
        scope_id=getattr(agent_pre, "scope_id", None),
        permission="agents.view",
    )
    # Belt-and-suspenders: the helper already enforces owner-or-admin
    # for personal agents (matching ``scope_id`` against the caller),
    # but the legacy ``created_by`` IDOR guard stays as a second layer
    # in case a personal agent ever lands with a stale ``scope_id``.
    is_org_admin = (current_user.role or "").lower() in ("owner", "admin", "super_admin")
    if (
        agent_pre.scope == "personal"
        and not is_org_admin
        and agent_pre.created_by != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Not allowed for this agent")
    import json
    from datetime import datetime, timezone

    from src.models.agent import AgentExecution

    exec_q = await db.execute(select(AgentExecution).where(AgentExecution.agent_id == agent_id))
    executions = list(exec_q.scalars().all())

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _month(e: AgentExecution) -> bool:
        started = getattr(e, "started_at", None) or getattr(e, "created_at", None)
        return bool(started and started >= month_start)

    def _tokens(e: AgentExecution) -> int:
        return int(e.llm_tokens_used or 0) + int(e.delta_tokens or 0)

    def _data_bytes(e: AgentExecution) -> int:
        """Size of the query result the execution analyzed. We use the
        JSONB result_payload byte length as the proxy: it captures both
        rows read and any intermediate aggregation the agent touched."""
        payload = getattr(e, "result_payload", None)
        if payload is None:
            return 0
        try:
            return len(json.dumps(payload, default=str))
        except Exception:
            return 0

    runs_total = len(executions)
    runs_this_month = sum(1 for e in executions if _month(e))
    tokens_total = sum(_tokens(e) for e in executions)
    tokens_this_month = sum(_tokens(e) for e in executions if _month(e))
    data_bytes_total = sum(_data_bytes(e) for e in executions)
    data_bytes_this_month = sum(_data_bytes(e) for e in executions if _month(e))
    findings_total = sum(int(e.findings_count or 0) for e in executions)
    findings_this_month = sum(int(e.findings_count or 0) for e in executions if _month(e))
    durations = [e.duration_ms for e in executions if e.duration_ms]
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else None
    last_execution = next(
        (
            e
            for e in sorted(
                executions,
                key=lambda x: (
                    getattr(x, "started_at", None)
                    or getattr(x, "created_at", None)
                    or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )
        ),
        None,
    )

    agent_q = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_q.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "agent_id": str(agent_id),
        "runs_total": runs_total,
        "runs_this_month": runs_this_month,
        "data_bytes_total": data_bytes_total,
        "data_bytes_this_month": data_bytes_this_month,
        "avg_data_bytes_per_run": int(data_bytes_total / runs_total) if runs_total else 0,
        "findings_total": findings_total,
        "findings_this_month": findings_this_month,
        "avg_duration_ms": avg_duration_ms,
        "last_run_at": (
            (
                getattr(last_execution, "started_at", None)
                or getattr(last_execution, "created_at", None)
            )
            if last_execution
            else None
        ),
        "next_run_at": agent.next_execution_at,
        "connection_count": len(agent.connection_ids or []),
        "table_count": len(agent.table_ids or []),
        # Billing-only fields. End-user UI must NOT surface these; they
        # are aggregated by the tenant admin dashboard and printed on
        # the customer invoice.
        "tokens_total": tokens_total,
        "tokens_this_month": tokens_this_month,
        "avg_tokens_per_run": int(tokens_total / runs_total) if runs_total else 0,
    }


@router.get("/metrics/summary")
async def get_tenant_agent_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-level roll-up for Settings → Usage & Metrics.

    Aggregates runs and tokens across every agent the user can see so
    admins can show customers a single "you used X runs / Y tokens this
    month" number per billing cycle.

    SECURITY (audit 2026-05-05): the previous implementation served the
    SAME numbers to every caller with ``metrics.view``, so a regular
    member with ``metrics.view`` saw billing-grade aggregates spanning
    agents they could not otherwise read. We now scope the aggregation
    to agents the caller can access — same shape as ``list_agents``:
      • org admin / owner → entire tenant (existing behaviour)
      • everyone else → personal agents they own + space agents in
        their member spaces.
    """
    await RBACService(db).assert_permission(current_user, "metrics.view")
    from datetime import datetime, timezone

    from src.models.agent import AgentExecution

    is_org_admin = (current_user.role or "").lower() in ("owner", "admin", "super_admin")
    agent_query = select(Agent)
    if not is_org_admin:
        from sqlalchemy import and_, or_

        from src.models.space import SpaceMember

        member_q = await db.execute(
            select(SpaceMember.space_id).where(SpaceMember.user_id == current_user.id)
        )
        member_space_ids = [str(sid) for sid in member_q.scalars().all()]
        clauses = [Agent.created_by == current_user.id]
        if member_space_ids:
            clauses.append(
                and_(
                    Agent.scope == "space",
                    Agent.scope_id.in_(member_space_ids),
                )
            )
        agent_query = agent_query.where(or_(*clauses))

    all_agents = await db.execute(agent_query)
    agents = list(all_agents.scalars().all())

    visible_agent_ids = [a.id for a in agents]
    if visible_agent_ids:
        execs_q = await db.execute(
            select(AgentExecution).where(AgentExecution.agent_id.in_(visible_agent_ids))
        )
        executions = list(execs_q.scalars().all())
    else:
        executions = []

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _month(e: AgentExecution) -> bool:
        started = getattr(e, "started_at", None) or getattr(e, "created_at", None)
        return bool(started and started >= month_start)

    def _tokens(e: AgentExecution) -> int:
        return int(e.llm_tokens_used or 0) + int(e.delta_tokens or 0)

    import json

    def _data_bytes(e: AgentExecution) -> int:
        payload = getattr(e, "result_payload", None)
        if payload is None:
            return 0
        try:
            return len(json.dumps(payload, default=str))
        except Exception:
            return 0

    return {
        "agents_total": len(agents),
        "agents_active": sum(1 for a in agents if a.status == "active"),
        "runs_this_month": sum(1 for e in executions if _month(e)),
        "runs_total": len(executions),
        "data_bytes_this_month": sum(_data_bytes(e) for e in executions if _month(e)),
        "data_bytes_total": sum(_data_bytes(e) for e in executions),
        "findings_this_month": sum(int(e.findings_count or 0) for e in executions if _month(e)),
        "findings_total": sum(int(e.findings_count or 0) for e in executions),
        # Billing-only — admin invoice / backend cost projection.
        "tokens_this_month": sum(_tokens(e) for e in executions if _month(e)),
        "tokens_total": sum(_tokens(e) for e in executions),
    }


@router.post("/{agent_id}/findings/{finding_id}/dismiss", response_model=AgentFindingResponse)
async def dismiss_finding(
    agent_id: UUID,
    finding_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Dismiss a finding."""
    await RBACService(db).assert_permission(current_user, "agents.findings.dismiss")
    return await service.dismiss_finding(finding_id)


@router.post(
    "/{agent_id}/findings/{finding_id}/add-to-page",
    response_model=AddFindingToPageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_finding_to_page(
    agent_id: UUID,
    finding_id: UUID,
    payload: AddFindingToPageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Materialise an agent finding as a Widget on the target page.

    Before this endpoint existed the FE "Add to page" CTA fell back to
    the generic POST /widgets endpoint with type='text', so charts and
    KPIs were lost — only the description ended up on the page. This
    endpoint reads the finding's viz_kind + rows and builds a typed
    Widget (chart / kpi / table / insight) so the canvas renders the
    same visualisation the user saw in the Cockpit. The agent's first
    connection is propagated so the widget can refresh later.
    """
    # Permission: the caller must be allowed to act on the agent (so a
    # crew/space agent can be added to a page by any member) and must
    # be the page owner / member. We reuse the existing helpers rather
    # than open-coding ACL here.
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.findings.view",
    )

    result = await service.add_finding_to_page(
        agent_id=agent_id,
        finding_id=finding_id,
        page_id=payload.page_id,
        user=current_user,
        position=payload.position,
        size=payload.size,
    )
    return AddFindingToPageResponse(**result)
