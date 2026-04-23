"""Tests for automatic knowledge-graph ingestion of platform entities.

User request (Bug 6a phase 3): "Todos os dados adicionados em business
rules, events, relationships, connections precisam obrigatoriamente
serem imediatamente atualizado o embeddings, e os dados da plataforma
tb, como pessoas, spaces, crews, e etc..."

These tests confirm that the Space / Crew / Agent service each call
``ai_client.ingest_knowledge_graph`` on successful create, with a
payload carrying the owner/scope metadata the RAG needs to filter by
caller later.

Happy-path covered; the failure path (ai service down) is expected to
be logged + swallowed — regression for that is a separate
integration test because here we'd need to assert log contents.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.services.agent_service import AgentService
from src.services.crew_service import CrewService
from src.services.space_service import SpaceService


def _get_ingest_payloads(mock_ingest: AsyncMock) -> list[dict]:
    return [call.args[0] if call.args else call.kwargs.get("payload") for call in mock_ingest.await_args_list]


@pytest.mark.asyncio
async def test_create_space_ingests_space_into_knowledge_graph(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "src.services.space_service.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(return_value={"success": True}),
    ) as mock_ingest:
        res = await async_client.post(
            "/api/v1/spaces",
            json={"name": "Engineering", "description": "Engineering team", "color": "#4F46E5"},
            headers=headers,
        )
    assert res.status_code in (200, 201)
    body = res.json()
    mock_ingest.assert_awaited_once()
    payload = _get_ingest_payloads(mock_ingest)[0]
    assert payload["entity_type"] == "space"
    assert payload["id"] == body["id"]
    assert payload["name"] == "Engineering"
    assert payload["owner_user_id"] == str(test_user_with_tokens["user"].id)


@pytest.mark.asyncio
async def test_create_crew_ingests_crew_with_space_scope(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # First space (the ingest-on-space-create stub is fine to hit)
    with patch(
        "src.services.space_service.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(return_value={"success": True}),
    ):
        space_res = await async_client.post(
            "/api/v1/spaces", json={"name": "Sales"}, headers=headers
        )
    space_id = space_res.json()["id"]

    with patch(
        "src.services.crew_service.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(return_value={"success": True}),
    ) as mock_ingest:
        res = await async_client.post(
            "/api/v1/crews",
            json={"name": "Pipeline crew", "description": "Mid-market pipeline", "space_id": space_id},
            headers=headers,
        )
    assert res.status_code in (200, 201)
    body = res.json()
    mock_ingest.assert_awaited_once()
    payload = _get_ingest_payloads(mock_ingest)[0]
    assert payload["entity_type"] == "crew"
    assert payload["id"] == body["id"]
    assert payload["space_id"] == space_id
    assert payload["crew_id"] == body["id"]


@pytest.mark.asyncio
async def test_create_agent_personal_ingests_agent_with_owner(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    user_id = str(test_user_with_tokens["user"].id)
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "src.ai.http_client.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(return_value={"success": True}),
    ) as mock_ingest:
        res = await async_client.post(
            "/api/v1/agents/",
            json={
                "name": "Mine alone",
                "scope": "personal",
                "scope_id": user_id,
                "monitor_type": "context",
                "focus": "Anything relevant",
            },
            headers=headers,
        )
    assert res.status_code in (200, 201)
    body = res.json()
    mock_ingest.assert_awaited_once()
    payload = _get_ingest_payloads(mock_ingest)[0]
    assert payload["entity_type"] == "agent"
    assert payload["id"] == body["id"]
    assert payload["owner_user_id"] == user_id
    # Personal scope must NOT set space_id or crew_id — the RAG
    # depends on that to isolate Personal agents correctly.
    assert payload["space_id"] is None
    assert payload["crew_id"] is None


@pytest.mark.asyncio
async def test_create_space_still_succeeds_when_ingest_fails(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Breaking the AI side must never block platform entity creation —
    the user's Space/Crew/Agent must still get saved."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "src.services.space_service.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(side_effect=RuntimeError("AI service is down")),
    ):
        res = await async_client.post(
            "/api/v1/spaces", json={"name": "Resilient"}, headers=headers
        )
    assert res.status_code in (200, 201)
    assert res.json()["name"] == "Resilient"


@pytest.mark.asyncio
async def test_register_user_ingests_user_profile(db_session):
    """Self-registration via HTTP is disabled (SSO-only), so we call
    AuthenticationService.register directly. Confirms the user's own
    profile lands in the RAG with owner_user_id = self."""
    from src.schemas.user import UserCreate
    from src.services.auth_service import AuthenticationService

    service = AuthenticationService(db_session)
    with patch(
        "src.ai.http_client.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(return_value={"success": True}),
    ) as mock_ingest:
        user_resp = await service.register(UserCreate(
            email=f"ingest-{uuid4()}@example.com",
            password="password-123-456",
            name="Ada Ingest",
            role="owner",
        ))
    assert user_resp.name == "Ada Ingest"
    payloads = _get_ingest_payloads(mock_ingest)
    user_payloads = [p for p in payloads if p and p.get("entity_type") == "user"]
    assert len(user_payloads) >= 1
    assert user_payloads[0]["name"] == "Ada Ingest"


@pytest.mark.asyncio
async def test_create_page_ingests_page_with_owner_for_personal_type(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    user_id = str(test_user_with_tokens["user"].id)
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "src.ai.http_client.AIServiceHTTPClient.ingest_knowledge_graph",
        new=AsyncMock(return_value={"success": True}),
    ) as mock_ingest:
        res = await async_client.post(
            "/api/v1/pages",
            json={"name": "My dashboard", "type": "personal", "color": "#4F46E5"},
            headers=headers,
        )
    assert res.status_code in (200, 201)
    body = res.json()
    payloads = _get_ingest_payloads(mock_ingest)
    page_payloads = [p for p in payloads if p and p.get("entity_type") == "page"]
    assert len(page_payloads) == 1
    assert page_payloads[0]["id"] == body["id"]
    assert page_payloads[0]["owner_user_id"] == user_id
    assert page_payloads[0]["space_id"] is None
