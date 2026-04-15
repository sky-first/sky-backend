"""Agent worker — Celery tasks for executing AI agents on schedule."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

DEPTH_CYCLES = {"quick": 1, "standard": 3, "deep": 5}
FREQUENCY_HOURS = {"hourly": 1, "daily": 24, "weekly": 168}


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

            # Optional: add previous answer for comparison
            if agent.last_answer:
                question += (
                    f"\n\nIMPORTANT: In the previous analysis, the result was:\n"
                    f'"{agent.last_answer[:500]}"\n\n'
                    f"Compare with the current data and highlight any changes."
                )

            # 4. Query the AI service for each connection
            answer = ""
            sql_used = ""
            for conn_id in (agent.connection_ids or []):
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

            # 6. Update agent stats + store last answer for next comparison
            agent.last_execution_at = datetime.now(timezone.utc)
            agent.last_answer = answer[:2000] if answer else None
            agent.executions_this_month += 1
            agent.cycles_consumed += cycles

            # Schedule next execution
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
                            deep_link=f"/dashboard/sky-studio?agent={agent.id}",
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
