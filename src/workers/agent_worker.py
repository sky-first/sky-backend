"""Agent worker — Celery tasks for executing AI agents on schedule."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

DEPTH_CYCLES = {"quick": 1, "standard": 3, "deep": 5}
FREQUENCY_HOURS = {"hourly": 1, "daily": 24, "weekly": 168}

# After this many consecutive scheduled-run failures, the agent is auto-paused
# (status="paused"). Prevents a misconfigured / broken agent from burning LLM
# budget indefinitely. The owner can resume manually after fixing the cause.
MAX_CONSECUTIVE_FAILURES = 3

# Substrings that indicate the previous run produced no real answer — only
# an orchestrator error. We skip prepending these to the next prompt and
# never store them as `last_answer`, otherwise the next scheduled tick asks
# the LLM to "compare with the previous error" and the loop never resolves.
_ORCHESTRATOR_ERROR_MARKERS = (
    "Error consulting the AI orchestrator",
    "Agentic Loop",
    "Recursion limit",
    "Please try again later",
)


def _looks_like_orchestrator_error(text: str | None) -> bool:
    if not text:
        return False
    return any(marker in text for marker in _ORCHESTRATOR_ERROR_MARKERS)


def _run_async(coro):
    """Helper to run async code from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _execute_agent_async(agent_id: str):
    """
    Core agent execution logic:
    1. Load agent config from DB
    2. For each connection, call AI service with agent's focus instructions
    3. Parse response into findings (insight/opportunity/risk)
    4. Store findings in DB
    5. Update agent execution stats
    6. Schedule next execution
    """
    from src.config.database import AsyncSessionLocal  # noqa: E402
    from src.models.agent import Agent, AgentExecution, AgentFinding
    from src.ai.http_client import AIServiceHTTPClient

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        # 1. Load agent
        result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        agent = result.scalar_one_or_none()
        if not agent:
            logger.error(f"Agent {agent_id} not found")
            return

        if agent.status != "active":
            logger.info(f"Agent {agent_id} is {agent.status}, skipping")
            return

        # 2. Create execution record
        execution = AgentExecution(
            agent_id=agent.id,
            status="running",
        )
        db.add(execution)
        await db.flush()

        depth = agent.depth or "standard"
        cycles = DEPTH_CYCLES.get(depth, 3)
        findings_created = 0
        ai_client = AIServiceHTTPClient()

        try:
            # 3. Build the question based on monitor_type
            monitor_type = getattr(agent, "monitor_type", "question") or "question"

            if monitor_type == "question":
                # Direct question — send the user's question as-is to the AI
                question = agent.focus or "Analyze the data and surface insights, risks, and opportunities."
            elif monitor_type == "sql":
                # Custom SQL — ask the AI to execute and interpret the SQL
                question = (
                    f"Execute this SQL query and analyze the results. "
                    f"Identify any anomalies, trends, or significant changes:\n\n"
                    f"```sql\n{agent.custom_sql or 'SELECT 1'}\n```"
                )
            else:
                # Datasource — scan mode with focus instructions
                question = (
                    f"You are an autonomous {agent.archetype or 'custom'} agent. "
                    f"Analyze the data and produce findings based on these instructions:\n\n"
                    f"{agent.focus or 'Look for anomalies, trends, risks, and opportunities.'}\n\n"
                    f"Respond with a structured analysis. For each finding, classify it as "
                    f"'insight', 'opportunity', or 'risk' with severity and confidence."
                )

            # Optional: add previous answer for comparison.
            # IMPORTANT: skip if previous run errored. Previously we naively
            # appended ANY last_answer, including agent-orchestrator errors
            # ("Error consulting the AI orchestrator (Agentic Loop)..."), so
            # the next scheduled run prepended the error string and asked the
            # LLM to "compare with the current data and highlight changes" —
            # which the orchestrator could not satisfy, retrying up to the
            # langgraph recursion limit each tick. With an hourly Pulse and 3
            # connections, that drained €15+ in 5 hours of OpenAI tokens.
            if (
                agent.last_answer
                and not _looks_like_orchestrator_error(agent.last_answer)
            ):
                question += (
                    f"\n\nIMPORTANT: In the previous analysis, the result was:\n"
                    f'"{agent.last_answer[:500]}"\n\n'
                    f"Compare with the current data and highlight any changes."
                )

            # 4. Query the AI service for each connection
            answer = ""
            sql_used = ""
            # Phase 6 — auditable_only mode filters out connections whose
            # tier is more sensitive than 'internal' before the agent
            # issues a query. We resolve tiers in one round-trip then
            # iterate the allowed subset.
            connection_ids = list(agent.connection_ids or [])
            if getattr(agent, "auditable_only", False) and connection_ids:
                from sqlalchemy import select
                from src.models.connection import DataConnection

                rows = (
                    await db.execute(
                        select(DataConnection.id, DataConnection.tier).where(
                            DataConnection.id.in_(connection_ids)
                        )
                    )
                ).all()
                allowed = {cid for cid, tier in rows if (tier or "internal") == "internal"}
                dropped = [str(c) for c in connection_ids if c not in allowed]
                if dropped:
                    logger.info(
                        f"Agent {agent_id}: auditable_only=true; "
                        f"dropped {len(dropped)} non-internal connection(s): {dropped}"
                    )
                connection_ids = [c for c in connection_ids if c in allowed]
            for conn_id in connection_ids:
                try:
                    # Pass table_ids as selected_datasets if specified
                    table_ids = getattr(agent, "table_ids", None)

                    response = await ai_client.query_connection(
                        connection_id=str(conn_id),
                        question=question,
                        user_id=str(agent.created_by) if agent.created_by else "system",
                        space_id=agent.scope_id or "default",
                        selected_datasets=table_ids if table_ids else None,
                    )

                    answer = response.get("answer", "") if isinstance(response, dict) else str(response)
                    sql_used = response.get("sql", "") if isinstance(response, dict) else ""

                    if answer:
                        finding = AgentFinding(
                            agent_id=agent.id,
                            execution_id=execution.id,
                            type="insight",
                            severity="medium",
                            title=(response.get("title", "") if isinstance(response, dict) else "") or f"Analysis from {agent.name}",
                            description=answer[:3000],
                            confidence=0.75,
                            query=question[:500],
                            connection_id=conn_id,
                            data_sources=table_ids or [str(conn_id)],
                        )
                        db.add(finding)
                        findings_created += 1

                except Exception as e:
                    logger.warning(f"Agent {agent_id}: failed to query connection {conn_id}: {e}")
                    continue

            # 5. Update execution with answer for comparison
            execution.status = "completed"
            execution.cycles_consumed = cycles
            execution.findings_count = findings_created
            execution.answer = answer[:3000] if answer else None
            execution.sql_executed = sql_used[:2000] if sql_used else None
            execution.finished_at = datetime.now(timezone.utc)

            # 6. Update agent stats + store last answer for next comparison.
            # Do NOT store orchestrator-error strings as last_answer. If we did,
            # the next scheduled run would prepend "previous result was 'Error
            # consulting the AI orchestrator'" and ask the LLM to compare with
            # current data — which it can't, so it loops to the recursion
            # limit, burning more tokens. Better to leave last_answer alone
            # and treat the next run as a fresh attempt.
            agent.last_execution_at = datetime.now(timezone.utc)
            answer_is_real = bool(answer) and not _looks_like_orchestrator_error(answer)
            if answer_is_real:
                agent.last_answer = answer[:2000]
                agent.consecutive_failures = 0
            else:
                # Bump the failure counter; pause the agent if it's been
                # failing repeatedly so it stops eating LLM budget.
                agent.consecutive_failures = (agent.consecutive_failures or 0) + 1
                if agent.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    agent.status = "paused"
                    agent.next_execution_at = None
                    logger.warning(
                        f"Agent {agent_id} auto-paused after "
                        f"{agent.consecutive_failures} consecutive failures"
                    )
            agent.executions_this_month += 1
            agent.cycles_consumed += cycles

            # Schedule next execution (skip if we just auto-paused above)
            if agent.status == "active":
                hours = FREQUENCY_HOURS.get(agent.frequency, 24)
                agent.next_execution_at = datetime.now(timezone.utc) + timedelta(hours=hours)

            await db.commit()

            # 7. Notify the agent creator about new findings
            if findings_created > 0 and agent.created_by:
                try:
                    from src.schemas.notification import NotificationCreate
                    from src.services.notification_service import NotificationService

                    notif_svc = NotificationService(db)
                    title = (
                        f"{agent.name} found {findings_created} new insight{'s' if findings_created > 1 else ''}"
                    )
                    await notif_svc.create(
                        NotificationCreate(
                            user_id=agent.created_by,
                            type="agent_finding",
                            title=title,
                            description=answer[:200] if answer else None,
                            entity_type="agent",
                            entity_id=str(agent.id),
                            # Route was renamed from sky-studio to
                            # universe-intelligence during the Phase-2
                            # UI refresh. The old path 404s; fixing
                            # here so existing notifications stop
                            # dead-ending users.
                            deep_link=f"/dashboard/universe-intelligence?agent={agent.id}",
                        )
                    )
                except Exception as notif_err:
                    logger.warning(f"Agent {agent_id}: notification failed (non-fatal): {notif_err}")

            logger.info(
                f"Agent {agent_id} executed successfully: "
                f"{findings_created} findings, {cycles} cycles consumed"
            )

        except Exception as e:
            execution.status = "failed"
            execution.error_message = str(e)[:1000]
            execution.finished_at = datetime.now(timezone.utc)
            agent.status = "error"
            await db.commit()
            logger.error(f"Agent {agent_id} execution failed: {e}")
            raise


@celery_app.task(bind=True, max_retries=2)
def execute_agent(self, agent_id: str):
    """Execute a single agent — called by scheduler or on-demand."""
    try:
        logger.info(f"Starting agent execution: {agent_id}")
        _run_async(_execute_agent_async(agent_id))
        return {"status": "success", "agent_id": agent_id}
    except Exception as exc:
        logger.error(f"Agent execution failed for {agent_id}: {exc}")
        raise self.retry(exc=exc, countdown=120)


@celery_app.task
def schedule_agents():
    """
    Periodic task — checks all active agents and enqueues those due for execution.
    Runs every 5 minutes via Celery Beat.
    """
    async def _check():
        from src.config.database import AsyncSessionLocal  # noqa: E402
        from src.models.agent import Agent
        from sqlalchemy import select

        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            # Insight-mode agents are scheduled by insight_agent_worker
            # via the new AgentRunService state machine; the legacy
            # scheduler only handles question/datasource/sql modes here
            # so the two flows don't double-enqueue.
            result = await db.execute(
                select(Agent).where(
                    Agent.status == "active",
                    Agent.next_execution_at <= now,
                    Agent.monitor_type != "insight",
                )
            )
            due_agents = result.scalars().all()

            for agent in due_agents:
                logger.info(f"Scheduling agent {agent.id} ({agent.name}) for execution")
                execute_agent.delay(str(agent.id))

            return len(due_agents)

    count = _run_async(_check())
    logger.info(f"Agent scheduler: {count} agents enqueued for execution")
    return {"agents_scheduled": count}
