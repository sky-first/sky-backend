"""FastAPI dependencies."""

from typing import AsyncGenerator, Optional
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.exceptions import UnauthorizedError
from src.models.user import User

# Forward reference
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    pass

# Create HTTPBearer security scheme for Swagger
security = HTTPBearer(
    bearerFormat="JWT",
    description="Enter JWT token obtained from /api/v1/auth/login endpoint",
    auto_error=False
)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get current authenticated user.

    Args:
        request: FastAPI request
        credentials: HTTP Bearer token credentials (for Swagger UI)
        db: Database session

    Returns:
        User: Current user

    Raises:
        UnauthorizedError: If user not authenticated
    """
    # The middleware already validates the token and sets request.state.user_id
    # This dependency is mainly for Swagger UI to show the security requirement
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise UnauthorizedError("User not authenticated")

    from src.repositories.user import UserRepository

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(UUID(user_id))
    if not user:
        raise UnauthorizedError("User not found")

    return user


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session (alias for get_db).

    Yields:
        AsyncSession: Database session
    """
    async for session in get_db():
        yield session

