"""Authentication middleware."""

import logging
from typing import Callable, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError

from src.config.settings import settings
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
    # Log that middleware is executing
    logger.info(f"🚀 AUTH MIDDLEWARE START - Path: {request.url.path}, Method: {request.method}")

    # Always allow CORS preflight requests through so CORSMiddleware can respond with 200.
    # Browsers send OPTIONS without Authorization; blocking it causes "preflight not OK" errors.
    if request.method == "OPTIONS":
        return await call_next(request)
    
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

    # Root only (avoid "/" matching every path)
    if request.url.path == "/":
        logger.debug(f"⏭️ Skipping auth for root path: {request.url.path}")
        return await call_next(request)

    if any(request.url.path.startswith(path) for path in public_paths):
        logger.debug(f"⏭️ Skipping auth for public path: {request.url.path}")
        return await call_next(request)
    
    logger.info(f"🔐 Auth middleware executing for path: {request.url.path}")

    # Extract token from Authorization header
    # Check all possible header name variations (case-insensitive)
    authorization = None
    for header_name in ["Authorization", "authorization", "AUTHORIZATION"]:
        if header_name in request.headers:
            authorization = request.headers[header_name]
            break
    
    # Also try direct access (case-insensitive)
    if not authorization:
        authorization = request.headers.get("Authorization") or request.headers.get("authorization")
    
    # Debug: log all headers
    logger.info(f"🔍 All headers: {dict(request.headers)}")
    logger.info(f"🔍 Authorization header value: {authorization}")
    
    if not authorization:
        logger.warning(f"⚠️ No authorization header for path: {request.url.path}")
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Missing authorization header"},
        )
        # Ensure CORS headers are present even when we short-circuit before CORSMiddleware runs
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.add_vary_header("Origin")
        return response
    
    logger.info(f"🔑 Authorization header found for path: {request.url.path}, value: {authorization[:50]}...")

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authorization scheme")
    except ValueError:
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Invalid authorization header format"},
        )
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.add_vary_header("Origin")
        return response

    try:
        # Check if user_id already set by dependency (get_current_user validates token first)
        # This avoids duplicate token validation
        if hasattr(request.state, 'user_id') and request.state.user_id:
            logger.debug(f"✅ User already authenticated via dependency - user_id: {request.state.user_id}")
            response = await call_next(request)
            return response
        
        # Verify token (fallback if dependency didn't set it)
        payload = verify_token(token, token_type="access")
        user_id = payload.get("sub")
        if not user_id:
            logger.warning(f"Token payload missing 'sub': {payload}")
            raise UnauthorizedError("Invalid token payload")

        # Store user info in request state
        # Ensure user_id is a string
        user_id_str = str(user_id)
        
        # Set state attributes directly
        request.state.user_id = user_id_str
        request.state.user_role = payload.get("role", "user")
        
        # Verify it was set correctly - use INFO level so we can see it in logs
        logger.info(f"🔍 Setting user_id: {user_id_str}, type: {type(user_id_str)}")
        logger.info(f"🔍 request.state.user_id after set: {getattr(request.state, 'user_id', 'NOT SET')}")
        logger.info(f"🔍 request.state attributes: {[attr for attr in dir(request.state) if not attr.startswith('_')]}")
        logger.info(f"✅ Auth successful - user_id: {user_id_str}, path: {request.url.path}")

        response = await call_next(request)
        return response
    except UnauthorizedError:
        # Re-raise UnauthorizedError to be handled by error_handler
        raise
    except JWTError as e:
        logger.warning(f"JWT verification failed: {str(e)}")
        raise UnauthorizedError("Invalid or expired token")
    except Exception as e:
        logger.error(f"Auth middleware error: {str(e)}")
        raise

