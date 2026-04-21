"""Agent API endpoints — CRUD, pause/resume, findings, streaming execution."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.api.deps import get_current_user, get_db
from src.models.agent import Agent, AgentExecution, AgentFinding
from src.models.user import User

logger = logging.getLogger(__name__)
from src.schemas.agent import (
    AgentCreate,
    AgentFindingResponse,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
)
from src.services.agent_service import AgentService
from src.services.rbac_service import RBACService

router = APIRouter()


async def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(db)


@router.get("/", response_model=List[AgentListResponse])
async def list_agents(
    scope: Optional[str] = Query(None, description="Filter by scope: personal, space, crew, organization"),
    scope_id: Optional[str] = Query(None, description="Filter by scope entity ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """List agents. Filter by scope/scope_id or get all accessible agents."""
    await RBACService(db).assert_permission(current_user, "agents.view")
    return await service.list_agents(scope=scope, scope_id=scope_id, created_by=None)


@router.post("/", response_model=AgentListResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Create a new agent."""
    await RBACService(db).assert_permission(current_user, "agents.create")
    return await service.create_agent(data, user_id=current_user.id)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Get agent detail with findings."""
    await RBACService(db).assert_permission(current_user, "agents.view")
    return await service.get_agent(agent_id)


@router.put("/{agent_id}", response_model=AgentListResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Update agent configuration."""
    await RBACService(db).assert_permission(current_user, "agents.edit")
    return await service.update_agent(agent_id, data)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Delete an agent and all its findings."""
    await RBACService(db).assert_permission(current_user, "agents.delete")
    await service.delete_agent(agent_id)
    return None


@router.post("/{agent_id}/pause", response_model=AgentListResponse)
async def pause_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Pause an active agent."""
    await RBACService(db).assert_permission(current_user, "agents.pause")
    return await service.pause_agent(agent_id)


@router.post("/{agent_id}/resume", response_model=AgentListResponse)
async def resume_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service),
):
    """Resume a paused agent."""
    await RBACService(db).assert_permission(current_user, "agents.resume")
    return await service.resume_agent(agent_id)


@router.post("/{agent_id}/run")
async def run_agent_now(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate execution of the agent."""
    await RBACService(db).assert_permission(current_user, "agents.run")
    import logging
    from sqlalchemy import select
    from src.models.agent import Agent

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        from src.workers.agent_worker import execute_agent
        execute_agent.delay(str(agent_id))
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not enqueue agent task (Celery may not be running): {e}")
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
    await RBACService(db).assert_permission(current_user, "agents.run")
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
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
        conn_id = str(agent.connection_ids[0]) if agent.connection_ids else None

        if not conn_id:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No connections configured'})}\n\n"
            return

        # Phase 4.2: explicit handling of every monitor_type the schema
        # validator accepts. `scan` is the preferred name for autonomous
        # connection monitoring; `datasource` is a legacy alias. `context`
        # is reserved for Phase 5 full-context mode and currently behaves
        # like `scan` with an explicit label for audit logs.
        monitor_type = (agent.monitor_type or "question").lower()
        if monitor_type == "question":
            question = agent.focus or "Analyze the data and surface insights, risks, and opportunities."
        elif monitor_type == "sql":
            question = f"Execute this SQL and analyze results:\n```sql\n{agent.custom_sql or 'SELECT 1'}\n```"
        elif monitor_type in ("scan", "datasource"):
            question = (
                f"You are an autonomous {agent.archetype or 'custom'} intelligence agent. "
                f"Scan the configured data sources for anomalies, trends, risks, and opportunities.\n\n"
                f"{agent.focus or ''}"
            ).strip()
        elif monitor_type == "context":
            question = (
                f"Full-context scan: traverse every available data source, "
                f"strategy artefact, and signal in scope and surface what "
                f"decision-makers should know.\n\n{agent.focus or ''}"
            ).strip()
        else:
            # Schema validator rejects unknown values before we get here,
            # but keep a graceful fallback so a stale row can still run.
            question = (
                f"You are an autonomous {agent.archetype or 'custom'} intelligence agent. "
                f"Analyze the data based on these instructions:\n\n"
                f"{agent.focus or 'Look for anomalies, trends, risks, and opportunities.'}"
            )

        if agent.last_answer:
            question += f"\n\nPrevious result: \"{agent.last_answer[:500]}\"\nHighlight any changes."

        # Send initial progress
        yield f"data: {json.dumps({'type': 'progress', 'stage': 'starting', 'message': f'Connecting to {agent.name}...'})}\n\n"

        try:
            async for line in ai_client.stream_query_connection(
                connection_id=conn_id,
                question=question,
                user_id=str(current_user.id),
                space_id=agent.scope_id or "default",
                instructions=agent.focus,
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
                            collected_meta = event.get("meta", {})

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
                                    r for r in raw_data
                                    if isinstance(r, list) and len(r) == len(raw_cols)
                                ]
                                collected_rows = {
                                    "columns": raw_cols,
                                    "data": clean_data[:200],  # R6: hard cap
                                    "truncated": bool(event.get("truncated")) or len(clean_data) > 200,
                                }

                        # Forward to frontend
                        yield f"data: {raw}\n\n"

                    except json.JSONDecodeError:
                        yield f"data: {raw}\n\n"
                elif line.strip():
                    yield f"{line}\n\n"

        except Exception as e:
            logger.error(f"Agent stream failed for {agent_id}: {e}")
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
                finding = AgentFinding(
                    agent_id=agent.id,
                    execution_id=execution_id,
                    type="insight" if has_answer else "error",
                    severity="medium" if has_answer else "low",
                    title=(
                        collected_meta.get("title", f"Analysis from {agent.name}")[:500]
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
                    rows=collected_rows,
                )
                save_db.add(finding)
                await save_db.flush()
                saved_finding_id = finding.id

                # Update execution
                exec_result = await save_db.execute(select(AgentExecution).where(AgentExecution.id == execution_id))
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
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.exception("Failed to save agent finding")
            yield f"data: {json.dumps({'type': 'error', 'message': f'Could not persist finding: {e}'})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

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
    """List all insights across all agents, optionally filtered by scope."""
    await RBACService(db).assert_permission(current_user, "agents.findings.view")
    from sqlalchemy.orm import selectinload

    query = select(Agent)
    if scope:
        query = query.where(Agent.scope == scope)
    if scope_id:
        query = query.where(Agent.scope_id == scope_id)

    result = await db.execute(query.options(selectinload(Agent.findings)))
    agents = result.scalars().all()

    all_findings: list = []
    for agent in agents:
        for f in (agent.findings or []):
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
    return await service.list_findings(agent_id, include_dismissed=include_dismissed)


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
