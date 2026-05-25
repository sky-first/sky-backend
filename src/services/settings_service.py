"""Settings service."""

import secrets
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.core.permissions import check_permission
from src.core.security import get_password_hash
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.crew import CrewRepository
from src.repositories.settings import APIKeyRepository, IntegrationRepository
from src.repositories.space import SpaceRepository
from src.repositories.user import UserRepository
from src.schemas.settings import (
    APIKeyCreate,
    APIKeyResponse,
    CrewsSettingsResponse,
    DataCatalogSettingsResponse,
    IntegrationCreate,
    IntegrationResponse,
    IntegrationUpdate,
    PermissionsSettingsResponse,
    SettingsResponse,
    SettingsUpdate,
    SpacesSettingsResponse,
    UsersSettingsResponse,
)


class SettingsService:
    """Settings service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize settings service.

        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)
        self.space_repo = SpaceRepository(db)
        self.crew_repo = CrewRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.api_key_repo = APIKeyRepository(db)
        self.integration_repo = IntegrationRepository(db)

    async def get_settings(self, user: User) -> SettingsResponse:
        """
        Get user settings.

        Args:
            user: Current user

        Returns:
            SettingsResponse: User settings
        """
        preferences = user.preferences or {}

        return SettingsResponse(
            theme=preferences.get("theme", "light"),
            language=preferences.get("language", "en"),
            notifications=preferences.get("notifications", {"email": True, "push": False}),
            preferences=preferences,
        )

    async def update_settings(self, user: User, settings_data: SettingsUpdate) -> SettingsResponse:
        """
        Update user settings.

        Args:
            user: Current user
            settings_data: Settings update data

        Returns:
            SettingsResponse: Updated settings
        """
        # Get existing preferences or initialize empty
        current_preferences = user.preferences or {}

        # Update with new data
        update_data = settings_data.model_dump(exclude_unset=True)

        # Merge dictionaries carefully
        # For top-level keys like 'theme' and 'language', direct replacement is fine
        if "theme" in update_data:
            current_preferences["theme"] = update_data["theme"]
        if "language" in update_data:
            current_preferences["language"] = update_data["language"]

        # For nested dictionaries like 'notifications', we might want to merge
        if "notifications" in update_data and update_data["notifications"]:
            current_preferences["notifications"] = {
                **(current_preferences.get("notifications") or {}),
                **update_data["notifications"],
            }

        # For the generic 'preferences' field, deep merge is tricky, but let's do shallow merge for now
        if "preferences" in update_data and update_data["preferences"]:
            current_preferences.update(update_data["preferences"])

        # Update user object
        user.preferences = current_preferences

        # Make sure to flag the field as modified for SQLAlchemy to pick up JSON changes
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(user, "preferences")

        # Check permissions? (Usually user can update their own settings)
        await self.user_repo.update(user.id, preferences=current_preferences)

        return SettingsResponse(
            theme=current_preferences.get("theme", "light"),
            language=current_preferences.get("language", "en"),
            notifications=current_preferences.get("notifications", {"email": True, "push": False}),
            preferences=current_preferences,
        )

    async def get_data_catalog_settings(self, user: User) -> DataCatalogSettingsResponse:
        """
        Get data catalog settings.

        Args:
            user: Current user

        Returns:
            DataCatalogSettingsResponse: Data catalog settings
        """
        # TODO: Get from database or config
        return DataCatalogSettingsResponse(
            auto_sync=True,
            sync_interval=3600,
            enabled_connectors=["postgresql", "mysql", "mongodb"],
        )

    async def get_spaces_settings(self, user: User) -> SpacesSettingsResponse:
        """
        Get spaces settings.

        Args:
            user: Current user

        Returns:
            SpacesSettingsResponse: Spaces settings
        """
        # TODO: Get from database or config
        return SpacesSettingsResponse(
            default_role="viewer",
            allow_public_spaces=False,
            max_spaces_per_user=10,
        )

    async def get_crews_settings(self, user: User) -> CrewsSettingsResponse:
        """
        Get crews settings.

        Args:
            user: Current user

        Returns:
            CrewsSettingsResponse: Crews settings
        """
        # TODO: Get from database or config
        return CrewsSettingsResponse(
            default_role="viewer",
            max_crews_per_user=5,
            allow_public_crews=False,
        )

    async def get_users_settings(self, user: User) -> UsersSettingsResponse:
        """
        Get users settings.

        Args:
            user: Current user

        Returns:
            UsersSettingsResponse: Users settings

        Raises:
            ForbiddenError: If user is not admin
        """
        if not check_permission(user, "user", "read"):
            raise ForbiddenError("Only administrators can view user settings")

        # TODO: Get from database or config
        return UsersSettingsResponse(
            allow_registration=True,
            require_email_verification=False,
            default_role="user",
        )

    async def get_permissions_settings(self, user: User) -> PermissionsSettingsResponse:
        """
        Get permissions settings.

        Args:
            user: Current user

        Returns:
            PermissionsSettingsResponse: Permissions settings

        Raises:
            ForbiddenError: If user is not admin
        """
        if not check_permission(user, "permission", "read"):
            raise ForbiddenError("Only administrators can view permission settings")

        # TODO: Get from database or config
        return PermissionsSettingsResponse(
            rbac_enabled=True,
            default_permissions={
                "admin": ["create", "read", "update", "delete"],
                "user": ["read", "update"],
                "viewer": ["read"],
            },
        )

    async def get_api_keys(self, user: User) -> List[APIKeyResponse]:
        """
        Get user API keys.

        Args:
            user: Current user

        Returns:
            List[APIKeyResponse]: List of API keys
        """
        api_keys = await self.api_key_repo.get_by_user(user.id)
        return [APIKeyResponse.model_validate(key) for key in api_keys]

    async def create_api_key(self, user: User, api_key_data: APIKeyCreate) -> Dict[str, Any]:
        """
        Create API key.

        Args:
            user: Current user
            api_key_data: API key creation data

        Returns:
            Dict[str, Any]: API key with plain key (only shown once)
        """
        # Generate API key
        plain_key = f"sk_{secrets.token_urlsafe(32)}"
        key_hash = get_password_hash(plain_key)
        key_prefix = plain_key[:12]  # First 12 characters for display

        # Create API key record
        api_key = await self.api_key_repo.create(
            user_id=user.id,
            name=api_key_data.name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            permissions=api_key_data.permissions,
            expires_at=api_key_data.expires_at,
        )

        await self.db.commit()
        await self.db.refresh(api_key)

        # Return with plain key (only shown once)
        return {
            "id": api_key.id,
            "name": api_key.name,
            "key": plain_key,  # Only shown once
            "key_prefix": key_prefix,
            "permissions": api_key.permissions,
            "expires_at": api_key.expires_at,
            "created_at": api_key.created_at,
        }

    async def delete_api_key(self, api_key_id: UUID, user: User) -> None:
        """
        Delete API key.

        Args:
            api_key_id: API key ID
            user: Current user

        Raises:
            NotFoundError: If API key not found
            ForbiddenError: If user doesn't own the key
        """
        api_key = await self.api_key_repo.get_by_id(api_key_id)
        if not api_key:
            raise NotFoundError("API key not found")

        if api_key.user_id != user.id:
            raise ForbiddenError("You do not have permission to delete this API key")

        await self.api_key_repo.delete(api_key_id)
        await self.db.commit()

    async def get_integrations(self, user: User) -> List[IntegrationResponse]:
        """
        Get user integrations.

        Args:
            user: Current user

        Returns:
            List[IntegrationResponse]: List of integrations
        """
        integrations = await self.integration_repo.get_by_user(user.id)
        return [IntegrationResponse.model_validate(integration) for integration in integrations]

    async def create_integration(
        self, user: User, integration_data: IntegrationCreate
    ) -> IntegrationResponse:
        """
        Create integration.

        Args:
            user: Current user
            integration_data: Integration creation data

        Returns:
            IntegrationResponse: Created integration
        """
        integration = await self.integration_repo.create(
            user_id=user.id,
            name=integration_data.name,
            type=integration_data.type,
            config=integration_data.config,
            enabled="true" if integration_data.enabled else "false",
        )

        await self.db.commit()
        await self.db.refresh(integration)

        return IntegrationResponse.model_validate(integration)

    async def update_integration(
        self, integration_id: UUID, user: User, integration_data: IntegrationUpdate
    ) -> IntegrationResponse:
        """
        Update integration.

        Args:
            integration_id: Integration ID
            user: Current user
            integration_data: Integration update data

        Returns:
            IntegrationResponse: Updated integration

        Raises:
            NotFoundError: If integration not found
            ForbiddenError: If user doesn't own the integration
        """
        integration = await self.integration_repo.get_by_id(integration_id)
        if not integration:
            raise NotFoundError("Integration not found")

        if integration.user_id != user.id:
            raise ForbiddenError("You do not have permission to update this integration")

        update_data = integration_data.model_dump(exclude_unset=True)
        if "enabled" in update_data:
            update_data["enabled"] = "true" if update_data["enabled"] else "false"

        integration = await self.integration_repo.update(integration_id, **update_data)
        await self.db.commit()
        await self.db.refresh(integration)

        return IntegrationResponse.model_validate(integration)

    async def delete_integration(self, integration_id: UUID, user: User) -> None:
        """
        Delete integration.

        Args:
            integration_id: Integration ID
            user: Current user

        Raises:
            NotFoundError: If integration not found
            ForbiddenError: If user doesn't own the integration
        """
        integration = await self.integration_repo.get_by_id(integration_id)
        if not integration:
            raise NotFoundError("Integration not found")

        if integration.user_id != user.id:
            raise ForbiddenError("You do not have permission to delete this integration")

        await self.integration_repo.delete(integration_id)
        await self.db.commit()
