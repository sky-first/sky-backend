"""Coverage boost tests for AIService."""

import pytest
import uuid
from src.services.ai_service import AIService
from src.schemas.ai import AIQueryRequest, ChatMessageRequest
from src.models.ai import AIQuery, AIHistory, ChatMessage
from src.models.space import Space
from src.models.page import Page
from src.models.widget import Widget
from src.models.user import User
from src.core.exceptions import ServiceUnavailableError


async def _seed_ai_fixtures(db_session):
    user = User(id=uuid.uuid4(), email=f"ai.{uuid.uuid4().hex[:8]}@example.com", role="user", password_hash="dummy", name="Test User")
    space = Space(id=uuid.uuid4(), name="AI Test Space", created_by=user.id)
    page = Page(id=uuid.uuid4(), name="AI Test Page", space_id=space.id, type="team", color="#000000", owner_id=user.id)
    from src.models.page import Page
    dashboard = Dashboard(id=uuid.uuid4(), name="AI Test Dash", page_id=page.id, created_by=user.id)
    widget = Widget(
        id=uuid.uuid4(),
        title="AI Test Widget",
        type="ai-box",
        position={"x": 0, "y": 0},
        size={"width": 100, "height": 100},
        dashboard_id=dashboard.id,
        created_by=user.id,
    )
    db_session.add(user)
    db_session.add(space)
    db_session.add(page)
    db_session.add(dashboard)
    db_session.add(widget)
    await db_session.flush()
    return user, space, page, widget


@pytest.mark.asyncio
async def test_process_query_marks_error_when_ai_unavailable(db_session):
    # Mock AI was intentionally disabled (see PR: fix-agents-500-and-disable-ai-mock).
    # process_query catches the ServiceUnavailableError internally and returns a response with status="error"
    # so the endpoint still replies 200 with a user-facing friendly message + error_key for the error banner.
    user, space, page, widget = await _seed_ai_fixtures(db_session)
    service = AIService(db_session)

    query_data = AIQueryRequest(
        question="What is the meaning of life?",
        knowledge=[],
        page_id=page.id,
    )
    response = await service.process_query(user.id, query_data)
    assert response.status == "error"


@pytest.mark.asyncio
async def test_send_chat_message_raises_when_ai_unavailable(db_session):
    # send_chat_message's fallback path also routes through the disabled mock, so the ServiceUnavailableError propagates.
    # The endpoint layer translates this to a 503 for the frontend PlatformErrorBanner.
    user, space, page, widget = await _seed_ai_fixtures(db_session)
    service = AIService(db_session)

    chat_data = ChatMessageRequest(
        message="Hello AI",
        widget_id=widget.id,
        page_id=page.id,
    )
    with pytest.raises(ServiceUnavailableError):
        await service.send_chat_message(user.id, chat_data)


@pytest.mark.asyncio
async def test_ai_service_history_basic(db_session):
    user, space, page, widget = await _seed_ai_fixtures(db_session)
    service = AIService(db_session)

    from src.schemas.ai import CreateHistoryRequest
    await service.create_history(user.id, CreateHistoryRequest(
        page_id=page.id,
        query="Test query",
        answer="Test answer",
        category="General",
    ))
    history = await service.get_history(user.id, page.id)
    assert len(history) >= 1

@pytest.mark.asyncio
async def test_ai_service_helpers(db_session):
    user_id = uuid.uuid4()
    service = AIService(db_session)
    
    # Test _get_first_active_connection when none exists
    conn = await service._get_first_active_connection(user_id)
    assert conn is None
    
    # Test _get_user_crew_ids with no space
    crews = await service._get_user_crew_ids(user_id, None)
    assert crews == []
