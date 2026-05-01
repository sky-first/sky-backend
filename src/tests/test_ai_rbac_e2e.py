"""End-to-end RBAC tests for the AI query endpoint.

The two-axis RBAC model (post-rewrite):
  • Platform: owner / admin / member
  • Space:    owner / editor / viewer

This module pins down what every (platform_role, space_role) pair
can do at `POST /api/v1/ai/query` — the single most user-visible AI
surface. We assert authorization (gates) — the answer body is mocked
through the AI service "unavailable" path so we don't depend on the
LLM being up; the endpoint still returns 200 with status="error" so
the auth layer is what we're observing.

Cases covered:
  1. owner            → 200, AI accepted
  2. admin            → 200, AI accepted
  3. member (no space)              → 200 (Personal scope)
  4. owner|admin|member × owner|editor|viewer  → 200 (full 3×3)
  5. unauthenticated                → 401
  6. cross-tenant isolation         → user A's token doesn't resolve to user B

Adding a new case: append to the parametrize block; the fixture
auto-creates the user with the right role + (optionally) a Space they
are a member of.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from faker import Faker
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.repositories.user import UserRepository
from src.schemas.ai import AIQueryResponse
from src.services.onboarding_service import ensure_default_page_and_space


# Stub the AI service entry point. We test authorisation only, so the
# AI pipeline must not reach out to LLM/Redis/Ollama in CI. Returning a
# canned AIQueryResponse with status="success" lets us assert that the
# endpoint accepts the call (HTTP 200 + status not "error_unauthorised")
# without depending on infrastructure that doesn't exist in CI.
@pytest.fixture(autouse=True)
def _stub_ai_service():
    now = datetime.now(timezone.utc)
    canned = AIQueryResponse(
        id=uuid4(),
        question="stub",
        answer="ok",
        status="success",
        page_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    with patch(
        "src.services.ai_service.AIService.process_query",
        new=AsyncMock(return_value=canned),
    ):
        yield


# ── helpers ─────────────────────────────────────────────────────────────────


async def _make_user(
    db: AsyncSession,
    *,
    platform_role: str,
    name: str,
) -> User:
    repo = UserRepository(db)
    fake = Faker()
    user = await repo.create(
        email=fake.email(),
        password_hash=get_password_hash("Test@2024!"),
        name=name,
        role=platform_role,
    )
    await ensure_default_page_and_space(db, user)
    await db.commit()
    await db.refresh(user)
    return user


async def _attach_to_space(
    db: AsyncSession,
    *,
    user: User,
    context_role: str,
) -> Space:
    """Create a fresh Space owned by an admin and attach `user` with
    the given context role. Returns the Space."""
    admin = await _make_user(db, platform_role="admin", name="Space owner")
    space = Space(
        name=f"Demo Space {user.id.hex[:6]}",
        description="RBAC e2e test space",
        created_by=admin.id,
    )
    db.add(space)
    await db.flush()

    db.add(
        SpaceMember(
            space_id=space.id,
            user_id=user.id,
            role=context_role,
        )
    )
    await db.commit()
    await db.refresh(space)
    return space


def _token_for(user: User) -> str:
    return create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )


# ── parametric matrix ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def query_user(db_session, request):
    """Build a (User, optional Space) pair from the parametrize spec.

    spec is a tuple (platform_role, context_role | None, name).
    """
    platform_role, context_role, name = request.param
    user = await _make_user(db_session, platform_role=platform_role, name=name)
    space = None
    if context_role:
        space = await _attach_to_space(db_session, user=user, context_role=context_role)
    return {"user": user, "space": space, "token": _token_for(user)}


CASES = [
    # Platform-only (no Space membership) — owner/admin bypass Space gates;
    # member falls back to Personal scope.
    pytest.param(("owner", None, "Platform Owner"), id="owner-no-space"),
    pytest.param(("admin", None, "Platform Admin"), id="admin-no-space"),
    pytest.param(("member", None, "Member Personal"), id="member-personal"),
    # Full 3×3 platform × Space-role cross-axis. New vocabulary:
    # owner / editor / viewer (was commander / navigator / explorer).
    pytest.param(("owner", "owner", "Owner / Space Owner"), id="owner+space-owner"),
    pytest.param(("owner", "editor", "Owner / Editor"), id="owner+editor"),
    pytest.param(("owner", "viewer", "Owner / Viewer"), id="owner+viewer"),
    pytest.param(("admin", "owner", "Admin / Space Owner"), id="admin+space-owner"),
    pytest.param(("admin", "editor", "Admin / Editor"), id="admin+editor"),
    pytest.param(("admin", "viewer", "Admin / Viewer"), id="admin+viewer"),
    pytest.param(("member", "owner", "Member / Space Owner"), id="member+space-owner"),
    pytest.param(("member", "editor", "Demo Editor"), id="demo-member+editor"),
    pytest.param(("member", "viewer", "Member / Viewer"), id="member+viewer"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("query_user", CASES, indirect=True)
async def test_ai_query_authorized_for_every_role_pair(async_client, query_user):
    """Every authenticated (platform_role × context_role) pair should be
    accepted by `/ai/query`. AI service is mock-disabled in tests so the
    body has status="error", but the auth layer must say 200."""
    headers = {"Authorization": f"Bearer {query_user['token']}"}
    payload = {"question": "What is in this space?", "knowledge": []}

    resp = await async_client.post("/api/v1/ai/query", json=payload, headers=headers)
    assert resp.status_code == 200, (
        f"role pair was rejected at the gate: status={resp.status_code} "
        f"body={resp.text}"
    )
    body = resp.json()
    # Status will be "error" (mock disabled) or "success" (LLM up). Either is
    # fine — both prove authorisation passed.
    assert body.get("status") in ("error", "success"), body


@pytest.mark.asyncio
async def test_ai_query_rejects_unauthenticated(async_client):
    resp = await async_client.post(
        "/api/v1/ai/query",
        json={"question": "Anything", "knowledge": []},
    )
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_ai_query_token_isolation(async_client, db_session):
    """Token from user A must NOT be accepted as user B. Build two
    independent users; send Alice's token; the resolved user_id on
    /api/v1/auth/me must be Alice's, never Bob's."""
    user_a = await _make_user(db_session, platform_role="member", name="Alice")
    user_b = await _make_user(db_session, platform_role="member", name="Bob")

    resp_a = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_token_for(user_a)}"},
    )
    resp_b = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_token_for(user_b)}"},
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["id"] == str(user_a.id)
    assert resp_b.json()["id"] == str(user_b.id)
    assert resp_a.json()["id"] != resp_b.json()["id"]


@pytest.mark.asyncio
async def test_ai_query_member_navigator_matches_demo_setup(async_client, db_session):
    """The Demo flow gives a visitor `user.role = "member"` and a Space
    membership with `space_members.role = "navigator"`. This pin asserts
    that exact pair is accepted by the AI gate, the same way it has to
    be in production for `demo.skyfirstlabs.com` to work."""
    demo_user = await _make_user(db_session, platform_role="member", name="Demo Visitor")
    await _attach_to_space(db_session, user=demo_user, context_role="navigator")
    token = _token_for(demo_user)

    resp = await async_client.post(
        "/api/v1/ai/query",
        json={"question": "What's in this space?", "knowledge": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") in ("error", "success"), body
