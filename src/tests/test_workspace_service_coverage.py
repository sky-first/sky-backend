"""Coverage boost tests for WorkspaceService."""

import pytest
import uuid
from src.services.workspace_service import WorkspaceService
from src.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceMemberCreate
from src.models.user import User

@pytest.mark.asyncio
async def test_workspace_service_lifecycle(db_session):
    user = User(id=uuid.uuid4(), email="ws.test@example.com", role="user", password_hash="dummy", name="Test User")
    db_session.add(user)
    await db_session.flush()

    service = WorkspaceService(db_session)
    
    # 1. Create Workspace
    create_data = WorkspaceCreate(name="WS Test", type="personal", color="#000000")
    ws = await service.create_workspace(user, create_data)
    assert ws.name == "WS Test"
    
    # 2. Get User Workspaces
    wss = await service.get_user_workspaces(user)
    assert len(wss) >= 1
    
    # 3. Get Workspace
    ws_get = await service.get_workspace(ws.id, user)
    assert ws_get.id == ws.id
    
    # 4. Update Workspace
    update_data = WorkspaceUpdate(name="Updated WS")
    ws_upd = await service.update_workspace(ws.id, user, update_data)
    assert ws_upd.name == "Updated WS"
    
    # 5. Members Management
    other_user_id = uuid.uuid4()
    member = await service.add_member(ws.id, user, WorkspaceMemberCreate(user_id=other_user_id, role="member"))
    assert member.role == "member"
    
    members = await service.get_workspace_members(ws.id, user)
    assert len(members) >= 2
    
    await service.update_member_role(ws.id, other_user_id, "admin", user)
    await service.remove_member(ws.id, other_user_id, user)
    
    # 6. Switch Workspace
    await service.switch_workspace(ws.id, user)
    
    # 7. Delete Workspace
    await service.delete_workspace(ws.id, user)
