from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest


@pytest.mark.asyncio
async def test_build_dashboard_job_async_success(monkeypatch):
    """
    Unit test for _build_dashboard_job_async covering the happy path with mocks only.
    This is intentionally lightweight (no DB/Redis/HTTP).
    """
    from src.ai import http_client as http_client_module
    from src.config import database as database_module
    from src.repositories import base as base_repo_module
    from src.repositories import dashboard as dashboard_repo_module
    from src.repositories import user as user_repo_module
    from src.services import ai_service as ai_service_module
    from src.services import dashboard_service as dashboard_service_module
    from src.workers import ai_worker

    job_id = str(uuid4())
    user_id = uuid4()
    planet_id = uuid4()
    space_id = uuid4()
    connection_id = uuid4()

    job = SimpleNamespace(
        id=UUID(job_id),
        user_id=user_id,
        planet_id=planet_id,
        space_id=space_id,
        connection_id=connection_id,
        goal="Build me a dashboard",
        language="en",
        max_widgets=2,
        status="queued",
        started_at=None,
        finished_at=None,
        completed_widgets=0,
        total_widgets=0,
        dashboard_id=None,
        created_widget_ids=None,
        plan=None,
        error=None,
    )

    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    class _SessionCM:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(database_module, "AsyncSessionLocal", lambda: _SessionCM())

    class FakeJobRepo:
        def __init__(self, _db, _model):
            pass

        async def get_by_id(self, _id):
            return job

    monkeypatch.setattr(base_repo_module, "BaseRepository", FakeJobRepo)

    class FakeUserRepo:
        def __init__(self, _db):
            pass

        async def get_by_id(self, _id):
            return SimpleNamespace(id=_id)

    monkeypatch.setattr(user_repo_module, "UserRepository", FakeUserRepo)

    class FakeAIService:
        def __init__(self, _db):
            self.metadata_repo = SimpleNamespace(get_by_connection_id=AsyncMock(return_value=None))

        async def _get_user_crew_ids(self, *_args, **_kwargs):  # noqa: ANN001
            return []

        async def process_query(self, *_args, **_kwargs):  # noqa: ANN001
            return SimpleNamespace(
                id=uuid4(),
                answer="ok",
                data_sample=[{"x": 1}],
                sql="select 1",
            )

    monkeypatch.setattr(ai_service_module, "AIService", FakeAIService)

    class FakeHTTPClient:
        async def dashboard_plan(self, **_kwargs):  # noqa: ANN003
            return {
                "dashboard_name": "Auto Dashboard",
                "description": "Generated",
                "widgets": [
                    {
                        "type": "text",
                        "title": "Intro",
                        "question": "Intro?",
                        "viz": {"content": "Hello"},
                    },
                    {
                        "type": "chart",
                        "title": "Chart",
                        "question": "Show X",
                        "viz": {"type": "bar", "mapping": {"x": "x", "y": "y"}},
                    },
                ],
            }

    monkeypatch.setattr(http_client_module, "AIServiceHTTPClient", FakeHTTPClient)

    class FakeDashboardService:
        def __init__(self, _db):
            pass

        async def create_dashboard(self, **_kwargs):  # noqa: ANN003
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(dashboard_service_module, "DashboardService", FakeDashboardService)

    class FakeWidgetRepo:
        def __init__(self, _db):
            pass

        async def create(self, **_kwargs):  # noqa: ANN003
            return SimpleNamespace(id=uuid4())

        async def update(self, *_args, **_kwargs):  # noqa: ANN001, ANN003
            return None

    monkeypatch.setattr(dashboard_repo_module, "WidgetRepository", FakeWidgetRepo)

    await ai_worker._build_dashboard_job_async(job_id)

    assert job.status == "succeeded"
    assert job.dashboard_id is not None
    assert isinstance(job.created_widget_ids, list)
    assert len(job.created_widget_ids) == 2
    assert job.completed_widgets == 2
    assert job.plan is not None


@pytest.mark.asyncio
async def test_build_dashboard_job_async_job_not_found(monkeypatch):
    from src.config import database as database_module
    from src.repositories import base as base_repo_module
    from src.workers import ai_worker

    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    class _SessionCM:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(database_module, "AsyncSessionLocal", lambda: _SessionCM())

    class FakeJobRepo:
        def __init__(self, _db, _model):
            pass

        async def get_by_id(self, _id):
            return None

    monkeypatch.setattr(base_repo_module, "BaseRepository", FakeJobRepo)

    # Should return without raising
    await ai_worker._build_dashboard_job_async(str(uuid4()))


@pytest.mark.asyncio
async def test_build_dashboard_job_async_missing_ids_sets_failed(monkeypatch):
    from src.config import database as database_module
    from src.repositories import base as base_repo_module
    from src.repositories import user as user_repo_module
    from src.services import ai_service as ai_service_module
    from src.workers import ai_worker

    job_id = str(uuid4())
    job = SimpleNamespace(
        id=UUID(job_id),
        user_id=uuid4(),
        planet_id=uuid4(),
        space_id=None,
        connection_id=None,
        goal="g",
        language="en",
        max_widgets=1,
        status="queued",
        started_at=None,
        finished_at=None,
        completed_widgets=0,
        total_widgets=0,
        dashboard_id=None,
        created_widget_ids=None,
        plan=None,
        error=None,
    )

    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    class _SessionCM:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(database_module, "AsyncSessionLocal", lambda: _SessionCM())

    class FakeJobRepo:
        def __init__(self, _db, _model):
            pass

        async def get_by_id(self, _id):
            return job

    monkeypatch.setattr(base_repo_module, "BaseRepository", FakeJobRepo)

    # Minimal mocks so it can reach the "missing ids" RuntimeError
    monkeypatch.setattr(
        user_repo_module,
        "UserRepository",
        lambda _db: SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(id=job.user_id))
        ),
    )
    monkeypatch.setattr(
        ai_service_module,
        "AIService",
        lambda _db: SimpleNamespace(
            _get_user_crew_ids=AsyncMock(return_value=[]),
            metadata_repo=SimpleNamespace(get_by_connection_id=AsyncMock(return_value=None)),
        ),
    )

    with pytest.raises(RuntimeError, match="space_id or connection_id"):
        await ai_worker._build_dashboard_job_async(job_id)

    assert job.status == "failed"
    assert job.error is not None
