"""Coverage boost tests for CrewService."""

import pytest
import uuid
from src.services.crew_service import CrewService
from src.schemas.crew import CrewCreate, CrewUpdate, CrewMemberCreate, CrewMemberUpdate
from src.models.user import User
from src.models.space import Space

@pytest.mark.asyncio
async def test_crew_service_lifecycle(db_session):
    user = User(id=uuid.uuid4(), email="crew.test@example.com", role="user", password_hash="dummy", name="Test User")
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
    member = await service.add_crew_member(crew.id, user, CrewMemberCreate(user_id=other_user_id, role="editor"))
    assert member.role == "editor"

    # List members
    members = await service.get_crew_members(crew.id, user)
    assert len(members) >= 2

    # Update member
    member_upd = await service.update_crew_member_role(crew.id, other_user_id, CrewMemberUpdate(role="owner"), user)
    assert member_upd.role == "owner"
    
    # Remove member
    await service.remove_crew_member(crew.id, other_user_id, user)
    
    # 6. Delete Crew
    await service.delete_crew(crew.id, user)
