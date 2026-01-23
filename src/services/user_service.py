"""User service."""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.core.permissions import check_permission, get_user_permissions
from src.core.security import get_password_hash
from src.models.user import User
from src.repositories.user import UserRepository
from src.schemas.user import UserCreate, UserResponse, UserUpdate
from src.services.auth_service import user_to_response_dict
from src.services.onboarding_service import ensure_default_planet_and_space


class UserService:
    """User service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize user service.

        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    async def list_users(
        self, current_user: User, skip: int = 0, limit: int = 100
    ) -> List[UserResponse]:
        """
        List all users.

        Args:
            current_user: Current authenticated user
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List[UserResponse]: List of users

        Raises:
            ForbiddenError: If user doesn't have permission
        """
        if not check_permission(current_user, "user", "read"):
            raise ForbiddenError("You don't have permission to list users")

        users = await self.user_repo.get_all(skip=skip, limit=limit)
        return [UserResponse.model_validate(user_to_response_dict(user)) for user in users]

    async def get_user(self, user_id: UUID, current_user: User) -> UserResponse:
        """
        Get user by ID.

        Args:
            user_id: User ID
            current_user: Current authenticated user

        Returns:
            UserResponse: User data

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        # Users can view their own profile, admins can view any
        if user_id != current_user.id and not check_permission(current_user, "user", "read"):
            raise ForbiddenError("You don't have permission to view this user")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        return UserResponse.model_validate(user_to_response_dict(user))

    async def create_user(self, user_data: UserCreate, current_user: User) -> UserResponse:
        """
        Create a new user.

        Args:
            user_data: User creation data
            current_user: Current authenticated user

        Returns:
            UserResponse: Created user

        Raises:
            ForbiddenError: If user doesn't have permission
            BadRequestError: If email already exists
        """
        if not check_permission(current_user, "user", "create"):
            raise ForbiddenError("You don't have permission to create users")

        # Check if email already exists
        existing_user = await self.user_repo.get_by_email(user_data.email)
        if existing_user:
            raise BadRequestError("User with this email already exists")

        # Create user
        user = await self.user_repo.create(
            email=user_data.email,
            password_hash=get_password_hash(user_data.password),
            name=user_data.name,
            avatar=user_data.avatar,
            role=user_data.role,
        )

        await self.db.commit()
        await self.db.refresh(user)

        # Ensure default planet/space for new users created by admins
        await ensure_default_planet_and_space(self.db, user)

        return UserResponse.model_validate(user_to_response_dict(user))

    async def update_user(
        self, user_id: UUID, user_data: UserUpdate, current_user: User
    ) -> UserResponse:
        """
        Update user.

        Args:
            user_id: User ID
            user_data: User update data
            current_user: Current authenticated user

        Returns:
            UserResponse: Updated user

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        # Users can update their own profile (limited fields), admins can update any
        if user_id != current_user.id and not check_permission(current_user, "user", "update"):
            raise ForbiddenError("You don't have permission to update this user")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        # Non-admin users can only update limited fields
        if current_user.role != "admin" and user_id != current_user.id:
            raise ForbiddenError("You can only update your own profile")

        # Update fields
        update_data = user_data.model_dump(exclude_unset=True)

        # Non-admin users cannot change role
        if current_user.role != "admin" and "role" in update_data:
            del update_data["role"]

        # Handle preferences specifically to merge instead of replace
        ai_fields = ["ai_tone", "ai_style", "ai_context"]
        has_ai_updates = any(field in update_data for field in ai_fields)

        if has_ai_updates or "preferences" in update_data:
            current_preferences = user.preferences or {}

            # Merge explicit AI fields
            for field in ai_fields:
                if field in update_data:
                    current_preferences[field] = update_data.pop(field)

            # Merge general preferences if provided
            if "preferences" in update_data:
                prefs_to_merge = update_data.pop("preferences")
                if isinstance(prefs_to_merge, dict):
                    current_preferences.update(prefs_to_merge)

            user.preferences = current_preferences
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(user, "preferences")

        # Update remaining fields
        for key, value in update_data.items():
            setattr(user, key, value)

        await self.db.commit()
        await self.db.refresh(user)

        return UserResponse.model_validate(user_to_response_dict(user))

    async def delete_user(self, user_id: UUID, current_user: User) -> None:
        """
        Delete user (soft delete).

        Args:
            user_id: User ID
            current_user: Current authenticated user

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
            BadRequestError: If trying to delete own account
        """
        if not check_permission(current_user, "user", "delete"):
            raise ForbiddenError("You don't have permission to delete users")

        if user_id == current_user.id:
            raise BadRequestError("You cannot delete your own account")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        await self.user_repo.delete(user_id)
        await self.db.commit()

    async def get_user_permissions(self, user_id: UUID, current_user: User) -> dict:
        """
        Get user permissions.

        Args:
            user_id: User ID
            current_user: Current authenticated user

        Returns:
            dict: User permissions

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        # Users can view their own permissions, admins can view any
        if user_id != current_user.id and not check_permission(current_user, "user", "read"):
            raise ForbiddenError("You don't have permission to view this user's permissions")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        return get_user_permissions(user)

    async def update_user_permissions(
        self, user_id: UUID, permissions: dict, current_user: User
    ) -> dict:
        """
        Update user permissions (by changing role).

        Args:
            user_id: User ID
            permissions: Permissions data (contains role)
            current_user: Current authenticated user

        Returns:
            dict: Updated permissions

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        if not check_permission(current_user, "user", "update"):
            raise ForbiddenError("You don't have permission to update user permissions")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        # Update role if provided
        if "role" in permissions:
            new_role = permissions["role"]
            if new_role not in ["admin", "user", "viewer"]:
                raise BadRequestError("Invalid role")
            user.role = new_role
            await self.db.commit()
            await self.db.refresh(user)

        return get_user_permissions(user)

    async def invite_user(
        self, user_id: UUID, invite_data: dict, current_user: User
    ) -> UserResponse:
        """
        Invite user (resend invitation or send welcome email).

        Args:
            user_id: User ID
            invite_data: Invite data (e.g., workspace_id, role)
            current_user: Current authenticated user

        Returns:
            UserResponse: User data

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        if not check_permission(current_user, "user", "update"):
            raise ForbiddenError("You don't have permission to invite users")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        # TODO: Implement email sending for invitation
        # For now, just return the user
        return UserResponse.model_validate(user_to_response_dict(user))
