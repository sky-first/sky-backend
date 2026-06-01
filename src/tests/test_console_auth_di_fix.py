"""``require_sky_team`` must use the same DB session as the rest of
the request so the user-repo lookup actually runs.

Until this fix landed, the dependency was calling
``get_current_user`` as a plain function, leaving its own
``Depends(get_db_session)`` default unresolved. The user-repo call
then raised ``AttributeError`` on the un-resolved Depends object, the
catch-all swallowed the exception, ``user`` ended up ``None`` and
every Console route returned 401 even for legitimate Sky operators.

These tests pin the contract end-to-end via the real FastAPI test
client so a regression of the same shape would fail loudly.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.main import app
from src.models.user import User
from src.repositories.user import UserRepository

# The Console host guard rejects any request whose Host header is not in the
# allowed-hosts list (_allowed_console_hosts).  The shared ``async_client``
# fixture uses base_url="http://test" which doesn't match, so every console
# route returns 404.  We create a module-local fixture that uses
# base_url="http://localhost" — "localhost" IS in the default allowed set.
@pytest.fixture
async def console_client(db_session):
    from src.api.deps import get_db_session
    from src.config.database import get_db

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_db] = _override_session
    app.dependency_overrides[get_db_session] = _override_session

    async with AsyncClient(app=app, base_url="http://localhost") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_console_me_with_sky_operator_jwt_returns_200(
    console_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A user whose row has ``is_sky_operator = True`` and a valid JWT
    must get a 200 from ``/api/console/v1/me`` — the regression we shipped
    came from this returning 401 in production for everyone."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email=f"operator-{uuid.uuid4().hex[:8]}@skyfirstlabs.com",
        password_hash="x",
        name="Op Test",
        role="admin",
        email_verified=True,
    )
    user.is_sky_operator = True
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})

    resp = await console_client.get(
        "/api/console/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == user.email
    assert body["is_sky_team"] is True


@pytest.mark.asyncio
async def test_console_me_without_token_returns_401_unauthenticated(
    console_client: AsyncClient,
) -> None:
    """No JWT → 401 with the ``unauthenticated`` shape that the FE
    useAccess hook expects, so it can route to ``/login`` rather than
    silently looping."""
    resp = await console_client.get("/api/console/v1/me")
    assert resp.status_code == 401
    # The custom error wrapper inlines the original detail dict as a
    # string inside ``error.message``; ``unauthenticated`` must appear
    # somewhere in the body so the FE useAccess hook can route by it.
    assert "unauthenticated" in resp.text


@pytest.mark.asyncio
async def test_console_me_with_non_operator_jwt_returns_403_sky_team_required(
    console_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A perfectly valid JWT for a non-operator user must surface as 403
    ``sky_team_required``, NOT 401. The FE distinguishes the two so a
    customer who lands on /console after SSO is bounced to /page with
    an "access denied" landing instead of being sent back to /login."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email=f"customer-{uuid.uuid4().hex[:8]}@gbtsolutions.pt",
        password_hash="x",
        name="External user",
        role="user",
        email_verified=True,
    )
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})

    resp = await console_client.get(
        "/api/console/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    # ``sky_team_required`` is the marker the FE useAccess hook greps
    # for to decide between /login (401) and /page?reason=… (403).
    assert "sky_team_required" in resp.text
