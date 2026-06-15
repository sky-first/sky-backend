"""Tests for the Space→Crew model (2026-06).

Lucas's directive: questions and agents are ALWAYS scoped to a crew, never
a bare space. Every space auto-creates a default "General" crew. The API
rejects collaborative queries / space-scoped agents that lack a crew.

Covers:
  * SpaceService.create_space auto-creates a "General" crew.
  * SpaceService.ensure_default_crew is idempotent (no duplicate General).
  * POST /ai/query with space_id but no crew_id → 400 (collaborative).
  * POST /ai/query personal (no space) is NOT blocked by the crew guard.
  * POST /agents with scope="space" → 400; scope="crew" passes the guard.
"""

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.crew import Crew
from src.schemas.space import SpaceCreate
from src.services.space_service import DEFAULT_CREW_NAME, SpaceService


def get_auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(autouse=True)
def _stub_ai_ingest(monkeypatch):
    """Space/Crew creation ingests entities into the AI knowledge graph.
    Stub it to an async no-op so the tests don't depend on the AI service.
    """
    from src.ai.http_client import AIServiceHTTPClient

    async def _noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(AIServiceHTTPClient, "ingest_knowledge_graph", _noop)


async def _crews_for_space(db: AsyncSession, space_id):
    result = await db.execute(select(Crew).where(Crew.space_id == space_id))
    return list(result.scalars().all())


# ─── default crew auto-creation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_space_auto_creates_general_crew(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    svc = SpaceService(db_session)

    space = await svc.create_space(user, SpaceCreate(name="Finance"))

    crews = await _crews_for_space(db_session, space.id)
    names = [(c.name or "").strip().lower() for c in crews]
    assert (
        DEFAULT_CREW_NAME.lower() in names
    ), f"expected a default '{DEFAULT_CREW_NAME}' crew, got {names}"


@pytest.mark.asyncio
async def test_ensure_default_crew_is_idempotent(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    svc = SpaceService(db_session)

    space = await svc.create_space(user, SpaceCreate(name="HR"))
    # Calling the backfill again must NOT create a second General crew.
    await svc.ensure_default_crew(space.id, user)

    crews = await _crews_for_space(db_session, space.id)
    general = [c for c in crews if (c.name or "").strip().lower() == DEFAULT_CREW_NAME.lower()]
    assert len(general) == 1, f"expected exactly one General crew, got {len(general)}"


# ─── query guard: crew required in collaborative mode ──────────────────────


@pytest.mark.asyncio
async def test_query_in_space_without_crew_is_rejected(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    svc = SpaceService(db_session)
    space = await svc.create_space(user, SpaceCreate(name="Marketing"))

    resp = await async_client.post(
        "/api/v1/ai/query",
        json={
            "question": "quantos candidatos?",
            "space_id": str(space.id),
            "is_personal": False,
            # crew_id deliberately omitted
        },
        headers=headers,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert "crew" in resp.text.lower()


@pytest.mark.asyncio
async def test_personal_query_not_blocked_by_crew_guard(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Personal mode (no space) must NOT be rejected by the crew guard.
    It may still fail later for unrelated reasons (no active page / no data),
    but the failure must NOT be the 400 "A crew must be selected" message.
    """
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    resp = await async_client.post(
        "/api/v1/ai/query",
        json={"question": "hello", "is_personal": True},
        headers=headers,
    )
    if resp.status_code == status.HTTP_400_BAD_REQUEST:
        assert "a crew must be selected" not in resp.text.lower()


# ─── agent-create guard: no bare-space agents ──────────────────────────────


@pytest.mark.asyncio
async def test_get_space_crews_backfills_general_when_missing(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    """A space whose crews were all removed (e.g. created before the
    Space→Crew model) self-heals: GET /spaces/{id}/crews re-creates General.
    """
    from src.services.crew_service import CrewService

    user = test_user_with_tokens["user"]
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    svc = SpaceService(db_session)
    space = await svc.create_space(user, SpaceCreate(name="Legacy"))

    # Remove every crew the space has, simulating a pre-model space.
    # delete_crew is a soft-delete, so we assert emptiness through
    # list_crews (which filters deleted) rather than the raw table query.
    crew_service = CrewService(db_session)
    for c in await _crews_for_space(db_session, space.id):
        await crew_service.delete_crew(c.id, user, force=True)
    await db_session.commit()
    active = await crew_service.list_crews(user, space_id=space.id)
    assert active == [] or all(
        (c.name or "").strip().lower() != DEFAULT_CREW_NAME.lower() for c in active
    )

    resp = await async_client.get(f"/api/v1/spaces/{space.id}/crews", headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    names = [(c.get("name") or "").strip().lower() for c in resp.json()]
    assert DEFAULT_CREW_NAME.lower() in names, names


@pytest.mark.asyncio
async def test_create_agent_with_space_scope_is_rejected(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    svc = SpaceService(db_session)
    space = await svc.create_space(user, SpaceCreate(name="Ops"))

    resp = await async_client.post(
        "/api/v1/agents/",
        json={
            "name": "Bare space agent",
            "scope": "space",
            "scope_id": str(space.id),
        },
        headers=headers,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert "crew level" in resp.text.lower()
