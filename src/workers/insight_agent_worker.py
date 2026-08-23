"""Celery beat + worker for insight-mode agents.

Two tasks:

  schedule_insight_agents  — runs every minute; picks agents with
                             monitor_type='insight' AND status='active'
                             AND next_execution_at <= now, calls
                             AgentRunService.enqueue for each.

  execute_insight_run      — worker task, processes one queued
                             agent_execution. Claims it → calls the AI
                             service (mocked in Phase 1) → reports
                             success / failure back through
                             AgentRunService.

The AI service call is intentionally indirected through
`_call_ai_run_agent(...)` so Phase 2 (when HMAC-signed real calls land)
only has to replace that function — the queue → claim → report flow
stays stable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import AsyncSessionLocal
from src.core.exceptions import NotFoundError
from src.models.agent import Agent, AgentExecution
from src.models.notification import NotificationType
from src.schemas.notification import NotificationCreate
from src.services.agent_run_service import AgentRunService
from src.services.notification_service import NotificationService
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _latest_finding_id(db: AsyncSession, run_id: UUID) -> Optional[str]:
    """O achado mais recente desta execução, ou None se ela não produziu nenhum.

    É o que o cliente móvel precisa para abrir o insight: o feed é indexado por
    ``AgentFinding.id``. Uma execução sem achados (nada mudou) devolve None, e
    aí a notificação fica a apontar à própria execução, que é o mais honesto —
    não há insight nenhum para abrir.
    """
    from src.models.agent import AgentFinding

    result = await db.execute(
        select(AgentFinding.id)
        .where(AgentFinding.execution_id == run_id)
        .order_by(AgentFinding.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return str(row) if row else None


async def _emit_insight_notifications(
    db: AsyncSession,
    *,
    agent: Agent,
    run_id: UUID,
    delta_kind: Optional[str],
    delta_summary: Optional[str],
) -> None:
    """Emit up to two notifications per successful insight run.

    * INSIGHT_AGENT_RESULT — every completed run. Users mute this
      category when they only want material-delta pings.
    * INSIGHT_AGENT_MATERIAL — delta_kind == 'material' only. This is
      the "you should actually look at this" signal; kept distinct
      from RESULT so users can mute one without losing the other.

    Target user is `agent.created_by`. Both notifications carry a
    deep_link that opens the insight widget on the dashboard; the UI
    consumer resolves `entity_id` to the widget.
    """
    owner_id = agent.created_by
    if owner_id is None:
        # SP-owned agents have no human to ping here (audit record is
        # enough). If we need to fan out to crew admins later this is
        # the place to resolve them.
        return

    service = NotificationService(db)
    widget_id = str(agent.widget_id) if agent.widget_id else ""

    # O destino do alerta.
    #
    # `/dashboard?insight=<widget_id>` foi escrito para o dashboard web, onde o
    # que se abre é o widget. Na app móvel o feed de insights é indexado pelo id
    # do ACHADO (AgentFinding.id), não pelo do widget — tocar no alerta dava
    # "não foi possível carregar o insight" e o utilizador ficava sem perceber
    # porquê. Manda-se o achado desta execução no `entity_id`, e o deep_link do
    # widget fica como está para não partir a web.
    finding_id = await _latest_finding_id(db, run_id)
    deep_link = f"/dashboard?insight={widget_id}" if widget_id else None

    result_title = f"{agent.name or 'Insight agent'} — run completed"
    description = (delta_summary or "").strip() or None

    # Feed-level notification — muted by default for power users.
    await service.create_notification(
        NotificationCreate(
            user_id=owner_id,
            type=NotificationType.INSIGHT_AGENT_RESULT.value,
            title=result_title,
            description=description,
            entity_type="agent_finding" if finding_id else "agent_execution",
            entity_id=finding_id or str(run_id),
            deep_link=deep_link,
        )
    )

    if (delta_kind or "").lower() == "material":
        material_title = f"{agent.name or 'Insight agent'} — material change"
        await service.create_notification(
            NotificationCreate(
                user_id=owner_id,
                type=NotificationType.INSIGHT_AGENT_MATERIAL.value,
                title=material_title,
                description=description,
                entity_type="agent_finding" if finding_id else "agent_execution",
                entity_id=finding_id or str(run_id),
                deep_link=deep_link,
            )
        )


# ─── Helpers ──────────────────────────────────────────────────────────────

def _run_async(coro):
    """Corre codigo assincrono a partir de uma tarefa sincrona do Celery.

    Delega no `laco_do_celery.correr`. A versao anterior REUTILIZAVA o laco
    do processo quando ele ainda estava aberto — o que evitava por acaso o
    defeito das ligacoes presas, mas guardava estado entre tarefas, que e a
    mesma familia de problema com outra cara. Agora e um laco por tarefa e as
    ligacoes sao devolvidas ao sair, como nos outros dois workers.
    """
    from src.workers.laco_do_celery import correr

    return correr(coro)


async def _call_ai_run_agent(
    agent: Agent, run: AgentExecution, db: AsyncSession
) -> Dict[str, Any]:
    """Re-run the widget's original query against its data source.

    Loads the linked widget and its source AIQuery, calls the AI service,
    computes a SHA-256 content hash for delta detection, and writes the
    new result back to widget.data so the dashboard reflects fresh data.
    The session commit is deferred to the caller (report_success / report_skip)
    so the widget update and the execution record land in the same transaction.
    """
    import hashlib
    import json

    from sqlalchemy import select as _select

    from src.ai.http_client import AIServiceHTTPClient
    from src.models.ai import AIQuery
    from src.models.widget import Widget

    # ── 1. Load widget ────────────────────────────────────────────────
    if not agent.widget_id:
        raise ValueError(f"Insight agent {agent.id} has no widget_id")

    widget = (
        await db.execute(_select(Widget).where(Widget.id == agent.widget_id))
    ).scalar_one_or_none()
    if widget is None:
        raise ValueError(f"Widget {agent.widget_id} not found (agent {agent.id})")
    if not widget.connection_id:
        raise ValueError(
            f"Widget {widget.id} has no connection_id — cannot re-run query"
        )

    # ── 2. Resolve question ───────────────────────────────────────────
    # Prefer the exact question the user asked when the widget was created
    # (stored on the source AIQuery). Fall back to the widget title, then
    # to a generic scan prompt so the agent never silently no-ops.
    question: Optional[str] = None
    if widget.query_id:
        ai_query = (
            await db.execute(_select(AIQuery).where(AIQuery.id == widget.query_id))
        ).scalar_one_or_none()
        if ai_query:
            question = ai_query.question

    if not question:
        question = (
            widget.title
            or "What are the latest key metrics and patterns in this data?"
        )

    # ── 3. Call AI service ────────────────────────────────────────────
    ai_client = AIServiceHTTPClient()
    started = datetime.now(timezone.utc)

    from src.core.locale import resolve_locale
    from src.models.user import User as _User
    _owner = None
    if agent.created_by:
        _owner = (
            await db.execute(_select(_User).where(_User.id == agent.created_by))
        ).scalar_one_or_none()

    # Resolve the REAL owning space - sending the raw scope_id is wrong for crew
    # (crew id) and personal (user id) and causes a false "No metadata found"
    # 404. See resolve_metadata_space_id.
    from src.services.agent_service import resolve_metadata_space_id

    _effective_space_id = await resolve_metadata_space_id(
        db, agent, str(widget.connection_id)
    )
    response = await ai_client.query_connection(
        connection_id=str(widget.connection_id),
        question=question,
        user_id=str(agent.created_by) if agent.created_by else "system",
        space_id=_effective_space_id or agent.scope_id or "default",
        locale=resolve_locale(None, _owner),
    )

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    answer: str = (
        response.get("answer", "") if isinstance(response, dict) else str(response)
    )
    data_sample: list = (
        response.get("data_sample", []) if isinstance(response, dict) else []
    )

    # ── 4. Delta detection — SHA-256 content hash ─────────────────────
    canonical = json.dumps(data_sample, sort_keys=True, default=str)
    result_hash = hashlib.sha256(canonical.encode()).hexdigest()

    prev_hash = (
        await db.execute(
            _select(AgentExecution.result_hash)
            .where(
                AgentExecution.agent_id == agent.id,
                AgentExecution.id != run.id,
                AgentExecution.result_hash.is_not(None),
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if prev_hash is None:
        delta_kind = "first_run"
        delta_summary = None
    elif prev_hash == result_hash:
        delta_kind = "none"
        delta_summary = None
    else:
        delta_kind = "material"
        delta_summary = answer[:500] if answer else None

    # ── 5. Write new result back to the widget ────────────────────────
    # Only when the data actually changed — skip writes on delta_kind='none'
    # so we don't dirty the row on every no-op tick.
    # Each widget type expects a specific shape in widget.data; we format
    # accordingly so the frontend component renders the updated content.
    if delta_kind in ("first_run", "material") and answer:
        now_ts = datetime.now(timezone.utc)
        existing = widget.data or {}
        base = {**existing, "last_agent_run_at": now_ts.isoformat()}

        if widget.type == "insight":
            widget.data = {
                **base,
                "answer": answer,
                "text_block": {
                    **(existing.get("text_block") or {}),
                    "body": answer,
                },
            }
        elif widget.type == "infographic":
            try:
                infographic_resp = await ai_client.generate_infographic(
                    question=question,
                    answer=answer,
                    data_sample=data_sample[:15],
                )
                widget.data = {
                    **base,
                    "answer": answer,
                    "infographic_data": (
                        infographic_resp.get("infographic_data") or infographic_resp
                    ),
                }
            except Exception:
                logger.warning(
                    "generate_infographic failed for widget %s — answer-only update",
                    widget.id,
                )
                widget.data = {**base, "answer": answer}
        elif widget.type == "kpi":
            value = None
            if data_sample and isinstance(data_sample[0], dict):
                vals = list(data_sample[0].values())
                value = vals[0] if vals else None
            widget.data = {**base, "answer": answer, "value": value, "data": data_sample}
        elif widget.type == "chart":
            widget.data = {**base, "answer": answer, "data": data_sample}
        elif widget.type == "table":
            columns = (
                list(data_sample[0].keys())
                if data_sample and isinstance(data_sample[0], dict)
                else []
            )
            widget.data = {**base, "answer": answer, "columns": columns, "rows": data_sample}
        else:
            widget.data = {**base, "answer": answer, "data_sample": data_sample[:15]}

        widget.updated_at = now_ts

    return {
        "result_hash": result_hash,
        "result_payload": {"rows": data_sample[:100], "schema": []},
        "delta": {"kind": delta_kind, "summary": delta_summary},
        "tokens": {"in": 0, "out": 0},
        "cost_usd": 0.0,
        "duration_ms": elapsed_ms,
        "context": {"doc_ids": [], "intent": None},
    }


# ─── Beat: schedule due insight agents ────────────────────────────────────


@celery_app.task
def schedule_insight_agents() -> Dict[str, int]:
    """Enqueue every insight agent whose `next_execution_at` has passed."""

    async def _tick() -> int:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Agent).where(
                    Agent.monitor_type == "insight",
                    Agent.status == "active",
                    Agent.next_execution_at.is_not(None),
                    Agent.next_execution_at <= now,
                )
            )
            due = list(result.scalars().all())

            service = AgentRunService(db)
            enqueued = 0
            for agent in due:
                try:
                    run = await service.enqueue(agent.id)
                    execute_insight_run.delay(str(run.id))
                    enqueued += 1
                except Exception:
                    logger.exception(f"Failed to enqueue agent {agent.id}")
            return enqueued

    count = _run_async(_tick())
    logger.info(f"Insight agent scheduler: {count} runs enqueued")
    return {"enqueued": count}


# ─── Worker: process one queued run ───────────────────────────────────────


@celery_app.task(bind=True, max_retries=0)
def execute_insight_run(self, run_id: str) -> Dict[str, Any]:
    """Claim a queued agent_execution row, call the AI service, report.

    Failures are handled INSIDE the task (not by Celery retries): we want
    the state machine's exponential-backoff policy to be the single
    source of truth for retries. Celery's max_retries=0 keeps its own
    retry mechanism out of the way.
    """

    async def _process() -> Dict[str, Any]:
        run_uuid = UUID(run_id)
        async with AsyncSessionLocal() as db:
            service = AgentRunService(db)
            try:
                run = await service.claim(run_uuid)
            except NotFoundError:
                logger.warning(f"Run {run_id} disappeared before claim")
                return {"status": "missing"}

            agent = await service._require_agent(run.agent_id)
            try:
                response = await _call_ai_run_agent(agent, run, db)
            except Exception as err:
                logger.exception(
                    f"AI service call failed for run {run_id}: {err}"
                )
                await service.report_failure(
                    run_uuid, error_message=str(err)[:1000]
                )
                return {"status": "failed", "error": str(err)[:200]}

            delta_kind = (response.get("delta") or {}).get("kind")
            if delta_kind == "none":
                await service.report_skip(run_uuid)
                return {"status": "skipped"}

            ctx = response.get("context") or {}
            await service.report_success(
                run_uuid,
                result_hash=response.get("result_hash"),
                result_payload=response.get("result_payload"),
                delta_kind=delta_kind,
                delta_summary=(response.get("delta") or {}).get("summary"),
                context_doc_ids=ctx.get("doc_ids") or [],
                context_intent=ctx.get("intent"),
            )

            # Phase 3.3: notify the agent owner. Two levels:
            #   - INSIGHT_AGENT_MATERIAL on material deltas (user-facing
            #     "something changed you should look at").
            #   - INSIGHT_AGENT_RESULT for every completed run (feed
            #     entry — users usually mute this category but keep
            #     MATERIAL on).
            try:
                await _emit_insight_notifications(
                    db,
                    agent=agent,
                    run_id=run_uuid,
                    delta_kind=delta_kind,
                    delta_summary=(response.get("delta") or {}).get("summary"),
                )
            except Exception:
                # Notifications are side-effects; a failure here must
                # not roll back the successful run.
                logger.exception(
                    "notify_insight_run_failed run_id=%s agent_id=%s",
                    run_uuid, agent.id,
                )

            return {"status": "succeeded"}

    return _run_async(_process())
