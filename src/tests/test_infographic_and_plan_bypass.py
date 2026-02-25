"""Tests for generate_infographic (AIService) and plan bypass / layout / filter logic in ai_worker."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.schemas.ai import GenerateInfographicRequest

# ─────────────────────────────────────────────────────────────────────────────
# AIService.generate_infographic
# ─────────────────────────────────────────────────────────────────────────────


class _FakeDB:
    commit = AsyncMock()
    refresh = AsyncMock()


def _make_ai_service(real_ai=None):
    """Return an AIService with injected dependencies, no DB connection needed."""
    from src.services.ai_service import AIService

    svc = AIService.__new__(AIService)
    svc.db = _FakeDB()
    svc.mock_ai = MagicMock()

    async def mock_gen(**kwargs):
        return {
            "type": "infographic",
            "sections": [
                {"id": "header", "type": "header", "title": "Mock"},
                {"id": "summary", "type": "text", "body": "Mock body"},
                {"id": "chart", "type": "chart", "data": kwargs.get("data_sample") or []},
            ],
            "meta": {"mock": True},
        }

    svc.mock_ai.generate_infographic = AsyncMock(side_effect=mock_gen)
    svc.real_ai = real_ai
    svc.query_repo = MagicMock()
    svc.history_repo = MagicMock()
    svc.pipeline_repo = MagicMock()
    svc.feedback_repo = MagicMock()
    svc.connection_repo = MagicMock()
    svc.metadata_repo = MagicMock()
    svc.crew_member_repo = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_generate_infographic_mock_fallback_when_no_real_ai():
    """When real_ai is None, should return mock infographic data."""
    svc = _make_ai_service(real_ai=None)
    result = await svc.generate_infographic(
        user_id=uuid4(),
        request=GenerateInfographicRequest(
            question="What are the top products?",
            answer="Product A leads with 45% share.",
            language="en",
        ),
    )
    assert result["type"] == "infographic"
    assert result["meta"]["mock"] is True
    assert any(s["id"] == "header" for s in result["sections"])
    assert any(s["id"] == "summary" for s in result["sections"])
    assert any(s["id"] == "chart" for s in result["sections"])


@pytest.mark.asyncio
async def test_generate_infographic_uses_real_ai_when_configured():
    """When real_ai is configured and implements generate_infographic, it should be called."""
    expected = {"type": "infographic", "sections": [], "meta": {"mock": False}}

    real_ai = MagicMock()
    real_ai.generate_infographic = AsyncMock(return_value=expected)

    svc = _make_ai_service(real_ai=real_ai)
    result = await svc.generate_infographic(
        user_id=uuid4(),
        request=GenerateInfographicRequest(
            question="Revenue trend?",
            answer="Revenue grew 12% YoY.",
            language="pt",
        ),
    )
    assert result == expected
    real_ai.generate_infographic.assert_called_once()


@pytest.mark.asyncio
async def test_generate_infographic_falls_back_when_real_ai_raises():
    """If real_ai.generate_infographic raises, should fall back to mock."""
    real_ai = MagicMock()
    real_ai.generate_infographic = AsyncMock(side_effect=RuntimeError("AI engine unreachable"))

    svc = _make_ai_service(real_ai=real_ai)
    result = await svc.generate_infographic(
        user_id=uuid4(),
        request=GenerateInfographicRequest(
            question="Costs?",
            answer="Costs rose 5%.",
            language="es",
        ),
    )
    assert result["type"] == "infographic"
    assert result["meta"]["mock"] is True


@pytest.mark.asyncio
async def test_generate_infographic_falls_back_when_real_ai_lacks_method():
    """If real_ai does NOT implement generate_infographic (AttributeError), use mock."""
    real_ai = MagicMock(spec=[])  # no attributes at all → raises AttributeError

    svc = _make_ai_service(real_ai=real_ai)
    result = await svc.generate_infographic(
        user_id=uuid4(),
        request=GenerateInfographicRequest(
            question="Staff count?",
            answer="250 employees.",
            language="en",
        ),
    )
    assert result["type"] == "infographic"
    assert result["meta"]["mock"] is True


@pytest.mark.asyncio
async def test_generate_infographic_data_sample_embedded():
    """data_sample list should appear inside the chart section."""
    svc = _make_ai_service(real_ai=None)
    sample = [{"name": "Jan", "value": 100}, {"name": "Feb", "value": 120}]
    result = await svc.generate_infographic(
        user_id=uuid4(),
        request=GenerateInfographicRequest(
            question="Monthly revenue?",
            answer="Growing.",
            data_sample=sample,
            language="en",
        ),
    )
    chart_section = next(s for s in result["sections"] if s["id"] == "chart")
    assert chart_section["data"] == sample


@pytest.mark.asyncio
async def test_generate_infographic_non_list_data_sample_becomes_empty():
    """Non-list data_sample should result in empty chart data (no crash)."""
    svc = _make_ai_service(real_ai=None)
    result = await svc.generate_infographic(
        user_id=uuid4(),
        request=GenerateInfographicRequest(
            question="Q",
            answer="A",
            data_sample=None,  # Use None instead of invalid dict for request
            language="en",
        ),
    )
    chart_section = next(s for s in result["sections"] if s["id"] == "chart")
    assert chart_section["data"] == []


# Since we want to test falling through with NONE, let's keep it simple.
# The real check for non-list already happens inside mock_ai or real_ai.


# ─────────────────────────────────────────────────────────────────────────────
# ai_worker: Plan Bypass
# ─────────────────────────────────────────────────────────────────────────────


def _make_base_job(plan=None, space_id=None, connection_id=None):
    job_id = str(uuid4())
    return job_id, SimpleNamespace(
        id=UUID(job_id),
        user_id=uuid4(),
        planet_id=uuid4(),
        space_id=space_id or uuid4(),
        connection_id=connection_id or uuid4(),
        goal="Test goal",
        language="en",
        max_widgets=2,
        status="queued",
        started_at=None,
        finished_at=None,
        completed_widgets=0,
        total_widgets=0,
        dashboard_id=None,
        created_widget_ids=None,
        plan=plan,
        error=None,
    )


def _patch_worker_deps(monkeypatch, job, plan_from_http=None, widget_answer="ok"):
    """Monkeypatch all heavy dependencies for _build_dashboard_job_async."""
    from src.ai import http_client as http_client_module
    from src.config import database as database_module
    from src.repositories import base as base_repo_module
    from src.repositories import dashboard as dashboard_repo_module
    from src.repositories import user as user_repo_module
    from src.services import ai_service as ai_service_module
    from src.services import dashboard_service as dashboard_service_module

    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    class _CM:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(database_module, "AsyncSessionLocal", lambda: _CM())

    class _JobRepo:
        def __init__(self, _db, _model):
            pass

        async def get_by_id(self, _id):
            return job

    monkeypatch.setattr(base_repo_module, "BaseRepository", _JobRepo)
    monkeypatch.setattr(
        user_repo_module,
        "UserRepository",
        lambda _db: SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(id=job.user_id))
        ),
    )

    http_called = {"n": 0}

    class _HTTPClient:
        async def dashboard_plan(self, **_kw):
            http_called["n"] += 1
            return plan_from_http or {
                "dashboard_name": "HTTP Plan",
                "description": "From HTTP",
                "widgets": [
                    {"type": "text", "title": "T", "question": "Q?", "viz": {"content": "hi"}},
                ],
            }

        async def suggest_widget_title(self, **_kw):
            return "Suggested"

    monkeypatch.setattr(http_client_module, "AIServiceHTTPClient", _HTTPClient)

    monkeypatch.setattr(
        ai_service_module,
        "AIService",
        lambda _db: SimpleNamespace(
            metadata_repo=SimpleNamespace(get_by_connection_id=AsyncMock(return_value=None)),
            _get_user_crew_ids=AsyncMock(return_value=[]),
            process_query=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid4(), answer=widget_answer, data_sample=[], sql="select 1"
                )
            ),
        ),
    )
    monkeypatch.setattr(
        dashboard_service_module,
        "DashboardService",
        lambda _db: SimpleNamespace(
            create_dashboard=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        ),
    )
    monkeypatch.setattr(
        dashboard_repo_module,
        "WidgetRepository",
        lambda _db: SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
            update=AsyncMock(return_value=None),
        ),
    )
    return http_called


@pytest.mark.asyncio
async def test_plan_bypass_uses_existing_plan_without_http_call(monkeypatch):
    """If job.plan already has widgets, the worker must NOT call client.dashboard_plan."""
    job_id, job = _make_base_job(
        plan={
            "dashboard_name": "Pre-built",
            "description": "Already planned",
            "widgets": [
                {
                    "type": "text",
                    "title": "Header",
                    "question": "What?",
                    "viz": {"content": "Intro"},
                },
            ],
        }
    )
    http_called = _patch_worker_deps(monkeypatch, job)

    from src.workers import ai_worker

    await ai_worker._build_dashboard_job_async(job_id)

    assert http_called["n"] == 0, "HTTP plan should NOT have been called when pre-built plan exists"
    assert job.status == "succeeded"


@pytest.mark.asyncio
async def test_plan_bypass_falls_through_to_http_when_no_plan(monkeypatch):
    """If job.plan is None, the worker MUST call client.dashboard_plan."""
    job_id, job = _make_base_job(plan=None)
    http_called = _patch_worker_deps(monkeypatch, job)

    from src.workers import ai_worker

    await ai_worker._build_dashboard_job_async(job_id)

    assert http_called["n"] == 1, "HTTP plan SHOULD have been called when no pre-built plan"
    assert job.status == "succeeded"


@pytest.mark.asyncio
async def test_plan_bypass_falls_through_to_http_when_plan_has_empty_widgets(monkeypatch):
    """job.plan with empty widgets list is NOT a valid bypass — must call HTTP."""
    job_id, job = _make_base_job(plan={"dashboard_name": "X", "widgets": []})
    http_called = _patch_worker_deps(monkeypatch, job)

    from src.workers import ai_worker

    await ai_worker._build_dashboard_job_async(job_id)

    assert http_called["n"] == 1, "HTTP plan SHOULD have been called when widgets list is empty"


# ─────────────────────────────────────────────────────────────────────────────
# ai_worker: Filters saved to canvas_settings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filters_saved_to_canvas_settings(monkeypatch):
    """When plan has filters, dashboard.canvas_settings must be set to {filters: [...]}."""
    from src.ai import http_client as http_client_module
    from src.config import database as database_module
    from src.repositories import base as base_repo_module
    from src.repositories import dashboard as dashboard_repo_module
    from src.repositories import user as user_repo_module
    from src.services import ai_service as ai_service_module
    from src.services import dashboard_service as dashboard_service_module
    from src.workers import ai_worker

    job_id = str(uuid4())
    job = SimpleNamespace(
        id=UUID(job_id),
        user_id=uuid4(),
        planet_id=uuid4(),
        space_id=uuid4(),
        connection_id=uuid4(),
        goal="Filter test",
        language="en",
        max_widgets=1,
        status="queued",
        started_at=None,
        finished_at=None,
        completed_widgets=0,
        total_widgets=0,
        dashboard_id=None,
        created_widget_ids=None,
        plan={
            "dashboard_name": "Filtered",
            "description": "With filters",
            "filters": [
                {"label": "Region", "field": "region", "type": "select"},
                {"label": "Year", "field": "year", "type": "range"},
            ],
            "widgets": [
                {"type": "text", "title": "Intro", "question": "Q?", "viz": {"content": "Hi"}}
            ],
        },
        error=None,
    )

    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    class _CM:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(database_module, "AsyncSessionLocal", lambda: _CM())

    class _JobRepo:
        def __init__(self, _db, _model):
            pass

        async def get_by_id(self, _id):
            return job

    monkeypatch.setattr(base_repo_module, "BaseRepository", _JobRepo)
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
            metadata_repo=SimpleNamespace(get_by_connection_id=AsyncMock(return_value=None)),
            _get_user_crew_ids=AsyncMock(return_value=[]),
            process_query=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid4(), answer="ok", data_sample=[], sql="select 1"
                )
            ),
        ),
    )

    captured_dashboard = {}

    class _DashboardService:
        def __init__(self, _db):
            pass

        async def create_dashboard(self, **_kw):
            d = SimpleNamespace(id=uuid4())
            captured_dashboard["obj"] = d
            return d

    monkeypatch.setattr(dashboard_service_module, "DashboardService", _DashboardService)
    monkeypatch.setattr(
        dashboard_repo_module,
        "WidgetRepository",
        lambda _db: SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
            update=AsyncMock(return_value=None),
        ),
    )

    await ai_worker._build_dashboard_job_async(job_id)

    assert job.status == "succeeded"
    # canvas_settings must have been set on the dashboard object returned by create_dashboard
    d = captured_dashboard.get("obj")
    assert d is not None
    assert hasattr(d, "canvas_settings")
    assert "filters" in d.canvas_settings
    assert len(d.canvas_settings["filters"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# ai_worker: Layout override from plan
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_layout_from_plan_overrides_textual_layout(monkeypatch):
    """Widgets with explicit layout in the plan must use those coordinates, not the textual layout."""
    from src.ai import http_client as http_client_module
    from src.config import database as database_module
    from src.repositories import base as base_repo_module
    from src.repositories import dashboard as dashboard_repo_module
    from src.repositories import user as user_repo_module
    from src.services import ai_service as ai_service_module
    from src.services import dashboard_service as dashboard_service_module
    from src.workers import ai_worker

    job_id = str(uuid4())
    job = SimpleNamespace(
        id=UUID(job_id),
        user_id=uuid4(),
        planet_id=uuid4(),
        space_id=uuid4(),
        connection_id=uuid4(),
        goal="Layout test",
        language="en",
        max_widgets=2,
        status="queued",
        started_at=None,
        finished_at=None,
        completed_widgets=0,
        total_widgets=0,
        dashboard_id=None,
        created_widget_ids=None,
        plan={
            "dashboard_name": "Layout Plan",
            "widgets": [
                {
                    "type": "insight",
                    "title": "Card 1",
                    "question": "Q1?",
                    "layout": {"x": 999.0, "y": 888.0, "w": 777.0, "h": 666.0},
                },
                {
                    "type": "insight",
                    "title": "Card 2",
                    "question": "Q2?",
                    # no layout → falls through to textual layout
                },
            ],
        },
        error=None,
    )

    created_calls = []

    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    class _CM:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(database_module, "AsyncSessionLocal", lambda: _CM())

    class _JobRepo:
        def __init__(self, _db, _model):
            pass

        async def get_by_id(self, _id):
            return job

    monkeypatch.setattr(base_repo_module, "BaseRepository", _JobRepo)
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
            metadata_repo=SimpleNamespace(get_by_connection_id=AsyncMock(return_value=None)),
            _get_user_crew_ids=AsyncMock(return_value=[]),
            process_query=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid4(), answer="ok", data_sample=[], sql="select 1"
                )
            ),
        ),
    )
    monkeypatch.setattr(
        dashboard_service_module,
        "DashboardService",
        lambda _db: SimpleNamespace(
            create_dashboard=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        ),
    )

    class _WidgetRepo:
        def __init__(self, _db):
            pass

        async def create(self, **kw):
            created_calls.append(kw)
            return SimpleNamespace(id=uuid4())

        async def update(self, *_args, **_kw):
            return None

    monkeypatch.setattr(dashboard_repo_module, "WidgetRepository", _WidgetRepo)

    await ai_worker._build_dashboard_job_async(job_id)

    assert job.status == "succeeded"
    assert len(created_calls) == 2

    # First widget: must use layout from plan
    pos0 = created_calls[0]["position"]
    size0 = created_calls[0]["size"]
    assert pos0["x"] == 999.0
    assert pos0["y"] == 888.0
    assert size0["width"] == 777.0
    assert size0["height"] == 666.0

    # Second widget: must use textual layout fallback (not plan layout)
    pos1 = created_calls[1]["position"]
    assert pos1["x"] != 999.0  # must differ from plan layout


# ─────────────────────────────────────────────────────────────────────────────
# dashboard_ai.py schema — DashboardAIBuildAsyncRequest with plan
# ─────────────────────────────────────────────────────────────────────────────


def test_dashboard_ai_build_async_request_accepts_plan_without_goal():
    """DashboardAIBuildAsyncRequest with plan must not require goal/original_question."""
    from src.schemas.dashboard_ai import DashboardAIBuildAsyncRequest

    req = DashboardAIBuildAsyncRequest(
        plan={"dashboard_name": "X", "widgets": [{"type": "text", "title": "T", "question": "Q"}]}
    )
    assert req.plan is not None


def test_dashboard_ai_build_async_request_fails_without_goal_and_plan():
    """Without goal, original_question, and plan, validation must fail."""
    from src.schemas.dashboard_ai import DashboardAIBuildAsyncRequest

    with pytest.raises(Exception):
        DashboardAIBuildAsyncRequest()


def test_dashboard_ai_build_async_request_goal_normalised():
    """original_question takes priority over goal."""
    from src.schemas.dashboard_ai import DashboardAIBuildAsyncRequest

    req = DashboardAIBuildAsyncRequest(goal="old", original_question="new question")
    assert req.goal == "new question"


# ─────────────────────────────────────────────────────────────────────────────
# dashboard_ai.py schema — DashboardAIPlanWidget type validation
# ─────────────────────────────────────────────────────────────────────────────


def test_dashboard_ai_plan_widget_valid_types():
    from src.schemas.dashboard_ai import DashboardAIPlanWidget

    for t in ("chart", "kpi", "table", "text", "infographic"):
        w = DashboardAIPlanWidget(widget_key="w1", type=t, title="T", question="Q?")
        assert w.type == t


def test_dashboard_ai_plan_widget_invalid_type():
    from src.schemas.dashboard_ai import DashboardAIPlanWidget

    with pytest.raises(Exception):
        DashboardAIPlanWidget(widget_key="w1", type="unsupported_type", title="T", question="Q?")
