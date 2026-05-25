"""Tests for per-space column visibility (SpaceTable.hidden_columns).

The column is a list-shaped JSON blob. Empty list = every column
visible. These tests pin the normalisation rules (trim whitespace,
dedupe, preserve order) and the ownership guard.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.space import Space, SpaceTable
from src.services.space_service import SpaceService


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_space_table(db: AsyncSession, user_id, connection_id=None):
    space = Space(name="Marketing", created_by=user_id)
    db.add(space)
    await db.flush()
    link = SpaceTable(
        space_id=space.id,
        connection_id=connection_id or uuid.uuid4(),
        table_name="customers",
        schema_name="public",
        hidden_columns=[],
    )
    db.add(link)
    await db.flush()
    return space, link


@pytest.mark.asyncio
async def test_set_hidden_columns_replaces_list(db_session: AsyncSession, test_user: dict):
    user = test_user["user"]
    space, link = await _make_space_table(db_session, user.id)

    svc = SpaceService(db_session)
    await svc.set_space_table_hidden_columns(
        space.id, link.connection_id, link.table_name, link.schema_name,
        ["email", "phone"], user,
    )
    await db_session.refresh(link)
    assert link.hidden_columns == ["email", "phone"]

    await svc.set_space_table_hidden_columns(
        space.id, link.connection_id, link.table_name, link.schema_name,
        ["ssn"], user,
    )
    await db_session.refresh(link)
    assert link.hidden_columns == ["ssn"]


@pytest.mark.asyncio
async def test_set_hidden_columns_dedupes_and_trims(db_session: AsyncSession, test_user: dict):
    user = test_user["user"]
    space, link = await _make_space_table(db_session, user.id)
    svc = SpaceService(db_session)

    await svc.set_space_table_hidden_columns(
        space.id, link.connection_id, link.table_name, link.schema_name,
        ["email", " email ", "", "phone", "phone"], user,
    )
    await db_session.refresh(link)
    assert link.hidden_columns == ["email", "phone"]


@pytest.mark.asyncio
async def test_empty_list_clears_hidden_columns(db_session: AsyncSession, test_user: dict):
    user = test_user["user"]
    space, link = await _make_space_table(db_session, user.id)
    link.hidden_columns = ["email"]
    await db_session.flush()

    svc = SpaceService(db_session)
    await svc.set_space_table_hidden_columns(
        space.id, link.connection_id, link.table_name, link.schema_name,
        [], user,
    )
    await db_session.refresh(link)
    assert link.hidden_columns == []


@pytest.mark.asyncio
async def test_non_owner_non_admin_is_forbidden(
    db_session: AsyncSession, test_user: dict,
):
    user = test_user["user"]
    space, link = await _make_space_table(db_session, user.id)

    other = SimpleNamespace(id=uuid.uuid4(), role="user")
    svc = SpaceService(db_session)
    from src.core.exceptions import ForbiddenError
    with pytest.raises(ForbiddenError):
        await svc.set_space_table_hidden_columns(
            space.id, link.connection_id, link.table_name, link.schema_name,
            ["email"], other,
        )


@pytest.mark.asyncio
async def test_admin_bypass_works(
    db_session: AsyncSession, test_user: dict,
):
    # Space owned by `test_user`, called by someone else who is admin.
    owner = test_user["user"]
    space, link = await _make_space_table(db_session, owner.id)
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin")

    svc = SpaceService(db_session)
    await svc.set_space_table_hidden_columns(
        space.id, link.connection_id, link.table_name, link.schema_name,
        ["email"], admin,
    )
    await db_session.refresh(link)
    assert link.hidden_columns == ["email"]


# ─── Endpoint end-to-end ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_updates_hidden_columns(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession,
):
    user = test_user_with_tokens["user"]
    user.role = "admin"
    await db_session.commit()
    space, link = await _make_space_table(db_session, user.id)
    await db_session.commit()

    resp = await async_client.patch(
        f"/api/v1/spaces/{space.id}/connections/{link.connection_id}/tables/{link.table_name}/columns"
        f"?schema_name={link.schema_name}",
        headers=_auth(test_user_with_tokens["access_token"]),
        json={"hidden_columns": ["email", "ssn"]},
    )
    assert resp.status_code == 200
    await db_session.refresh(link)
    assert link.hidden_columns == ["email", "ssn"]


@pytest.mark.asyncio
async def test_endpoint_400s_on_non_list(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession,
):
    user = test_user_with_tokens["user"]
    user.role = "admin"
    await db_session.commit()
    space, link = await _make_space_table(db_session, user.id)
    await db_session.commit()

    resp = await async_client.patch(
        f"/api/v1/spaces/{space.id}/connections/{link.connection_id}/tables/{link.table_name}/columns",
        headers=_auth(test_user_with_tokens["access_token"]),
        json={"hidden_columns": "email,ssn"},
    )
    assert resp.status_code == 400
