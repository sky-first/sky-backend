"""AI worker for processing AI queries."""

import asyncio
import logging
import uuid

# Mesmo defeito do `space_service`: usado e nunca importado.
from sqlalchemy import select
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
        {"x": 72.0, "y": 72.0, "w": 456.0, "h": 96.0},  # w1: Header
        {"x": 120.0, "y": 192.0, "w": 576.0, "h": 168.0},  # w2: Summary
        {"x": 144.0, "y": 384.0, "w": 264.0, "h": 504.0},  # w3: Detail A
        {"x": 432.0, "y": 384.0, "w": 216.0, "h": 360.0},  # w4: Detail B
        {"x": 696.0, "y": 96.0, "w": 336.0, "h": 720.0},  # w5: Column 1
        {"x": 1056.0, "y": 96.0, "w": 336.0, "h": 720.0},  # w6: Column 2
    ]


async def _build_dashboard_job_async(job_id: str) -> None:
    # Ensure all models are imported so SQLAlchemy relationship targets resolve
    # (worker process doesn't import the whole FastAPI app).
    import src.models  # noqa: F401
    import src.models.workspace  # noqa: F401
    from src.ai.http_client import AIServiceHTTPClient
    from src.config.database import AsyncSessionLocal
    from src.models.page_build_job import PageBuildJob
    from src.models.notification import NotificationType
    from src.repositories.base import BaseRepository
    from src.repositories.widget import WidgetRepository
    from src.repositories.user import UserRepository
    from src.schemas.notification import NotificationCreate
    from src.services.ai_service import AIService
    from src.services.widget_service import WidgetService
    from src.services.notification_service import NotificationService

    async with AsyncSessionLocal() as db:
        # Renamed in PR0a from DashboardBuildJob → PageBuildJob.
        repo = BaseRepository(db, PageBuildJob)

        job_uuid = UUID(job_id)
        job = await repo.get_by_id(job_uuid)
        if not job:
            logger.warning(f"PageBuildJob not found: {job_id}")
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
            from src.core.locale import DEFAULT_LOCALE, normalize_locale
            language = normalize_locale(job.language) if job.language else DEFAULT_LOCALE

            # Force textual/infographic mode for AI-built dashboards as requested by USER
            is_textual = True
            max_widgets = min(int(job.max_widgets or 8), 6)

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
                        route_key="pages.widget_exec",
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

            # --- MANDATORY PERMISSION FILTERING FOR DASHBOARD PLAN ---
            # 1. Get truly authorized tables for this context
            authorized_tables = []
            try:
                authorized_tables = await ai_service.permission_service.get_authorized_tables(
                    user_id=user_id,
                    connection_id=UUID(connection_id),
                    space_id=UUID(space_id) if space_id else None,
                    crew_ids=[UUID(cid) for cid in crew_ids] if crew_ids else None,
                )
            except Exception as e:
                logger.error(f"Error checking authorized tables in worker: {e}", exc_info=True)
                authorized_tables = []

            # 2. Build a compact schema summary from backend connection_metadata,
            # BUT only for authorized tables.
            logical_tables_override = None
            schema_summary_override = None
            try:
                meta = await ai_service.metadata_repo.get_by_connection_id(UUID(connection_id))
                tables = (meta.tables or []) if meta else []
                logical_tables: list[str] = []
                schema_lines: list[str] = []

                # Filter to only authorized tables
                authorized_set = set(authorized_tables)

                for t in tables if isinstance(tables, list) else []:
                    if not isinstance(t, dict):
                        continue
                    name = str(t.get("name") or "").strip()
                    if not name or name not in authorized_set:
                        continue

                    schema = str(t.get("schema") or "").strip()
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

                # unique preserving order, limit to 12 tables to keep planning prompt small
                seen = set()
                logical_tables_override = [
                    x for x in logical_tables if not (x in seen or seen.add(x))
                ][:12]
                schema_summary_override = "\n".join(schema_lines[:12])
            except Exception:
                logical_tables_override = None
                schema_summary_override = None

            # ── Plan Bypass ──────────────────────────────────────────────────────────
            # If the frontend/chat already supplied a valid plan in job.plan, use it
            # directly without an extra AI round-trip (saves cost and latency).

            # Extract any conversation context stored in job.plan._context first,
            # so it is available in both the bypass and the re-plan branches.
            ctx = None
            try:
                if isinstance(job.plan, dict) and isinstance(job.plan.get("_context"), dict):
                    ctx = job.plan.get("_context")
            except Exception:
                ctx = None

            existing_plan = None
            try:
                p = job.plan
                if (
                    isinstance(p, dict)
                    and isinstance(p.get("widgets"), list)
                    and len(p["widgets"]) > 0
                ):
                    existing_plan = p
            except Exception:
                existing_plan = None

            if existing_plan is not None:
                logger.info(
                    "build_dashboard_job(%s): using pre-calculated plan (%d widgets)",
                    job_id,
                    len(existing_plan["widgets"]),
                )
                plan_payload = existing_plan
            else:
                client = AIServiceHTTPClient()
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
                    authorized_tables=list(authorized_tables),
                )
            # Preserve any pre-existing context stored in job.plan
            if isinstance(ctx, dict):
                plan_payload["_context"] = ctx
            job.plan = plan_payload
            await db.commit()
            await db.refresh(job)

            # Page is the canvas now — apply plan-derived canvas state directly
            # onto the page. (Dashboard layer dropped 2026-05-20.)
            widget_service = WidgetService(db)
            from src.models.page import Page
            page = (
                await db.execute(select(Page).where(Page.id == job.page_id))
            ).scalar_one_or_none()
            if page is None:
                raise RuntimeError(f"Page {job.page_id} not found for build job {job_id}")

            # If the plan contains filters, persist them to canvas_settings so the
            # frontend can hydrate the filter bar without an extra round-trip.
            plan_filters = plan_payload.get("filters")
            if plan_filters and isinstance(plan_filters, list):
                page.canvas_settings = {"filters": plan_filters}
                logger.info(
                    "build_page_job(%s): saved %d filters to canvas_settings",
                    job_id,
                    len(plan_filters),
                )
                await db.commit()
                await db.refresh(job)

            page_id = job.page_id

            # Plan widgets (cap to max_widgets)
            widgets = list(plan_payload.get("widgets") or [])[:max_widgets]

            textual_layout = _get_textual_layout()

            # Layout parameters
            GRID_COLS = 12
            COL_W = 96
            GAP_X = 24
            STEP_X = COL_W + GAP_X
            BASE_X = 72
            BASE_Y = 72
            ROW_STEP = 360

            # If textual layout is active, FORCE all widgets to be insight cards
            # UNLESS they are explicitly marked as 'infographic'
            if is_textual:
                for w in widgets:
                    if w.get("type") != "infographic":
                        w["type"] = "insight"

            def _widget_grid_span(_widget_type: str) -> int:
                # Infographic takes full width
                if _widget_type == "infographic":
                    return 12
                return 3

            def _widget_height(widget_type: str) -> float:
                if widget_type == "infographic":
                    return float(800)  # Taller for infographic
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

                # ── Layout priority (CRITICAL: must be checked BEFORE is_textual logic) ──
                # 1. Explicit layout from the AI plan takes highest priority.
                # 2. Hardcoded textual layout is used as fallback (but never for infographic).
                # 3. Plain grid layout as last resort.
                plan_layout = w.get("layout")
                if plan_layout and isinstance(plan_layout, dict):
                    # AI plan supplied explicit coordinates — use them directly
                    x = float(plan_layout.get("x") or 72.0)
                    y = float(plan_layout.get("y") or 72.0)
                    width = float(plan_layout.get("w") or 456.0)
                    height = float(plan_layout.get("h") or 312.0)
                    logger.debug(
                        "build_dashboard_job(%s): widget %d using plan layout x=%s y=%s",
                        job_id,
                        idx,
                        x,
                        y,
                    )
                elif is_textual and idx < len(textual_layout) and wtype != "infographic":
                    # Fallback to hardcoded textual layout (skipped for infographic widgets)
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
                    "isInsight": True if (is_textual and wtype != "infographic") else False,
                }
                # Keep chart type/mapping if known (useful once we "bring it to life")
                if wtype == "chart" and isinstance(viz, dict):
                    if viz.get("type"):
                        placeholder_data["type"] = viz.get("type")
                    if isinstance(viz.get("mapping"), dict):
                        placeholder_data["mapping"] = viz.get("mapping")

                created = await widget_repo.create(
                    page_id=page_id,
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
            from src.schemas.ai import AIQueryRequest, ConfigureData, GenerateInfographicRequest

            # Get additional context for the AI engine
            ctx = {}
            if isinstance(job.plan, dict) and isinstance(job.plan.get("_context"), dict):
                ctx = job.plan.get("_context")

            context_tables = ctx.get("context_tables") or []
            initial_ai_response = ctx.get("initial_ai_response")

            failed_count = 0
            failed_widget_ids: list[str] = []

            for idx, (w, wid) in enumerate(zip(widgets, placeholder_ids)):
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
                            except Exception as update_exc:
                                logger.exception(
                                    "Failed to mark widget %s as rate-limited placeholder",
                                    widget_id,
                                    exc_info=update_exc,
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

                    if wtype == "infographic":
                        context_instructions += (
                            "\nFor this Infographic, provide a broad and detailed analysis in the answer field. "
                            "Include metrics, growth rates, drivers, and strategic outlook in the text. "
                        )

                    if wtype == "insight":
                        context_instructions += (
                            "\nFor this Insight Card, provide a concise analytical summary in the answer field, "
                            "and ensure the data sample supports the insight with a relevant chart structure."
                        )

                    ai_req = AIQueryRequest(
                        question=w.get("question") or "",
                        knowledge=knowledge,
                        space_id=space_id,
                        is_personal=True,
                        locale=language,
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
                        "isLoading": False,
                    }

                    logger.debug(f"Processing widget {idx}, type={wtype}")
                    if wtype == "infographic":
                        # Generate structured infographic data
                        try:
                            # Extract style from widget config or data
                            # Default to 'mix' if not specified
                            style = "mix"
                            if isinstance(viz, dict) and viz.get("style"):
                                style = viz.get("style")

                            infographic_req = GenerateInfographicRequest(
                                question=w.get("question") or "",
                                answer=query_resp.answer or "",
                                data_sample=query_resp.data_sample,
                                language=language,
                                style=style,
                            )
                            infographic_data = await ai_service.generate_infographic(
                                user_id, infographic_req
                            )
                            widget_data["infographic_data"] = infographic_data
                            widget_data["type"] = "infographic"
                        except Exception:
                            # Fallback: maintain basic widget data
                            widget_data["isLoading"] = False
                            widget_data["error"] = True

                    elif wtype == "insight":
                        # Map query result to Insight data structure
                        # Wide widgets get text_beside_chart, tall get text_above_chart
                        layout_type = "text_beside_chart" if idx < 2 else "text_above_chart"

                        # Simple heuristic for icon priority
                        priority = "medium"
                        answer_lower = (query_resp.answer or "").lower()
                        if (
                            "critical" in answer_lower
                            or "urgent" in answer_lower
                            or "fail" in answer_lower
                        ):
                            priority = "critical"
                        elif (
                            "high" in answer_lower
                            or "important" in answer_lower
                            or "significant" in answer_lower
                        ):
                            priority = "high"

                        # Chart type fallback
                        chart_type = "bar"
                        if isinstance(viz, dict) and viz.get("type"):
                            chart_type = viz.get("type")

                        widget_data.update(
                            {
                                "isInsight": True,
                                "insightTitle": w.get("title") or "Insight",
                                "layout_type": layout_type,
                                "section_id": f"insight-{idx}-{uuid.uuid4()}",
                                "content": {
                                    "text_block": {
                                        "title": "Analysis",
                                        "body": query_resp.answer or "No insight generated.",
                                        "priority": priority,
                                    },
                                    "chart_block": {
                                        "chartType": chart_type,
                                        "data": query_resp.data_sample or [],
                                        "chartTitle": "Supporting Data",
                                    },
                                },
                            }
                        )

                    # Preserve planner chart viz + mapping ONLY for non-insight charts
                    elif wtype == "chart" and isinstance(viz, dict) and viz.get("type"):
                        widget_data["type"] = viz.get("type")
                        if isinstance(viz.get("mapping"), dict):
                            widget_data["mapping"] = viz.get("mapping")

                    # :novo: NOVA FUNCIONALIDADE: Sugerir título melhor baseado nos dados
                    # Skip for Insight cards (they manage their own title via content.text_block.title or w.get("title"))
                    if wtype == "insight":
                        final_title = w.get("title") or "Insight"
                    else:
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
                        description=f"Your page '{job.goal[:30]}...' has been built with new insights.",
                        entity_type="page",
                        entity_id=job.page_id,
                        deep_link=f"/pages/{job.page_id}",
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
