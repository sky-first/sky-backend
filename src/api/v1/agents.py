"""Agent API endpoints — CRUD, pause/resume, findings, streaming execution."""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
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
    service: AgentService = Depends(get_agent_service),
):
    """List agents. Filter by scope/scope_id or get all accessible agents."""
    await RBACService(db).assert_permission(current_user, "crews.create")
    return await service.list_agents(scope=scope, scope_id=scope_id, created_by=None)


@router.post("/", response_model=AgentListResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentCreate,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Create a new agent."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    return await service.create_agent(data, user_id=current_user.id)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Get agent detail with findings."""
    await RBACService(db).assert_permission(current_user, "crews.create")
    return await service.get_agent(agent_id)


@router.put("/{agent_id}", response_model=AgentListResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Update agent configuration."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    return await service.update_agent(agent_id, data)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Delete an agent and all its findings."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    await service.delete_agent(agent_id)
    return None


@router.post("/{agent_id}/pause", response_model=AgentListResponse)
async def pause_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Pause an active agent."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    return await service.pause_agent(agent_id)


@router.post("/{agent_id}/resume", response_model=AgentListResponse)
async def resume_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Resume a paused agent."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    return await service.resume_agent(agent_id)


@router.post("/{agent_id}/run")
async def run_agent_now(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate execution of the agent."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
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
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    Execute an agent with SSE streaming — shows live progress as AI analyzes data.
    Returns Server-Sent Events with types: progress, datasets_selected, sql_generated, chunk, meta, done.
    """
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
        conn_id = str(agent.connection_ids[0]) if agent.connection_ids else None

        if not conn_id:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No connections configured'})}\n\n"
            return

        monitor_type = agent.monitor_type or "question"
        if monitor_type == "question":
            question = agent.focus or "Analyze the data and surface insights, risks, and opportunities."
        elif monitor_type == "sql":
            question = f"Execute this SQL and analyze results:\n```sql\n{agent.custom_sql or 'SELECT 1'}\n```"
        else:
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

                        # Forward to frontend
                        yield f"data: {raw}\n\n"

                    except json.JSONDecodeError:
                        yield f"data: {raw}\n\n"
                elif line.strip():
                    yield f"{line}\n\n"

        except Exception as e:
            logger.error(f"Agent stream failed for {agent_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        # Save finding from collected answer
        try:
            from src.config.database import AsyncSessionLocal
            async with AsyncSessionLocal() as save_db:
                if collected_answer:
                    finding = AgentFinding(
                        agent_id=agent.id,
                        execution_id=execution_id,
                        type="insight",
                        severity="medium",
                        title=collected_meta.get("title", f"Analysis from {agent.name}")[:500],
                        description=collected_answer[:3000],
                        confidence=0.75,
                        query=question[:500],
                        connection_id=UUID(conn_id) if conn_id else None,
                        data_sources=[s for s in [collected_meta.get("chosen_table"), conn_id] if s],
                    )
                    save_db.add(finding)

                    # Update execution
                    exec_result = await save_db.execute(select(AgentExecution).where(AgentExecution.id == execution_id))
                    exec_obj = exec_result.scalar_one_or_none()
                    if exec_obj:
                        exec_obj.status = "completed"
                        exec_obj.findings_count = 1
                        exec_obj.cycles_consumed = 3
                        exec_obj.finished_at = datetime.now(timezone.utc)

                    # Update agent stats
                    agent_result = await save_db.execute(select(Agent).where(Agent.id == agent_id))
                    agent_obj = agent_result.scalar_one_or_none()
                    if agent_obj:
                        agent_obj.last_execution_at = datetime.now(timezone.utc)
                        agent_obj.executions_this_month += 1
                        agent_obj.cycles_consumed += 3

                    await save_db.commit()

            yield f"data: {json.dumps({'type': 'finding_saved', 'title': collected_meta.get('title', 'Analysis complete')})}\n\n"
        except Exception as e:
            logger.error(f"Failed to save agent finding: {e}")

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
    await RBACService(db).assert_permission(current_user, "crews.create")
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
    service: AgentService = Depends(get_agent_service),
):
    """List findings for an agent."""
    await RBACService(db).assert_permission(current_user, "crews.create")
    return await service.list_findings(agent_id, include_dismissed=include_dismissed)


@router.post("/{agent_id}/findings/{finding_id}/dismiss", response_model=AgentFindingResponse)
async def dismiss_finding(
    agent_id: UUID,
    finding_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """Dismiss a finding."""
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    return await service.dismiss_finding(finding_id)
