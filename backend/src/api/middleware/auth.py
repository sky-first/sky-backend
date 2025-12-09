"""Authentication middleware."""

import logging
from typing import Callable, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError

from src.core.exceptions import UnauthorizedError
from src.core.security import verify_token

logger = logging.getLogger(__name__)


async def auth_middleware(request: Request, call_next: Callable) -> Response:
    """
    Authentication middleware.

    Args:
        request: FastAPI request
        call_next: Next middleware/route handler

    Returns:
        Response: HTTP response
    """
    # Skip auth for public endpoints
    public_paths = [
        "/health",
        "/ready",
        "/live",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/debug/openapi",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",  # Logout doesn't require auth header, only refresh token in body
        "/api/v1/auth/refresh",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-email",
    ]

    if any(request.url.path.startswith(path) for path in public_paths):
        return await call_next(request)

    # Extract token from Authorization header
    authorization = request.headers.get("Authorization")
    if not authorization:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Missing authorization header"},
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authorization scheme")
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Invalid authorization header format"},
        )

    try:
        # Verify token
        payload = verify_token(token, token_type="access")
        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedError("Invalid token payload")

        # Store user info in request state
        request.state.user_id = user_id
        request.state.user_role = payload.get("role", "user")

        response = await call_next(request)
        return response
    except JWTError as e:
        logger.warning(f"JWT verification failed: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Invalid or expired token"},
        )
    except Exception as e:
        logger.error(f"Auth middleware error: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal Server Error", "message": "Authentication error"},
        )

