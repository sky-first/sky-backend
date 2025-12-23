"""AI worker for processing AI queries."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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


async def _build_dashboard_job_async(job_id: str) -> None:
    # Ensure all models are imported so SQLAlchemy relationship targets resolve
    # (worker process doesn't import the whole FastAPI app).
    import src.models  # noqa: F401
    import src.models.workspace  # noqa: F401

    from src.config.database import AsyncSessionLocal
    from src.models.dashboard_build_job import DashboardBuildJob
    from src.repositories.base import BaseRepository
    from src.repositories.user import UserRepository
    from src.repositories.dashboard import WidgetRepository
    from src.services.dashboard_service import DashboardService
    from src.services.ai_service import AIService
    from src.ai.http_client import AIServiceHTTPClient
    from src.schemas.dashboard import DashboardCreate, WidgetCreate

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
            max_widgets = min(int(job.max_widgets or 8), 8)

            ai_service = AIService(db)
            crew_ids = await ai_service._get_user_crew_ids(user_id, space_id, all_spaces=True)  # noqa: SLF001

            client = AIServiceHTTPClient()
            plan_payload = await client.dashboard_plan(
                connection_id=connection_id,
                user_id=str(user_id),
                space_id=space_id,
                crew_ids=crew_ids if crew_ids else None,
                language=language,
                goal=goal,
                max_widgets=max_widgets,
            )
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

            # Layout params copied from sync build (4 per row)
            GRID_COLS = 12
            COL_W = 96
            GAP_X = 24
            STEP_X = COL_W + GAP_X
            BASE_X = 72
            BASE_Y = 72
            ROW_STEP = 360

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

            for w in widgets:
                wtype = w.get("type") or "chart"
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
                    title=w.get("title") or (wtype.capitalize() if isinstance(wtype, str) else "Widget"),
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

            for w, wid in zip(widgets, placeholder_ids):
                await db.refresh(job)
                if job.status == "cancelled":
                    return

                wtype = w.get("type") or "chart"
                viz = w.get("viz") if isinstance(w.get("viz"), dict) else {}
                widget_id = UUID(wid)

                if wtype == "text":
                    content = ""
                    if isinstance(viz, dict) and isinstance(viz.get("content"), str):
                        content = viz.get("content") or ""
                    if not content:
                        content = w.get("title") or ""
                    await widget_repo.update(
                        widget_id,
                        title=w.get("title") or "Text",
                        data={"content": content, "question": w.get("question") or "", "isPlaceholder": False},
                        config={"viz": viz or {}},
                        query_id=None,
                    )
                    job.completed_widgets = int(job.completed_widgets or 0) + 1
                    await db.commit()
                    continue

                ai_req = AIQueryRequest(
                    question=w.get("question") or "",
                    knowledge=[connection_id],
                    space_id=space_id,
                    is_personal=True,
                    configure_data=ConfigureData(
                        question=w.get("question") or "",
                        knowledge=[connection_id],
                        response_format="text",
                        creativity=15,
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

                await widget_repo.update(
                    widget_id,
                    title=w.get("title") or "",
                    data=widget_data,
                    config={"viz": viz or {}},
                    query_id=query_resp.id,
                    connection_id=UUID(connection_id),
                )

                job.completed_widgets = int(job.completed_widgets or 0) + 1
                await db.commit()

            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise

