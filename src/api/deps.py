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
    import logging
    logger = logging.getLogger(__name__)
    
    # IMPORTANT: In FastAPI, dependencies are resolved BEFORE HTTP middlewares execute.
    # So we need to validate the token directly here, not rely on middleware.
    # However, we also check request.state in case middleware already set it (for consistency).
    
    user_id = None
    
    # First, try to get user_id from request.state (set by middleware if it executed)
    if hasattr(request, 'state'):
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            logger.debug(f"🔍 Found user_id in request.state: {user_id}")
    
    # If not in state, extract and validate token directly from Authorization header
    if not user_id:
        authorization = request.headers.get("Authorization")
        if authorization:
            try:
                scheme, token = authorization.split(" ", 1)  # Use maxsplit=1 to handle tokens with spaces
                if scheme.lower() == "bearer":
                    # Verify token directly
                    from src.core.security import verify_token
                    payload = verify_token(token, token_type="access")
                    user_id = payload.get("sub")
                    if user_id:
                        # Ensure request.state exists
                        if not hasattr(request, 'state'):
                            # This shouldn't happen, but just in case
                            logger.warning("request.state doesn't exist, creating it")
                        # Store in request.state for other middlewares/dependencies
                        request.state.user_id = str(user_id)
                        request.state.user_role = payload.get("role", "user")
                        logger.debug(f"🔍 Validated token and set user_id in state: {user_id}")
            except ValueError as e:
                # Invalid authorization header format
                logger.debug(f"🔍 Invalid authorization header format: {str(e)}")
            except Exception as e:
                logger.debug(f"🔍 Token validation failed: {str(e)}")
                # Fall through to error below
    
    # Also check credentials from Swagger UI (HTTPBearer)
    if not user_id and credentials:
        try:
            from src.core.security import verify_token
            payload = verify_token(credentials.credentials, token_type="access")
            user_id = payload.get("sub")
            if user_id:
                request.state.user_id = str(user_id)
                request.state.user_role = payload.get("role", "user")
                logger.debug(f"🔍 Validated token from credentials and set user_id: {user_id}")
        except Exception as e:
            logger.debug(f"🔍 Credentials validation failed: {str(e)}")
    
    if not user_id:
        logger.warning(f"❌ User not authenticated - no valid token found. Path: {request.url.path}")
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

