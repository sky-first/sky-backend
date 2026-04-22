"""Coverage boost tests for AIService."""

import pytest
import uuid
from src.services.ai_service import AIService
from src.schemas.ai import AIQueryRequest, ChatMessageRequest
from src.models.ai import AIQuery, AIHistory, ChatMessage
from src.models.space import Space
from src.models.page import Page
from src.models.dashboard import Widget
from src.models.user import User

@pytest.mark.asyncio
async def test_ai_service_basic(db_session):
    user = User(id=uuid.uuid4(), email="ai.test@example.com", role="user", password_hash="dummy", name="Test User")
    space = Space(id=uuid.uuid4(), name="AI Test Space", created_by=user.id)
    page = Page(id=uuid.uuid4(), name="AI Test Page", space_id=space.id, type="team", color="#000000", owner_id=user.id)
    from src.models.dashboard import Dashboard
    dashboard = Dashboard(id=uuid.uuid4(), name="AI Test Dash", page_id=page.id, created_by=user.id)
    widget = Widget(
        id=uuid.uuid4(), 
        title="AI Test Widget", 
        type="ai-box",
        position={"x": 0, "y": 0},
        size={"width": 100, "height": 100},
        dashboard_id=dashboard.id, 
        created_by=user.id
    )
    db_session.add(user)
    db_session.add(space)
    db_session.add(page)
    db_session.add(dashboard)
    db_session.add(widget)
    await db_session.flush()

    service = AIService(db_session)
    
    # 1. Process Query
    query_data = AIQueryRequest(
        question="What is the meaning of life?",
        knowledge=[],
        page_id=page.id
    )
    # This will likely use mock_ai because self.real_ai is None in tests (usually)
    response = await service.process_query(user.id, query_data)
    assert response.status == "completed"
    
    # 2. Send Chat Message
    chat_data = ChatMessageRequest(
        message="Hello AI",
        widget_id=widget.id,
        page_id=page.id
    )
    chat_response = await service.send_chat_message(user.id, chat_data)
    assert "Hello AI" in chat_response.content
    
    # 3. History & Feedbacks
    from src.schemas.ai import CreateHistoryRequest
    await service.create_history(user.id, CreateHistoryRequest(
        page_id=page.id,
        query="Test query",
        answer="Test answer",
        category="General"
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
