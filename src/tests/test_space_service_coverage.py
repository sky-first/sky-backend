"""Coverage boost tests for SpaceService."""

import pytest
import uuid
from src.services.space_service import SpaceService
from src.schemas.space import SpaceCreate, SpaceUpdate, SpaceMemberCreate, SpaceTableCreate
from src.models.user import User

@pytest.mark.asyncio
async def test_space_service_lifecycle(db_session):
    # Setup - use a real user from DB if possible, or create one
    user = User(id=uuid.uuid4(), email="space.test@example.com", role="user", password_hash="dummy", name="Test User")
    db_session.add(user)
    await db_session.flush()

    service = SpaceService(db_session)
    
    # 1. Create Space
    create_data = SpaceCreate(name="Service Test Space", description="Testing", color="#FF0000", icon="star")
    space = await service.create_space(user, create_data)
    assert space.name == "Service Test Space"
    
    # 1b. Elevate creator to owner (Phase 7 vocabulary).
    await service.update_space_member_role(space.id, user.id, "owner")
    
    # 2. List Spaces
    spaces = await service.list_spaces(user)
    assert len(spaces) >= 1
    
    # 3. Get Space
    space_get = await service.get_space(space.id, user)
    assert space_get.id == space.id
    
    # 4. Update Space
    update_data = SpaceUpdate(name="Updated Space Name")
    space_upd = await service.update_space(space.id, user, update_data)
    assert space_upd.name == "Updated Space Name"
    
    # 5. Members Management
    # Add member
    other_user_id = uuid.uuid4()
    # Correct order: (space_id, user, member_data)
    member = await service.add_space_member(space.id, user, SpaceMemberCreate(user_id=other_user_id, role="editor"))
    assert member.role == "editor"
    
    # List members
    members = await service.get_space_members(space.id, user)
    assert len(members) >= 2 # creator + new member
    
    # Update member
    member_upd = await service.update_space_member_role(space.id, other_user_id, "owner")
    assert member_upd.role == "owner"
    
    # Remove member
    await service.remove_space_member(space.id, other_user_id, user)
    
    # 6. Tables Management
    from src.models.connection import DataConnection
    conn = DataConnection(
        id=uuid.uuid4(),
        name="Test Conn",
        connector_id="postgres",
        config={},
        created_by=user.id
    )
    db_session.add(conn)
    await db_session.flush()

    await service.add_space_table(space.id, SpaceTableCreate(connection_id=conn.id, table_name="test_table"), user)
    
    # 7. Delete Space
    await service.delete_space(space.id, user)

@pytest.mark.asyncio
async def test_space_service_exceptions(db_session):
    user = User(id=uuid.uuid4(), email="space.err@example.com", role="user", password_hash="dummy", name="Test User")
    db_session.add(user)
    await db_session.flush()
    
    service = SpaceService(db_session)
    non_existent = uuid.uuid4()
    
    with pytest.raises(Exception): # NotFoundError
        await service.get_space(non_existent, user)
    
    with pytest.raises(Exception): # NotFoundError
        await service.update_space(non_existent, user, SpaceUpdate(name="X"))
