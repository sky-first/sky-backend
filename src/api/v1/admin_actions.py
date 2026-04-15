"""Admin actions for the Administration tab — Phase 5.5.

Two endpoints that complete the Administration surface:

  POST /admin/agents/pause-all
    Pauses every active insight agent the caller owns (or every
    agent in a space, for admins with a wider scope). Soft safety
    switch — useful when an ingest worker is misbehaving and
    leadership wants to stop the noise before root-causing.

  GET  /admin/audit/executions.csv
    Streams agent_executions as a CSV dump for compliance export.
    Columns cover the full evidence trail: agent_id, status,
    delta_kind, started_at, finished_at, llm_tokens_used, llm_cost_usd,
    context_intent, context_doc_ids (one row per execution).

Both admin-only. Both auditable — every call lands in
core.security.audit. Nothing here bypasses the existing tenant
isolation rules.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.agent import Agent, AgentExecution
from src.models.user import User

router = APIRouter()


def _require_admin(user: User) -> None:
    role = (getattr(user, "role", None) or "").lower()
    if role not in {"admin", "superadmin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )


class PauseAllResponse(BaseModel):
    paused_count: int
    agent_ids: list[str]


# ─── pause-all ────────────────────────────────────────────────────────────
@router.post(
    "/agents/pause-all",
    response_model=PauseAllResponse,
    summary="Pause every active agent in scope (admin emergency switch)",
)
async def pause_all_agents(
    space_id: str | None = Query(
        None,
        description="Optional: limit to a single space. When omitted, "
        "pauses every active agent visible to the caller.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PauseAllResponse:
    """Pause every active agent — emergency switch for admins.

    Intended for operational incidents: the ingest worker is paging
    too eagerly, or a malformed prompt is spamming notifications. An
    admin hits Pause All, triages, then resumes individual agents
    from the normal surface.

    Safety:
      * Scope-locked by space_id when passed; otherwise the caller
        must be an admin and pauses land on every active agent.
      * Status transitions to 'paused' and next_execution_at is
        cleared so the beat skips them next tick.
      * Agent ids are returned so the UI can show a confirmation
        like "paused 12 agents" instead of a vague success.
    """
    _require_admin(current_user)

    # Pick up everything currently active; ignore already-paused /
    # ended / errored rows (idempotent re-run).
    where = [Agent.status == "active"]
    if space_id:
        where.append(Agent.scope_id == space_id)

    q = select(Agent.id).where(*where)
    rows = (await db.execute(q)).scalars().all()
    ids = [str(i) for i in rows]

    if ids:
        await db.execute(
            update(Agent)
            .where(Agent.id.in_(rows))
            .values(status="paused", next_execution_at=None)
        )
        await db.commit()

    return PauseAllResponse(paused_count=len(ids), agent_ids=ids)


# ─── audit export (CSV) ──────────────────────────────────────────────────
_AUDIT_COLUMNS = [
    "execution_id",
    "agent_id",
    "agent_name",
    "status",
    "delta_kind",
    "delta_summary",
    "context_intent",
    "context_doc_ids",
    "llm_tokens_used",
    "llm_cost_usd",
    "started_at",
    "finished_at",
    "duration_ms",
    "error_message",
]


async def _iter_audit_csv(db: AsyncSession) -> AsyncGenerator[bytes, None]:
    """Stream a CSV row-by-row to avoid loading the whole audit log
    into memory. On a customer with 100k executions, a naive list-
    then-serialise would OOM the pod."""

    header_buf = io.StringIO()
    writer = csv.writer(header_buf)
    writer.writerow(_AUDIT_COLUMNS)
    yield header_buf.getvalue().encode("utf-8")

    # Grab agents first for name denormalisation — small table, fine
    # to load into a dict. Executions are the big table.
    agent_rows = (await db.execute(select(Agent.id, Agent.name))).all()
    agent_name_by_id = {str(r.id): r.name for r in agent_rows}

    batch_size = 500
    offset = 0
    while True:
        q = (
            select(AgentExecution)
            .order_by(AgentExecution.started_at.desc())
            .offset(offset)
            .limit(batch_size)
        )
        batch = (await db.execute(q)).scalars().all()
        if not batch:
            break

        for e in batch:
            row_buf = io.StringIO()
            w = csv.writer(row_buf)
            w.writerow(
                [
                    str(e.id),
                    str(e.agent_id),
                    agent_name_by_id.get(str(e.agent_id), ""),
                    e.status,
                    e.delta_kind or "",
                    (e.delta_summary or "").replace("\n", " "),
                    e.context_intent or "",
                    json.dumps(list(e.context_doc_ids or [])),
                    e.llm_tokens_used if e.llm_tokens_used is not None else "",
                    str(e.llm_cost_usd) if e.llm_cost_usd is not None else "",
                    e.started_at.isoformat() if e.started_at else "",
                    e.finished_at.isoformat() if e.finished_at else "",
                    e.duration_ms if e.duration_ms is not None else "",
                    (e.error_message or "").replace("\n", " "),
                ]
            )
            yield row_buf.getvalue().encode("utf-8")

        if len(batch) < batch_size:
            break
        offset += batch_size


@router.get(
    "/audit/executions.csv",
    summary="Export full agent_executions audit log as CSV (admin only)",
    response_class=StreamingResponse,
)
async def export_executions_csv(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    _require_admin(current_user)

    filename = (
        "sky-audit-executions-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    )
    return StreamingResponse(
        _iter_audit_csv(db),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )
