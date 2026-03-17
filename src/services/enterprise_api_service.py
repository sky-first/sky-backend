"""Enterprise API service."""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.enterprise_api import EnterpriseAPI
from src.models.user import User
from src.repositories.enterprise_api import EnterpriseAPIRepository
from src.schemas.enterprise_api import EnterpriseAPICreate, EnterpriseAPIUpdate


class EnterpriseAPIService:
    """Enterprise API service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize enterprise API service.

        Args:
            db: Database session
        """
        self.db = db
        self.api_repo = EnterpriseAPIRepository(db)

    async def list_apis(self, user: User) -> List[EnterpriseAPI]:
        """
        List all APIs for a user.

        Args:
            user: Current user

        Returns:
            List[EnterpriseAPI]: List of APIs
        """
        return await self.api_repo.get_by_user(user.id)

    async def get_api(self, api_id: UUID, user: User) -> EnterpriseAPI:
        """
        Get API by ID.

        Args:
            api_id: API ID
            user: Current user

        Returns:
            EnterpriseAPI: API data

        Raises:
            NotFoundError: If API not found
            ForbiddenError: If user doesn't have access
        """
        api = await self.api_repo.get_by_id(api_id)
        if not api:
            raise NotFoundError("Enterprise API not found")

        if api.created_by != user.id:
            raise ForbiddenError("Access denied to this API")

        return api

    async def create_api(
        self, user: User, api_data: EnterpriseAPICreate
    ) -> EnterpriseAPI:
        """
        Create a new API registry.

        Args:
            user: Current user
            api_data: API creation data

        Returns:
            EnterpriseAPI: Created API
        """
        # Convert endpoints to dict for JSON storage
        endpoints_data = [e.model_dump() for e in api_data.endpoints]

        api = await self.api_repo.create(
            name=api_data.name,
            base_url=api_data.base_url,
            description=api_data.description,
            endpoints=endpoints_data,
            created_by=user.id,
        )

        await self.db.commit()
        await self.db.refresh(api)
        return api

    async def update_api(
        self, api_id: UUID, user: User, api_data: EnterpriseAPIUpdate
    ) -> EnterpriseAPI:
        """
        Update API registry.

        Args:
            api_id: API ID
            user: Current user
            api_data: API update data

        Returns:
            EnterpriseAPI: Updated API

        Raises:
            NotFoundError: If API not found
            ForbiddenError: If user doesn't have access
        """
        api = await self.api_repo.get_by_id(api_id)
        if not api:
            raise NotFoundError("Enterprise API not found")

        if api.created_by != user.id:
            raise ForbiddenError("Access denied to this API")

        update_data = api_data.model_dump(exclude_unset=True)

        # Convert endpoints to dict if provided
        if "endpoints" in update_data and update_data["endpoints"]:
            update_data["endpoints"] = [e.model_dump() for e in api_data.endpoints]

        await self.api_repo.update(api_id, **update_data)
        await self.db.commit()

        # Reload
        return await self.api_repo.get_by_id(api_id)

    async def delete_api(self, api_id: UUID, user: User) -> None:
        """
        Delete API registry.

        Args:
            api_id: API ID
            user: Current user

        Raises:
            NotFoundError: If API not found
            ForbiddenError: If user doesn't have access
        """
        api = await self.api_repo.get_by_id(api_id)
        if not api:
            raise NotFoundError("Enterprise API not found")

        if api.created_by != user.id:
            raise ForbiddenError("Access denied to this API")

        await self.db.delete(api)
        await self.db.commit()
