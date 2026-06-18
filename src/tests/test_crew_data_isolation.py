"""Regression guard: crew-scoped data access is fail-closed and isolated.

A crew sees ONLY the tables explicitly granted to it via CrewTable — it never
inherits "all tables" from the space, and never sees a sibling crew's tables.
This locks in the fix for the cross-crew data leak (the AI was filtering by
``crew_id``, but with grants missing every crew saw everything).
"""

import uuid

import pytest

from src.models.connection import DataConnection
from src.models.crew import Crew, CrewTable
from src.models.space import Space
from src.models.user import User
from src.services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_crew_table_access_is_fail_closed_and_isolated(db_session):
    user = User(
        id=uuid.uuid4(),
        email="iso@example.com",
        role="user",
        password_hash="x",
        name="Iso",
    )
    conn = DataConnection(
        id=uuid.uuid4(),
        name="C",
        connector_id="postgres",
        config={},
        created_by=user.id,
    )
    space = Space(
        id=uuid.uuid4(),
        name="S",
        created_by=user.id,
        privacy="private",
        sensitivity="internal",
        is_demo=False,
    )
    db_session.add_all([user, conn, space])
    await db_session.flush()

    crew_a = Crew(id=uuid.uuid4(), name="A", space_id=space.id, created_by=user.id)
    crew_b = Crew(id=uuid.uuid4(), name="B", space_id=space.id, created_by=user.id)
    crew_empty = Crew(id=uuid.uuid4(), name="E", space_id=space.id, created_by=user.id)
    db_session.add_all([crew_a, crew_b, crew_empty])
    await db_session.flush()

    db_session.add_all(
        [
            CrewTable(crew_id=crew_a.id, connection_id=conn.id, table_name="orders"),
            CrewTable(crew_id=crew_a.id, connection_id=conn.id, table_name="customers"),
            CrewTable(crew_id=crew_b.id, connection_id=conn.id, table_name="payments"),
        ]
    )
    await db_session.flush()

    svc = PermissionService(db_session)
    a = await svc.get_authorized_tables(user.id, conn.id, space_id=space.id, crew_ids=[crew_a.id])
    b = await svc.get_authorized_tables(user.id, conn.id, space_id=space.id, crew_ids=[crew_b.id])
    empty = await svc.get_authorized_tables(
        user.id, conn.id, space_id=space.id, crew_ids=[crew_empty.id]
    )

    # Each crew sees only its own grants...
    assert a == ["customers", "orders"]
    assert b == ["payments"]
    # ...a crew with no CrewTable rows sees nothing (fail-closed, never "all")...
    assert empty == []
    # ...and never a sibling crew's tables (no cross-crew leak).
    assert "payments" not in a
    assert "orders" not in b

    # Personal mode is ADDITIVE: crew_ids means "all the user's crews", so it
    # unions every crew's grants (here A + B) instead of fail-closing to one.
    personal = await svc.get_authorized_tables(
        user.id, conn.id, crew_ids=[crew_a.id, crew_b.id], is_personal=True
    )
    assert set(personal) == {"customers", "orders", "payments"}
