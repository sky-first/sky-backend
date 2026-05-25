from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.services.ai_service import AIService


@pytest.mark.asyncio
async def test_ai_service_simple_coverage():
    db = AsyncMock()
    service = AIService(db)
    user_id = uuid4()

    # Simple coverage for utility methods
    service.crew_member_repo = MagicMock()
    service.crew_member_repo.get_crew_ids_by_user = AsyncMock(return_value=[uuid4()])
    ids = await service._get_user_crew_ids(user_id, all_spaces=True)
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_page_service_coverage():
    from src.services.page_service import PageService

    db = AsyncMock()
    service = PageService(db)
    service.page_repo = MagicMock()
    service.page_repo.get_user_pages = AsyncMock(return_value=[])
    mock_user = MagicMock(id=uuid4())
    res = await service.get_user_pages(mock_user)
    assert res == []


@pytest.mark.asyncio
async def test_user_service_coverage():
    from src.core.exceptions import NotFoundError
    from src.services.user_service import UserService

    db = AsyncMock()
    service = UserService(db)
    service.user_repo = MagicMock()
    service.user_repo.get_by_id = AsyncMock(return_value=None)
    user_id = uuid4()
    mock_user = MagicMock(id=user_id, role="admin")
    with pytest.raises(NotFoundError):
        await service.get_user(user_id, mock_user)
