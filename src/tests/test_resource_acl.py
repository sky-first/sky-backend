"""Tests for Phase 2 — resource_acl table + Share endpoints + ACL-aware resolver.

Coverage:
  • Authorization.can honours an explicit user grant (Member with NO Space
    membership but viewer-grant on a Connection → can read it)
  • Authorization.can honours tenant-wide grants (no user grant, but a
    tenant grant on a Dashboard → every Member can view)
  • Resource ACL grant overrides the Space-default level (user is Space
    viewer + has explicit editor grant on a specific resource → editor)
  • POST /resources/{type}/{id}/share creates and re-upserts a grant
  • GET  /resources/{type}/{id}/acl lists grants
  • DELETE /resources/{type}/{id}/share/{grant_id} revokes
  • Member cannot share a resource they don't own (no owner grant)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.resource_acl import ResourceAcl
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.repositories.user import UserRepository
from src.services.authorization import Authorization


async def _user(db: AsyncSession, *, role: str, name: str) -> User:
    return await UserRepository(db).create(
        email=f"{uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name=name,
        role=role,
    )


def _token(user: User) -> str:
    return create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )


# ── Resolver: explicit grants ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_grant_lets_member_read_connection(db_session):
    user = await _user(db_session, role="member", name="M")
    conn_id = uuid4()
    db_session.add(
        ResourceAcl(
            resource_type="connection",
            resource_id=conn_id,
            principal_type="user",
            principal_id=user.id,
            level="viewer",
        )
    )
    await db_session.commit()
    auth = Authorization(db_session)
    assert (
        await auth.can(
            user, "connections.view", resource_type="connection", resource_id=conn_id
        )
        is True
    )


@pytest.mark.asyncio
async def test_tenant_grant_lets_every_member_read(db_session):
    user = await _user(db_session, role="member", name="M")
    dash_id = uuid4()
    db_session.add(
        ResourceAcl(
            resource_type="dashboard",
            resource_id=dash_id,
            principal_type="tenant",
            principal_id=None,
            level="viewer",
        )
    )
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            user, "pages.view", resource_type="dashboard", resource_id=dash_id
        )
        is True
    )


@pytest.mark.asyncio
async def test_explicit_grant_overrides_space_viewer_with_editor(db_session):
    """User is Viewer in Space S; resource X (in another Space, doesn't
    matter) has an explicit editor-level grant for this user. The
    user can edit X even though they couldn't if going by Space alone."""
    creator = await _user(db_session, role="admin", name="C")
    user = await _user(db_session, role="member", name="V")
    space = Space(name=f"S {uuid4().hex[:6]}", created_by=creator.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=user.id, role="viewer"))
    conn_id = uuid4()
    db_session.add(
        ResourceAcl(
            resource_type="connection",
            resource_id=conn_id,
            principal_type="user",
            principal_id=user.id,
            level="editor",
        )
    )
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            user,
            # `connections.sync` e não `.create`: este teste é sobre a
            # concessão explícita sobrepor-se ao papel de espaço, e a chave
            # era o veículo. `.create` passou a exigir dono do projeto —
            # ligar dados novos é a fronteira que o pedido de acesso guarda —
            # enquanto sincronizar uma ligação que já existe continua a ser
            # de editor, que é o nível desta concessão.
            "connections.sync",
            space_id=space.id,
            resource_type="connection",
            resource_id=conn_id,
        )
        is True
    )


@pytest.mark.asyncio
async def test_no_grant_no_membership_denies(db_session):
    user = await _user(db_session, role="member", name="M")
    assert (
        await Authorization(db_session).can(
            user,
            "connections.view",
            resource_type="connection",
            resource_id=uuid4(),
        )
        is False
    )


# ── HTTP endpoints ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_share_resource(async_client, db_session):
    owner = await _user(db_session, role="owner", name="O")
    target = await _user(db_session, role="member", name="T")
    conn_id = uuid4()
    headers = {"Authorization": f"Bearer {_token(owner)}"}
    payload = {
        "principal_type": "user",
        "principal_id": str(target.id),
        "level": "viewer",
    }
    r = await async_client.post(
        f"/api/v1/resources/connection/{conn_id}/share",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["resource_type"] == "connection"
    assert body["principal_type"] == "user"
    assert body["level"] == "viewer"


@pytest.mark.asyncio
async def test_share_is_idempotent_upsert(async_client, db_session):
    owner = await _user(db_session, role="owner", name="O")
    target = await _user(db_session, role="member", name="T")
    conn_id = uuid4()
    headers = {"Authorization": f"Bearer {_token(owner)}"}

    payload1 = {
        "principal_type": "user",
        "principal_id": str(target.id),
        "level": "viewer",
    }
    r1 = await async_client.post(
        f"/api/v1/resources/connection/{conn_id}/share",
        json=payload1,
        headers=headers,
    )
    assert r1.status_code == 201
    grant_id_1 = r1.json()["id"]

    # Upgrade to editor — same (resource, principal) pair → upsert.
    payload2 = {**payload1, "level": "editor"}
    r2 = await async_client.post(
        f"/api/v1/resources/connection/{conn_id}/share",
        json=payload2,
        headers=headers,
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == grant_id_1
    assert r2.json()["level"] == "editor"


@pytest.mark.asyncio
async def test_list_acl_returns_all_grants(async_client, db_session):
    owner = await _user(db_session, role="owner", name="O")
    headers = {"Authorization": f"Bearer {_token(owner)}"}
    conn_id = uuid4()
    db_session.add(
        ResourceAcl(
            resource_type="connection",
            resource_id=conn_id,
            principal_type="tenant",
            level="viewer",
        )
    )
    await db_session.commit()

    r = await async_client.get(
        f"/api/v1/resources/connection/{conn_id}/acl", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["principal_type"] == "tenant"


@pytest.mark.asyncio
async def test_member_without_grant_cannot_share(async_client, db_session):
    user = await _user(db_session, role="member", name="M")
    headers = {"Authorization": f"Bearer {_token(user)}"}
    conn_id = uuid4()
    payload = {
        "principal_type": "user",
        "principal_id": str(uuid4()),
        "level": "viewer",
    }
    r = await async_client.post(
        f"/api/v1/resources/connection/{conn_id}/share",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_revoke_grant_deletes_row(async_client, db_session):
    owner = await _user(db_session, role="owner", name="O")
    headers = {"Authorization": f"Bearer {_token(owner)}"}
    conn_id = uuid4()
    grant = ResourceAcl(
        resource_type="connection",
        resource_id=conn_id,
        principal_type="tenant",
        level="viewer",
    )
    db_session.add(grant)
    await db_session.commit()
    await db_session.refresh(grant)

    r = await async_client.delete(
        f"/api/v1/resources/connection/{conn_id}/share/{grant.id}",
        headers=headers,
    )
    assert r.status_code == 204
    list_r = await async_client.get(
        f"/api/v1/resources/connection/{conn_id}/acl", headers=headers
    )
    assert list_r.json()["total"] == 0
