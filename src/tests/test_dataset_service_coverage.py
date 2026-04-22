"""Coverage boost tests for DatasetService."""

import pytest
import uuid
from src.services.dataset_service import DatasetService
from src.models.user import User

@pytest.mark.asyncio
async def test_dataset_service_basic(db_session):
    user = User(id=uuid.uuid4(), email="data.test@example.com", role="user", password_hash="dummy", name="Test User")
    db_session.add(user)
    await db_session.flush()

    service = DatasetService(db_session)
    
    # 1. Delete "table" dataset (marks as excluded)
    await service.delete_dataset("some_table", user)
    
    # 2. Get excluded datasets
    excluded = await service.get_excluded_datasets(user)
    assert "some_table" in excluded
    
    # 3. Delete "file" dataset (needs a real file or will fail in file_service)
    # We'll just test the prefix logic
    with pytest.raises(Exception): # NotFoundError for invalid UUID
        await service.delete_dataset("file_invalid", user)
