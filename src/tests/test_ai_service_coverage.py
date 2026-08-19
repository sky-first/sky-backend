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
    widget = Widget(
        id=uuid.uuid4(),
        title="AI Test Widget",
        type="ai-box",
        position={"x": 0, "y": 0},
        size={"width": 100, "height": 100},
        page_id=page.id,
        created_by=user.id,
    )
    db_session.add(user)
    db_session.add(space)
    db_session.add(page)
    db_session.add(widget)
    await db_session.flush()
    return user, space, page, widget


@pytest.mark.asyncio
async def test_process_query_returns_empty_state_when_no_connection_available(db_session):
    # When no data connection is wired up the no-connection fast-fail
    # guard (work/ai-no-connection-fastfail) intercepts before the AI
    # engine runs, returning status="completed" with an empty-state
    # answer pointing the user to Sources → Connect. The endpoint still
    # replies 200 with a user-facing friendly message.
    #
    # CI default is AI_SERVICE_TYPE=mock so service.real_ai is None and
    # the guard branch (which lives INSIDE `if self.real_ai:`) never
    # executes. Local devs have AI_SERVICE_TYPE=real in .env.local so it
    # does fire there. We force real_ai to a truthy sentinel so the test
    # exercises the same branch in both environments.
    user, space, page, widget = await _seed_ai_fixtures(db_session)
    service = AIService(db_session)
    service.real_ai = object()  # type: ignore[assignment]

    query_data = AIQueryRequest(
        question="What is the meaning of life?",
        knowledge=[],
        page_id=page.id,
    )
    response = await service.process_query(user.id, query_data)
    assert response.status == "completed"
    assert response.answer is not None
    # A frase deixou de ser uma só em inglês: depende de quem pergunta e da
    # língua dele. O que este teste garante continua a ser o mesmo — que há
    # uma resposta útil em vez de silêncio ou de um erro.
    from src.core.locale import get_message

    assert response.answer in (
        get_message("space_has_no_data_can_connect", "pt"),
        get_message("space_has_no_data_ask_access", "pt"),
        get_message("space_has_no_data_can_connect", "en"),
        get_message("space_has_no_data_ask_access", "en"),
    )


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


@pytest.mark.asyncio
async def test_process_query_returns_empty_state_when_no_connection(db_session, monkeypatch):
    """No-connection fast-fail (work/ai-no-connection-fastfail).

    When AI_SERVICE_TYPE=real but the user has zero connections, the guard
    must short-circuit with status="completed" and an empty-state answer
    pointing the user to Sources → Connect. Without this guard the real
    AI engine would hang for 90s, surfacing as "AI didn't respond in time"
    on the chat UI.
    """
    user, space, page, widget = await _seed_ai_fixtures(db_session)
    service = AIService(db_session)

    # Force the real_ai branch on without standing up the real engine —
    # we just need a truthy value so the guard executes.
    service.real_ai = object()

    # Make every connection-resolution helper return None so the guard
    # branch fires.
    async def _none(*args, **kwargs):
        return None

    async def _empty_list(*args, **kwargs):
        return []

    monkeypatch.setattr(service, "_resolve_connection_id_from_tables", _none)
    monkeypatch.setattr(service, "_get_first_active_connection_for_space", _none)
    monkeypatch.setattr(service, "_get_first_active_connection", _none)
    monkeypatch.setattr(service, "_get_user_dataset_connection_ids", _empty_list)
    monkeypatch.setattr(service, "_get_best_connection_for_question", _none)

    query_data = AIQueryRequest(
        question="what is our retention?",
        knowledge=[],
        page_id=page.id,
    )
    response = await service.process_query(user.id, query_data)

    assert response.status == "completed"
    assert response.answer is not None
    # Mesma razão do teste acima: a frase deixou de ser uma só em inglês.
    from src.core.locale import get_message as _msg

    assert response.answer in (
        _msg("space_has_no_data_can_connect", "pt"),
        _msg("space_has_no_data_ask_access", "pt"),
        _msg("space_has_no_data_can_connect", "en"),
        _msg("space_has_no_data_ask_access", "en"),
    )
