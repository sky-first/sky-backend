"""Agent worker — Celery tasks for executing AI agents on schedule."""

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _extract_tables_from_sql(sql: str) -> List[str]:
    """Extract table names from a SQL query to guide the orchestrator's table selection."""
    if not sql:
        return []
    matches = re.findall(r'\b(?:FROM|JOIN)\s+((?:\w+\.)?\w+)', sql, re.IGNORECASE)
    seen: dict = {}
    for m in matches:
        seen[m.lower()] = m.lower()
        bare = m.split(".")[-1].lower()
        if bare not in seen:
            seen[bare] = bare
    return list(seen.values())


DEPTH_CYCLES = {"quick": 1, "standard": 3, "deep": 5}
FREQUENCY_HOURS = {"hourly": 1, "daily": 24, "weekly": 168}

# After this many consecutive scheduled-run failures, the agent is auto-paused
# (status="paused"). Prevents a misconfigured / broken agent from burning LLM
# budget indefinitely. The owner can resume manually after fixing the cause.
MAX_CONSECUTIVE_FAILURES = 3

# Phase 3 tier-router — when L1 (delta check, no LLM) detects no change in
# the agent's data sources since the previous run, the worker short-circuits
# without calling the AI service. We still record the L1 cost (0.2 beats per
# connection) so the org-wide dashboard can show how often agents skipped
# vs. ran. L2 (gpt-4o-mini triage) and L3 (gpt-4o deep dive) costs are
# recorded around the existing AI call. The L2 step is a placeholder today
# and always escalates to L3 — the real triage prompt lands in a follow-up.

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


async def _connections_changed_since(db, connection_ids, since):
    """L1 delta-check helper. Returns True iff any of the listed connections
    had its row or its metadata refreshed after `since`. Uses timestamps
    the BE already maintains (DataConnection.updated_at and
    DataConnection.last_metadata_update), so the check is cheap (no
    source-system hit) and honest: if no sync ever happened, we have no
    signal of new data and skip the run.
    """
    if not connection_ids or since is None:
        # No prior run to compare against — let it run as L3 today, the
        # next tick will start short-circuiting once `last_execution_at`
        # is populated.
        return True

    from sqlalchemy import select
    from src.models.connection import DataConnection

    rows = (
        await db.execute(
            select(
                DataConnection.updated_at,
                DataConnection.last_metadata_update,
            ).where(DataConnection.id.in_(connection_ids))
        )
    ).all()

    for conn_updated, meta_updated in rows:
        latest = max(
            (t for t in (conn_updated, meta_updated) if t is not None),
            default=None,
        )
        if latest is not None and latest > since:
            return True
    return False


async def _record_beats_safely(db, user, *, kind: str, source_id=None):
    """Wrapper around BeatsService.record_only that swallows errors. The
    tier-router never wants beat-accounting failures to take an agent run
    down — the L3 call already happened (or will), the budget is
    advisory at this layer. Failures are logged and execution continues.
    """
    try:
        from src.services.beats_service import BeatsService

        await BeatsService(db).record_only(user, kind=kind, source_id=source_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Beats record_only(%s) failed: %s", kind, exc)


# Adaptive scheduling — agents that consistently produce zero findings
# get exponentially longer next-run intervals. Saves beats and noise on
# stale data sources without ever hard-pausing the agent. Cap is 7 days
# so even a long-quiet agent still ticks at least weekly. Reset to base
# cadence the moment any of the recent runs has a finding.
ADAPTIVE_BACKOFF_LOOKBACK = 20
ADAPTIVE_BACKOFF_THRESHOLD = 3   # need ≥3 empties in a row before backing off
ADAPTIVE_BACKOFF_MAX_HOURS = 24 * 7


async def _adaptive_interval_hours(db, agent_id, base_hours: int, current_findings: int) -> int:
    """Decide the next-run interval given the recent findings history.

    Streak = the leading run of zero-finding executions, counting the
    current run's `current_findings` as the most-recent entry. Below
    `ADAPTIVE_BACKOFF_THRESHOLD` we keep `base_hours`. Beyond it, each
    extra empty doubles the wait, capped at 7 days.
    """
    if base_hours <= 0:
        return base_hours

    from sqlalchemy import desc, select
    from src.models.agent import AgentExecution

    history = (
        await db.execute(
            select(AgentExecution.findings_count, AgentExecution.id)
            .where(AgentExecution.agent_id == agent_id)
            .order_by(desc(AgentExecution.started_at))
            .limit(ADAPTIVE_BACKOFF_LOOKBACK + 1)
        )
    ).all()
    # Drop any AgentExecution rows that match the run we just flushed —
    # the caller passes the *current* findings count separately so we
    # don't double-count if SQLAlchemy autoflush already persisted it.
    counts = [current_findings] + [c for c, _ in history if c is not None][1:]

    streak = 0
    for c in counts:
        if c == 0:
            streak += 1
        else:
            break

    if streak < ADAPTIVE_BACKOFF_THRESHOLD:
        return base_hours

    # streak == THRESHOLD → 2x; +1 → 4x; capped by MAX_HOURS.
    multiplier = 2 ** (streak - ADAPTIVE_BACKOFF_THRESHOLD + 1)
    return min(base_hours * multiplier, ADAPTIVE_BACKOFF_MAX_HOURS)


def _run_async(coro):
    """Helper to run async code from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Sprint 1.17 round 5 — viz_kind heuristics for new agent findings.
# Pure helper, no side effects. Inferred from response shape so every
# autonomous agent run carries an authoritative viz hint the Pulse FE
# can render without guessing.
import re as _re_viz


_PERCENT_DELTA_RE = _re_viz.compile(r"[+\-]?\s?\d+(?:\.\d+)?\s?%")
_NUMERIC_RE = _re_viz.compile(r"\d+(?:\.\d+)?")


def _normalize_rows(rows):
    if not rows:
        return None, None
    if isinstance(rows, dict) and "columns" in rows and "data" in rows:
        return rows.get("columns") or [], rows.get("data") or []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        cols = list(rows[0].keys())
        data = [[r.get(c) for c in cols] for r in rows]
        return cols, data
    return None, None


def _infer_viz_kind(response, answer: str) -> str:
    # The AI service returns the SQL result rows under `data_sample`
    # (a list of row dicts, capped at 15). Earlier code read `data`, a
    # key the AI QueryResponse never sets — so `rows` was always None and
    # every finding fell through to a text viz_kind ("callout"/"kpi")
    # regardless of the underlying data. Prefer `data_sample`; keep `data`
    # as a fallback for any caller that still uses the old shape.
    rows = None
    if isinstance(response, dict):
        rows = response.get("data_sample") or response.get("data")
    cols, data = _normalize_rows(rows)

    title = ""
    if isinstance(response, dict):
        title = response.get("title") or ""

    # Sprint 1.17 round 7 — emit only canonical viz_kinds the FE
    # registry knows about (bar / line / area / pie / scatter / kpi /
    # big_number / comparison_kpi / callout / bullet_list). Earlier
    # legacy strings ("delta", "sparkline", "text", "range") forced
    # the FE into a fallback layout, defeating the point of the hint.
    if _PERCENT_DELTA_RE.search(title) or _PERCENT_DELTA_RE.search(answer or ""):
        return "big_number"

    if cols and data:
        numeric_cols = sum(
            1
            for c_idx in range(len(cols))
            if any(
                isinstance(row[c_idx], (int, float))
                for row in data
                if len(row) > c_idx
            )
        )
        if numeric_cols == 1:
            label_col = next(
                (
                    c_idx
                    for c_idx in range(len(cols))
                    if any(
                        isinstance(row[c_idx], str)
                        for row in data
                        if len(row) > c_idx
                    )
                ),
                None,
            )
            if label_col is not None:
                distinct = {row[label_col] for row in data if len(row) > label_col}
                if 2 <= len(distinct) <= 8:
                    return "pie"
            return "line"
        if numeric_cols >= 2:
            return "bar"

    if answer and len(_NUMERIC_RE.findall(answer)) >= 1 and len(answer) < 240:
        return "kpi"

    return "callout"


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
            # `focus` is the agent's objective/instructions, not a SQL question.
            # For autonomous scan modes, use a concrete question the SQL pipeline
            # can act on and forward focus as `instructions` so the AI applies
            # the user's specific intent when interpreting results.
            monitor_type = getattr(agent, "monitor_type", "question") or "question"
            agent_instructions: Optional[str] = None
            sql_instructions: Optional[str] = None
            sql_table_hints: Optional[List[str]] = None

            if monitor_type == "question":
                # Direct question — focus IS the user's question.
                question = agent.focus or "Analyze the data and surface insights, risks, and opportunities."
            elif monitor_type == "sql":
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
                    sql_table_hints = _extract_tables_from_sql(agent.custom_sql)
            elif monitor_type in ("scan", "datasource"):
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
                question = (
                    f"You are an autonomous {agent.archetype or 'custom'} agent. "
                    f"Analyze the data and produce findings based on these instructions:\n\n"
                    f"{agent.focus or 'Look for anomalies, trends, risks, and opportunities.'}\n\n"
                    f"Respond with a structured analysis."
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

            # ── L1 — delta check ───────────────────────────────────────
            # If none of the agent's connections have been touched since
            # the previous successful run, skip the L2/L3 path entirely.
            # We still record the L1 cost (0.2 beats/connection) so the
            # tenant dashboard reflects the work the worker actually did.
            from src.models.user import User
            from sqlalchemy import select as _sqla_select
            agent_user = None
            if agent.created_by:
                agent_user = (
                    await db.execute(
                        _sqla_select(User).where(User.id == agent.created_by)
                    )
                ).scalar_one_or_none()

            # Inject business knowledge context (OKRs, metrics, glossary)
            # into agent_instructions so the LLM can cross-reference findings
            # with the user's actual business objectives across all 4 scopes
            # (org, space, crew, personal). Best-effort — never blocks the run.
            if agent_user is not None:
                try:
                    from src.services.knowledge_context_loader import (
                        load_knowledge_context_for_user,
                        render_knowledge_for_prompt,
                    )
                    _kc = await load_knowledge_context_for_user(db, agent_user)
                    _rendered = render_knowledge_for_prompt(_kc)
                    if _rendered:
                        agent_instructions = (
                            f"{_rendered}\n\n{agent_instructions}"
                            if agent_instructions
                            else _rendered
                        )
                        logger.info(
                            "Agent %s: injected knowledge context (%d metrics, %d glossary terms)",
                            agent_id,
                            len(_kc.get("metrics", [])),
                            len(_kc.get("glossary", [])),
                        )
                except Exception as _kc_err:
                    logger.debug("Agent %s: knowledge context load skipped: %s", agent_id, _kc_err)

            l1_should_run = await _connections_changed_since(
                db, connection_ids, agent.last_execution_at
            )
            if agent_user is not None:
                for conn_id in connection_ids:
                    await _record_beats_safely(
                        db, agent_user, kind="agent_l1", source_id=conn_id
                    )

            if not l1_should_run:
                # Short-circuit: nothing to look at. Mark the execution
                # as skipped (cycles=0, findings=0) and reschedule on
                # the agent's normal cadence. Stats and consecutive_
                # failures stay untouched — a "no-data" tick is not a
                # failure, just a quiet no-op.
                execution.status = "skipped_no_delta"
                execution.cycles_consumed = 0
                execution.findings_count = 0
                execution.finished_at = datetime.now(timezone.utc)
                # Skipped delta-checks are L1. Try/except so a missing
                # `tier` column doesn't fail the entire skip path.
                try:
                    execution.tier = "l1"
                except Exception:
                    pass
                agent.last_execution_at = datetime.now(timezone.utc)
                hours = FREQUENCY_HOURS.get(agent.frequency, 24)
                agent.next_execution_at = datetime.now(timezone.utc) + timedelta(
                    hours=hours
                )
                await db.commit()
                logger.info(
                    "Agent %s: L1 delta-check found no new data across "
                    "%d connection(s); skipping LLM call",
                    agent_id,
                    len(connection_ids),
                )
                return

            for conn_id in connection_ids:
                try:
                    # Pass table_ids as selected_datasets if specified.
                    # For SQL mode, prefer names extracted from custom_sql — the
                    # orchestrator matches by logical/physical name, not by UUID.
                    table_ids = getattr(agent, "table_ids", None)
                    # table_ids are stored as "connectionId::schema.tableName" — strip both
                    # the "connId::" prefix and the "schema." prefix so the orchestrator
                    # can match by logical/physical name (e.g. "accounts").
                    def _extract_table_name(tid: str) -> str:
                        name = tid.split("::", 1)[-1] if "::" in tid else tid
                        return name.rsplit(".", 1)[-1] if "." in name else name

                    table_names = (
                        [_extract_table_name(tid) for tid in table_ids]
                        if table_ids else None
                    ) or None
                    effective_datasets = sql_table_hints or table_names

                    # ── L2 — triage (placeholder). Today we always
                    # escalate to L3; the real gpt-4o-mini "is this
                    # worth a deep dive?" prompt lands in a follow-up.
                    # Recording the cost here keeps the per-connection
                    # plumbing honest so the dashboard reflects the
                    # eventual architecture without another schema
                    # change. ── L3 — deep dive (the existing AI call).
                    if agent_user is not None:
                        await _record_beats_safely(
                            db, agent_user, kind="agent_l2", source_id=conn_id
                        )
                        await _record_beats_safely(
                            db, agent_user, kind="agent_l3", source_id=conn_id
                        )

                    from src.core.locale import resolve_locale
                    response = await ai_client.query_connection(
                        connection_id=str(conn_id),
                        question=question,
                        user_id=str(agent.created_by) if agent.created_by else "system",
                        space_id=agent.scope_id or "default",
                        selected_datasets=effective_datasets,
                        instructions=agent_instructions,
                        agent_mode=monitor_type,
                        sql_instructions=sql_instructions,
                        locale=resolve_locale(None, agent_user),
                    )

                    answer = response.get("answer", "") if isinstance(response, dict) else str(response)
                    sql_used = response.get("sql", "") if isinstance(response, dict) else ""

                    if answer:
                        # Sprint 1.17 round 5 — viz_kind is picked by a
                        # heuristic from the response shape so every
                        # finding the worker emits ships with an
                        # authoritative card variant. The Pulse FE
                        # reads this and the "Add to page" picker
                        # mirrors it onto the spawned widget kind.
                        viz_kind = _infer_viz_kind(
                            response=response if isinstance(response, dict) else None,
                            answer=answer,
                        )
                        # Result rows live under `data_sample` on the AI
                        # QueryResponse (not `data`) — see _infer_viz_kind.
                        # Without this the finding shipped with rows=None and
                        # the Pulse card rendered as text instead of a chart.
                        raw_data = (
                            (response.get("data_sample") or response.get("data"))
                            if isinstance(response, dict)
                            else None
                        )
                        cols, data = _normalize_rows(raw_data)
                        rows_payload = {"columns": cols, "data": data} if cols and data else None
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
                            viz_kind=viz_kind,
                            rows=rows_payload,
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
            # Insights-Analytics tier — classify by what the run actually
            # did (findings + delta + monitor type). The aggregator on
            # Settings → Analytics derives tier from BeatConsumption.kind
            # so this is a forward-stamp for future use. Skipped when
            # the `tier` column hasn't migrated yet (postgres staging
            # may lag the model). Wrapped in try/except so a runtime
            # AttributeError doesn't kill an otherwise successful run.
            try:
                from src.services.insights_tier import classify_agent_execution

                execution.tier = classify_agent_execution(
                    findings_count=findings_created,
                    delta_kind=execution.delta_kind,
                    monitor_type=monitor_type,
                    input_tokens=execution.llm_tokens_used,
                    output_tokens=None,
                    error=False,
                )
            except Exception as tier_err:  # noqa: BLE001
                logger.warning(
                    f"Agent {agent_id}: tier stamp skipped: {tier_err}"
                )

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

            # Schedule next execution (skip if we just auto-paused above).
            # Adaptive backoff stretches the interval when recent runs have
            # been empty — see _adaptive_interval_hours.
            if agent.status == "active":
                base_hours = FREQUENCY_HOURS.get(agent.frequency, 24)
                hours = await _adaptive_interval_hours(
                    db, agent.id, base_hours, current_findings=findings_created
                )
                agent.next_execution_at = datetime.now(timezone.utc) + timedelta(hours=hours)
                if hours != base_hours:
                    logger.info(
                        "Agent %s: adaptive backoff applied (%dh base → %dh next)",
                        agent_id,
                        base_hours,
                        hours,
                    )

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
            try:
                execution.tier = "l1"
            except Exception:
                pass
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
