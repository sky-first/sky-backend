"""AI worker for processing AI queries."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List
from uuid import UUID

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def process_ai_query(self, query_id: str):
    """
    Process AI query.

    Args:
        query_id: AI query ID

    Returns:
        dict: Processing result
    """
    try:
        # TODO: Implement AI processing logic
        logger.info(f"Processing AI query {query_id}")
        return {"status": "success", "query_id": query_id}
    except Exception as exc:
        logger.error(f"AI processing failed for query {query_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=1)
def build_dashboard_job(self, job_id: str):
    """
    Execute an async dashboard build job (Davinci plan + widget execution).
    """
    try:
        asyncio.run(_build_dashboard_job_async(job_id))
        return {"status": "success", "job_id": job_id}
    except Exception as exc:
        logger.error(f"Dashboard build job failed for job_id={job_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=30)


def _get_textual_layout() -> list[dict]:
    """Return the exact 6-widget layout derived from Image 2 (orange boxes)."""
    # G = 24px (grid unit)
    return [
        {"x": 72.0, "y": 72.0, "w": 456.0, "h": 96.0},    # w1: Header
        {"x": 120.0, "y": 192.0, "w": 576.0, "h": 168.0}, # w2: Summary
        {"x": 144.0, "y": 384.0, "w": 264.0, "h": 504.0}, # w3: Detail A
        {"x": 432.0, "y": 384.0, "w": 216.0, "h": 360.0}, # w4: Detail B
        {"x": 696.0, "y": 96.0, "w": 336.0, "h": 720.0},  # w5: Column 1
        {"x": 1056.0, "y": 96.0, "w": 336.0, "h": 720.0}, # w6: Column 2
    ]


async def _build_dashboard_job_async(job_id: str) -> None:
    # Ensure all models are imported so SQLAlchemy relationship targets resolve
    # (worker process doesn't import the whole FastAPI app).
    import src.models  # noqa: F401
    import src.models.workspace  # noqa: F401
    from src.ai.http_client import AIServiceHTTPClient
    from src.config.database import AsyncSessionLocal
    from src.models.dashboard_build_job import DashboardBuildJob
    from src.models.notification import NotificationType
    from src.repositories.base import BaseRepository
    from src.repositories.dashboard import WidgetRepository
    from src.repositories.user import UserRepository
    from src.schemas.dashboard import DashboardCreate
    from src.schemas.notification import NotificationCreate
    from src.services.ai_service import AIService
    from src.services.dashboard_service import DashboardService
    from src.services.notification_service import NotificationService

    async with AsyncSessionLocal() as db:
        repo = BaseRepository(db, DashboardBuildJob)

        job_uuid = UUID(job_id)
        job = await repo.get_by_id(job_uuid)
        if not job:
            logger.warning(f"DashboardBuildJob not found: {job_id}")
            return

        if job.status in ("succeeded", "failed", "cancelled"):
            return

        try:
            # Mark running
            now = datetime.now(timezone.utc)
            job.status = "running"
            job.started_at = job.started_at or now
            job.completed_widgets = 0
            job.total_widgets = int(getattr(job, "max_widgets", 8) or 8)
            await db.commit()
            await db.refresh(job)

            # Resolve needed context
            if not job.space_id or not job.connection_id:
                raise RuntimeError("Job missing space_id or connection_id")

            user_repo = UserRepository(db)
            user = await user_repo.get_by_id(job.user_id)
            if not user:
                raise RuntimeError("User not found for job")

            user_id = job.user_id
            space_id = str(job.space_id)
            connection_id = str(job.connection_id)
            goal = job.goal
            language = job.language or "en"
            
            # Detect textual format early to cap max_widgets if needed
            is_textual = "[Visualization Format: textual]" in (goal or "")
            max_widgets = min(int(job.max_widgets or 8), 6 if is_textual else 8)

            ai_service = AIService(db)
            crew_ids = await ai_service._get_user_crew_ids(
                user_id, space_id, all_spaces=True
            )  # noqa: SLF001

            # Rate limiting (per widget) for cost control.
            # We enforce here (worker) because this is where the expensive calls happen.
            # If Redis is not configured/available (local dev/tests), we fail open.
            rl_limiter = None
            rl_buckets = None
            try:
                from src.config.settings import settings
                from src.rate_limit.core import (
                    RateLimitExceeded,
                    RedisFixedWindowRateLimiter,
                    default_buckets_for_request,
                    resolve_tenant_key,
                )

                if (
                    settings.RATE_LIMIT_ENABLED
                    and settings.AI_RATE_LIMIT_ENABLED
                    and bool(getattr(settings, "REDIS_URL", "") or "")
                ):
                    # Prefer tenant resolution by crews within the current space when possible.
                    # (If multiple crews exist, tenant_key falls back to space:{space_id}.)
                    crew_ids_in_space = await ai_service._get_user_crew_ids(
                        user_id, space_id, all_spaces=False
                    )  # noqa: SLF001
                    tenant_key = resolve_tenant_key(
                        user_id=str(user_id),
                        crew_ids=crew_ids_in_space,
                        space_id=space_id,
                        is_personal=True,
                    )
                    rl_limiter = RedisFixedWindowRateLimiter(enabled=True, key_prefix="rl:v1")
                    rl_buckets = default_buckets_for_request(
                        tenant_key=tenant_key,
                        user_id=str(user_id),
                        route_key="dashboards.widget_exec",
                        user_per_min=settings.AI_RATE_LIMIT_USER_PER_MINUTE,
                        user_per_hour=settings.AI_RATE_LIMIT_USER_PER_HOUR,
                        tenant_per_min=settings.AI_RATE_LIMIT_TENANT_PER_MINUTE,
                        tenant_per_hour=settings.AI_RATE_LIMIT_TENANT_PER_HOUR,
                        global_user_per_hour=settings.AI_RATE_LIMIT_GLOBAL_USER_PER_HOUR,
                        key_prefix="rl:v1",
                    )
            except Exception:
                rl_limiter = None
                rl_buckets = None

            # Build a compact schema summary from backend connection_metadata so Davinci can plan even if
            # the AI Engine catalog is not fully initialized.
            logical_tables_override = None
            schema_summary_override = None
            try:
                meta = await ai_service.metadata_repo.get_by_connection_id(
                    UUID(connection_id)
                )  # noqa: SLF001
                tables = (meta.tables or []) if meta else []
                logical_tables: list[str] = []
                schema_lines: list[str] = []
                for t in tables[:12] if isinstance(tables, list) else []:
                    if not isinstance(t, dict):
                        continue
                    schema = str(t.get("schema") or "").strip()
                    name = str(t.get("name") or "").strip()
                    if not name:
                        continue
                    logical = f"{schema}.{name}" if schema else name
                    logical_tables.append(logical)
                    cols = t.get("columns") or []
                    col_names = []
                    if isinstance(cols, list):
                        for c in cols[:10]:
                            if isinstance(c, dict) and c.get("name"):
                                col_names.append(str(c["name"]))
                    schema_lines.append(
                        f"- {logical} cols: {', '.join(col_names)}" if col_names else f"- {logical}"
                    )
                # unique preserving order
                seen = set()
                logical_tables_override = [
                    x for x in logical_tables if not (x in seen or seen.add(x))
                ]
                schema_summary_override = "\n".join(schema_lines)
            except Exception:
                logical_tables_override = None
                schema_summary_override = None

            client = AIServiceHTTPClient()
            ctx = None
            try:
                if isinstance(job.plan, dict) and isinstance(job.plan.get("_context"), dict):
                    ctx = job.plan.get("_context")
            except Exception:
                ctx = None
            plan_payload = await client.dashboard_plan(
                connection_id=connection_id,
                user_id=str(user_id),
                space_id=space_id,
                crew_ids=crew_ids if crew_ids else None,
                language=language,
                goal=goal,
                original_question=(
                    (ctx.get("original_question") if isinstance(ctx, dict) else None) or goal
                ),
                max_widgets=max_widgets,
                logical_tables_override=logical_tables_override,
                schema_summary_override=schema_summary_override,
                initial_ai_response=(
                    ctx.get("initial_ai_response") if isinstance(ctx, dict) else None
                ),
                context_spaces=(ctx.get("context_spaces") if isinstance(ctx, dict) else None),
                context_crews=(ctx.get("context_crews") if isinstance(ctx, dict) else None),
                context_tables=(ctx.get("context_tables") if isinstance(ctx, dict) else None),
            )
            # Preserve any pre-existing context stored in job.plan
            if isinstance(ctx, dict):
                plan_payload["_context"] = ctx
            job.plan = plan_payload
            await db.commit()
            await db.refresh(job)

            # Create dashboard once
            dashboard_service = DashboardService(db)
            if not job.dashboard_id:
                dashboard = await dashboard_service.create_dashboard(
                    user=user,
                    dashboard_data=DashboardCreate(
                        name=str(plan_payload.get("dashboard_name") or goal),
                        description=plan_payload.get("description"),
                        planet_id=job.planet_id,
                    ),
                )
                job.dashboard_id = dashboard.id
                await db.commit()
                await db.refresh(job)

            dashboard_id = job.dashboard_id

            # Plan widgets (cap to max_widgets)
            widgets = list(plan_payload.get("widgets") or [])[:max_widgets]

            # Layout logic
            is_textual = "[Visualization Format: textual]" in (goal or "")
            textual_layout = _get_textual_layout() if is_textual else []

            def _widget_grid_span(_widget_type: str) -> int:
                return 3

            def _widget_height(widget_type: str) -> float:
                if widget_type == "table":
                    return float(360)
                if widget_type in ("kpi", "text"):
                    return float(216)
                return float(312)

            def _span_width_px(span_cols: int) -> float:
                return float(span_cols * COL_W + max(0, span_cols - 1) * GAP_X)

            # 1) SHELL-FIRST: create placeholders for all widgets immediately
            widget_repo = WidgetRepository(db)
            placeholder_ids: List[str] = []
            cursor_col = 0
            cursor_row = 0

            for idx, w in enumerate(widgets):
                wtype = w.get("type") or "chart"
                
                # Apply fixed textual layout if available and applicable
                if is_textual and idx < len(textual_layout):
                    pos_info = textual_layout[idx]
                    x, y = pos_info["x"], pos_info["y"]
                    width, height = pos_info["w"], pos_info["h"]
                else:
                    span = _widget_grid_span(wtype)
                    if cursor_col + span > GRID_COLS:
                        cursor_row += 1
                        cursor_col = 0

                    x = float(BASE_X + cursor_col * STEP_X)
                    y = float(BASE_Y + cursor_row * ROW_STEP)
                    width = _span_width_px(span)
                    height = _widget_height(wtype)
                    cursor_col += span

                viz = w.get("viz") if isinstance(w.get("viz"), dict) else {}
                placeholder_data = {
                    "isPlaceholder": True,
                    "placeholderMode": "auto",
                    "question": w.get("question") or "",
                }
                # Keep chart type/mapping if known (useful once we "bring it to life")
                if wtype == "chart" and isinstance(viz, dict):
                    if viz.get("type"):
                        placeholder_data["type"] = viz.get("type")
                    if isinstance(viz.get("mapping"), dict):
                        placeholder_data["mapping"] = viz.get("mapping")

                created = await widget_repo.create(
                    dashboard_id=dashboard_id,
                    type=wtype,
                    title=w.get("title")
                    or (wtype.capitalize() if isinstance(wtype, str) else "Widget"),
                    position={"x": x, "y": y},
                    size={"width": width, "height": height},
                    data=placeholder_data,
                    config={"viz": viz or {}},
                    connection_id=UUID(connection_id),
                    query_id=None,
                )
                placeholder_ids.append(str(created.id))

            job.created_widget_ids = placeholder_ids
            job.completed_widgets = 0
            await db.commit()
            await db.refresh(job)

            # 2) Fill each widget and update in-place (placeholder -> real)
            from src.schemas.ai import AIQueryRequest, ConfigureData

            # Get additional context for the AI engine
            ctx = {}
            if isinstance(job.plan, dict) and isinstance(job.plan.get("_context"), dict):
                ctx = job.plan.get("_context")

            context_tables = ctx.get("context_tables") or []
            initial_ai_response = ctx.get("initial_ai_response")

            failed_count = 0
            failed_widget_ids: list[str] = []

            for w, wid in zip(widgets, placeholder_ids):
                await db.refresh(job)
                if job.status == "cancelled":
                    return

                wtype = w.get("type") or "chart"
                viz = w.get("viz") if isinstance(w.get("viz"), dict) else {}
                widget_id = UUID(wid)

                try:
                    # Enforce rate limit per widget (counts dashboards as questions too).
                    if rl_limiter and rl_buckets:
                        try:
                            await rl_limiter.enforce(rl_buckets)
                        except RateLimitExceeded as e:
                            # Don't fail the whole job; mark this widget as rate-limited placeholder and continue.
                            failed_count += 1
                            failed_widget_ids.append(str(widget_id))
                            logger.warning(
                                "Async dashboard build: rate limited (will continue). widget_id=%s scope=%s key=%s",
                                widget_id,
                                e.result.scope,
                                e.result.key,
                            )
                            try:
                                safe_title = w.get("title") or (
                                    wtype.capitalize() if isinstance(wtype, str) else "Widget"
                                )
                                await widget_repo.update(
                                    widget_id,
                                    title=f"{safe_title} (rate limited)",
                                    data={
                                        "isPlaceholder": True,
                                        "placeholderMode": "manual",
                                        "question": w.get("question") or "",
                                        "error": "rate_limited",
                                        "rate_limit": e.result.to_payload(),
                                    },
                                    config={"viz": viz or {}},
                                    query_id=None,
                                    connection_id=UUID(connection_id),
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to mark widget %s as rate-limited placeholder",
                                    widget_id,
                                )
                            job.completed_widgets = int(job.completed_widgets or 0) + 1
                            await db.commit()
                            continue

                    if wtype == "text":
                        content = ""
                        if isinstance(viz, dict) and isinstance(viz.get("content"), str):
                            content = viz.get("content") or ""
                        if not content:
                            content = w.get("title") or ""
                        await widget_repo.update(
                            widget_id,
                            title=w.get("title") or "Text",
                            data={
                                "content": content,
                                "question": w.get("question") or "",
                                "isPlaceholder": False,
                            },
                            config={"viz": viz or {}},
                            query_id=None,
                        )
                        job.completed_widgets = int(job.completed_widgets or 0) + 1
                        await db.commit()
                        continue

                    # Merge connection_id with context tables for knowledge
                    knowledge = [connection_id]
                    if context_tables:
                        knowledge.extend(context_tables)

                    # Construct rich context instructions for the AI
                    context_instructions = f"CONTEXT: You are building a widget for a dashboard with the goal: '{goal}'.\n"
                    if initial_ai_response:
                        context_instructions += (
                            f"The user previously received this answer: '{initial_ai_response}'.\n"
                        )

                    if context_tables:
                        context_instructions += f"Relevant tables identified in the conversation: {', '.join(context_tables)}.\n"

                    context_instructions += (
                        "Use this context to correctly identify tables and columns... "
                        "CRITICAL: You MUST generate a SQL query to retrieve data for this chart. "
                        "Do not return just text."
                    )

                    ai_req = AIQueryRequest(
                        question=w.get("question") or "",
                        knowledge=knowledge,
                        space_id=space_id,
                        is_personal=True,
                        configure_data=ConfigureData(
                            question=w.get("question") or "",
                            knowledge=knowledge,
                            instructions=context_instructions,
                            creativity=5,
                            response_format="json",
                            length=35,
                            sql_instructions=(
                                "If you generate SQL for a chart, prefer aggregated results with <= 15 rows. "
                                "Always LIMIT the result set to 15 rows or fewer."
                            ),
                        ),
                    )
                    query_resp = await ai_service.process_query(user_id, ai_req)

                    widget_data = {
                        "question": w.get("question"),
                        "answer": query_resp.answer,
                        "data": query_resp.data_sample or [],
                        "sql": query_resp.sql,
                        "chosen_table": getattr(query_resp, "chosen_table", None),
                        "chosen_datasets": getattr(query_resp, "chosen_datasets", None),
                        "isPlaceholder": False,
                    }

                    # Preserve planner chart viz + mapping
                    if wtype == "chart" and isinstance(viz, dict) and viz.get("type"):
                        widget_data["type"] = viz.get("type")
                        if isinstance(viz.get("mapping"), dict):
                            widget_data["mapping"] = viz.get("mapping")

                    # :novo: NOVA FUNCIONALIDADE: Sugerir título melhor baseado nos dados
                    final_title = w.get("title") or ""
                    try:
                        suggested_title = await client.suggest_widget_title(
                            question=w.get("question") or "",
                            data_sample=query_resp.data_sample or [],
                            answer=query_resp.answer,
                            current_title=w.get("title") or "",
                            language=language,
                        )
                        if suggested_title and suggested_title.strip():
                            generic_titles = [
                                "widget",
                                "chart",
                                "kpi",
                                "table",
                                "text",
                                "gráfico",
                                "dados",
                            ]
                            current_lower = (w.get("title") or "").lower().strip()
                            suggested_lower = suggested_title.lower().strip()
                            if (
                                current_lower in generic_titles
                                or suggested_lower not in generic_titles
                            ):
                                final_title = suggested_title
                                logger.info(
                                    "Widget title updated: '%s' -> '%s'",
                                    w.get("title"),
                                    final_title,
                                )
                    except Exception as e:
                        logger.warning(
                            "Failed to suggest title for widget %s: %s. Using original title.",
                            widget_id,
                            e,
                        )
                        final_title = w.get("title") or ""

                    await widget_repo.update(
                        widget_id,
                        title=final_title,
                        data=widget_data,
                        config={"viz": viz or {}},
                        query_id=query_resp.id,
                        connection_id=UUID(connection_id),
                    )

                except Exception as e:
                    failed_count += 1
                    failed_widget_ids.append(str(widget_id))
                    logger.exception(
                        "Async dashboard build: widget failed (will continue). widget_id=%s type=%s",
                        widget_id,
                        wtype,
                    )
                    try:
                        safe_title = w.get("title") or (
                            wtype.capitalize() if isinstance(wtype, str) else "Widget"
                        )
                        await widget_repo.update(
                            widget_id,
                            title=f"{safe_title} (error)",
                            data={
                                "isPlaceholder": True,
                                "placeholderMode": "manual",
                                "question": w.get("question") or "",
                                "error": str(e),
                            },
                            config={"viz": viz or {}},
                            query_id=None,
                            connection_id=UUID(connection_id),
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark widget %s as errored placeholder", widget_id
                        )

                job.completed_widgets = int(job.completed_widgets or 0) + 1
                await db.commit()
            job.status = "succeeded"

            # Trigger Notification: NEW_INSIGHT_AVAILABLE
            try:
                ns = NotificationService(db)
                await ns.create(
                    NotificationCreate(
                        user_id=job.user_id,
                        space_id=job.space_id,
                        type=NotificationType.NEW_INSIGHT_AVAILABLE,
                        title="New Insights Ready",
                        description=f"Your dashboard '{job.goal[:30]}...' has been built with new insights.",
                        entity_type="dashboard",
                        entity_id=job.dashboard_id,
                        deep_link=f"/dashboards/{job.dashboard_id}",
                    )
                )
            except Exception as e:
                logger.error(f"Failed to create notification for job {job_id}: {e}")

            if failed_count > 0:
                job.error = (
                    f"{failed_count} widget(s) failed; ids={','.join(failed_widget_ids[:10])}"
                )
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise
