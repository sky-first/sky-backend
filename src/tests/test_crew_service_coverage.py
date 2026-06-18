"""Coverage boost tests for CrewService."""

import uuid

import pytest
from sqlalchemy import select

from src.models.connection import DataConnection
from src.models.crew import CrewConnection, CrewTable
from src.models.space import Space, SpaceConnection, SpaceTable
from src.models.user import User
from src.schemas.crew import (
    CrewCreate,
    CrewMemberCreate,
    CrewMemberUpdate,
    CrewTableSelection,
    CrewUpdate,
)
from src.services.crew_service import CrewService


@pytest.mark.asyncio
async def test_crew_service_lifecycle(db_session):
    user = User(
        id=uuid.uuid4(),
        email="crew.test@example.com",
        role="user",
        password_hash="dummy",
        name="Test User",
    )
    space = Space(id=uuid.uuid4(), name="Crew Test Space", created_by=user.id)
    db_session.add(user)
    db_session.add(space)
    await db_session.flush()

    service = CrewService(db_session)

    # 1. Create Crew
    create_data = CrewCreate(name="Service Test Crew", space_id=space.id)
    crew = await service.create_crew(user, create_data)
    assert crew.name == "Service Test Crew"

    # 2. List Crews
    crews = await service.list_crews(user, space_id=space.id)
    assert len(crews) >= 1

    # 3. Get Crew
    crew_get = await service.get_crew(crew.id, user)
    assert crew_get.id == crew.id

    # 4. Update Crew
    update_data = CrewUpdate(name="Updated Crew Name")
    crew_upd = await service.update_crew(crew.id, user, update_data)
    assert crew_upd.name == "Updated Crew Name"

    # 5. Members Management
    other_user_id = uuid.uuid4()
    member = await service.add_crew_member(
        crew.id, user, CrewMemberCreate(user_id=other_user_id, role="editor")
    )
    assert member.role == "editor"

    # List members
    members = await service.get_crew_members(crew.id, user)
    assert len(members) >= 2

    # Update member
    member_upd = await service.update_crew_member_role(
        crew.id, other_user_id, CrewMemberUpdate(role="owner"), user
    )
    assert member_upd.role == "owner"

    # Remove member
    await service.remove_crew_member(crew.id, other_user_id, user)

    # 6. Delete Crew
    await service.delete_crew(crew.id, user)


@pytest.mark.asyncio
async def test_create_crew_grants_data_access_restricted_to_space(db_session):
    """A crew can be granted connections/tables, but only the subset its parent
    space already exposes — anything outside the space is silently dropped."""
    user = User(
        id=uuid.uuid4(),
        email="crew.access@example.com",
        role="user",
        password_hash="dummy",
        name="Access User",
    )
    space = Space(id=uuid.uuid4(), name="Access Space", created_by=user.id)
    # Two connections: one belongs to the space, one does not.
    conn_in = DataConnection(
        id=uuid.uuid4(), name="In-Space DB", connector_id="postgres", config={}, created_by=user.id
    )
    conn_out = DataConnection(
        id=uuid.uuid4(), name="Other DB", connector_id="postgres", config={}, created_by=user.id
    )
    db_session.add_all([user, space, conn_in, conn_out])
    await db_session.flush()

    # The space has conn_in (not conn_out), and narrows conn_in to a single table.
    db_session.add(SpaceConnection(space_id=space.id, connection_id=conn_in.id))
    db_session.add(
        SpaceTable(
            space_id=space.id,
            connection_id=conn_in.id,
            table_name="invoices",
            schema_name="billing_silver",
        )
    )
    await db_session.flush()

    service = CrewService(db_session)
    crew = await service.create_crew(
        user,
        CrewCreate(
            name="Scoped Crew",
            space_id=space.id,
            # conn_out must be dropped (not in space); conn_in kept.
            connection_ids=[conn_in.id, conn_out.id],
            tables=[
                # allowed — in the space's narrowed set
                CrewTableSelection(
                    connection_id=conn_in.id, table_name="invoices", schema_name="billing_silver"
                ),
                # dropped — space did not expose this table for conn_in
                CrewTableSelection(
                    connection_id=conn_in.id, table_name="secret", schema_name="billing_silver"
                ),
                # dropped — connection not in space at all
                CrewTableSelection(
                    connection_id=conn_out.id, table_name="anything", schema_name=None
                ),
            ],
        ),
    )

    conn_rows = (
        (
            await db_session.execute(
                select(CrewConnection.connection_id).where(CrewConnection.crew_id == crew.id)
            )
        )
        .scalars()
        .all()
    )
    assert set(conn_rows) == {conn_in.id}

    table_rows = (
        await db_session.execute(
            select(CrewTable.connection_id, CrewTable.table_name, CrewTable.schema_name).where(
                CrewTable.crew_id == crew.id
            )
        )
    ).all()
    assert set(table_rows) == {(conn_in.id, "invoices", "billing_silver")}
    # connection_count is computed by the stats query, not by create's return.
    refetched = await service.get_crew(crew.id, user)
    assert refetched.connection_count == 1

    # The read endpoint reflects the crew's OWN grant (one connection, narrowed
    # to one table) with the resolved name — not the parent space's full list.
    detail = await service.get_crew_connections(crew.id, user)
    assert len(detail) == 1
    assert detail[0].connection_id == conn_in.id
    assert detail[0].name == "In-Space DB"
    assert detail[0].all_tables is False
    assert [(t.table_name, t.schema_name) for t in detail[0].tables] == [
        ("invoices", "billing_silver")
    ]


@pytest.mark.asyncio
async def test_create_crew_without_connections_grants_no_access(db_session):
    """Omitting connection_ids creates NO CrewConnection/CrewTable rows — the
    crew starts with no data access. Fail-closed: the space must liberate
    tables to the crew explicitly via CrewTable; there is no inheritance from
    the space (see PermissionService.get_authorized_tables)."""
    user = User(
        id=uuid.uuid4(),
        email="crew.noaccess@example.com",
        role="user",
        password_hash="dummy",
        name="NoAccess User",
    )
    space = Space(id=uuid.uuid4(), name="Plain Space", created_by=user.id)
    db_session.add_all([user, space])
    await db_session.flush()

    service = CrewService(db_session)
    crew = await service.create_crew(user, CrewCreate(name="Plain Crew", space_id=space.id))

    conn_rows = (
        (
            await db_session.execute(
                select(CrewConnection.connection_id).where(CrewConnection.crew_id == crew.id)
            )
        )
        .scalars()
        .all()
    )
    assert conn_rows == []
    # No CrewTable grants either — the crew is fail-closed until tables are
    # explicitly liberated to it by the space.
    table_rows = (
        (await db_session.execute(select(CrewTable.table_name).where(CrewTable.crew_id == crew.id)))
        .scalars()
        .all()
    )
    assert table_rows == []
