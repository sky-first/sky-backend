"""Authentication middleware."""

import logging
from typing import Callable, cast

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
        return cast(Response, await call_next(request))

    # WebSocket endpoints pass the token as a query parameter (?token=...) because
    # the browser WebSocket API cannot set custom headers. These handlers call
    # verify_token() internally — let them through so the middleware doesn't try
    # to return a JSONResponse on a WebSocket upgrade (which crashes with
    # RuntimeError: No response returned).
    ws_token_paths = [
        "/api/v1/cursor/",
        "/api/v1/ws/chat/",
    ]
    if any(request.url.path.startswith(p) for p in ws_token_paths):
        return cast(Response, await call_next(request))

    # Skip auth for public endpoints
    public_paths = [
        "/health",
        "/healthz",       # k8s convention — same payload as /health, kept
        "/healthz/ready", # so external probes that follow the k8s naming
        "/healthz/live",  # convention (Docker HEALTHCHECK + cluster probes)
        "/ready",
        "/live",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/debug/openapi",
        # API v1 auth routes
        "/api/v1/auth/login",
        "/api/v1/auth/logout",  # Logout doesn't require auth header, only refresh token in body
        "/api/v1/auth/refresh",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/methods",  # Per-tenant auth methods — drives the /login page
        "/api/v1/auth/sso/",  # All SSO endpoints (login and callback)
        "/api/v1/auth/invite/validate",  # Invite validation (public)
        "/api/v1/auth/invite/login",  # Invite login (public)
        "/api/v1/auth/invite/accept",  # Invite accept (public)
        # Local-dev blob storage — browser PUT/GET goes directly here without a Bearer header.
        # Both endpoints return 404 in production (_assert_local_mode guard).
        "/api/v1/knowledge/local-upload",
        "/api/v1/knowledge/local-download",
        # Legacy API routes (without /v1 prefix)
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/refresh",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/verify-email",
        "/api/auth/register",  # Registration endpoint
        "/api/auth/sso/",  # All SSO endpoints (legacy prefix, mirrors /api/v1/auth/sso/)
        "/api/v1/auth/register",  # Registration endpoint (v1)
        # Public demo signup — issues its own JWT, no auth required.
        "/api/v1/demo/",
        "/api/demo/",
        # Projeto A multi-tenant smoke endpoints — no customer data,
        # only the resolver's view of the current request.
        "/api/v1/_test/",
        "/api/_test/",
        # Projeto B Internal Console — auth happens at the dependency
        # layer via ``require_sky_team`` (which itself wraps
        # ``get_current_user``). Letting the legacy auth middleware
        # 401 here would short-circuit the Sky-team check and surface
        # the wrong error code.
        "/api/console/v1/",
    ]

    # Root only (avoid "/" matching every path)
    if request.url.path == "/":
        logger.debug(f"⏭️ Skipping auth for root path: {request.url.path}")
        return cast(Response, await call_next(request))

    if any(request.url.path.startswith(path) for path in public_paths):
        logger.debug(f"⏭️ Skipping auth for public path: {request.url.path}")
        return cast(Response, await call_next(request))

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
            content={
                "error": "Unauthorized",
                "message": "Missing authorization header",
            },
        )
        # Ensure CORS headers are present even when we short-circuit before CORSMiddleware runs
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.add_vary_header("Origin")
        return response

    logger.info(
        f"🔑 Authorization header found for path: {request.url.path}, value: {authorization[:50]}..."
    )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authorization scheme")
    except ValueError:
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "Unauthorized",
                "message": "Invalid authorization header format",
            },
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
        if hasattr(request.state, "user_id") and request.state.user_id:
            logger.debug(
                f"✅ User already authenticated via dependency - user_id: {request.state.user_id}"
            )
            response = await call_next(request)
            return response

        # Try to verify as custom JWT first
        # Note: Auth0 token verification is handled by get_current_user dependency
        # which has access to database session. Middleware only handles custom JWT.
        try:
            payload = verify_token(token, token_type="access")
            user_id = payload.get("sub")
            if not user_id:
                logger.warning(f"Token payload missing 'sub': {payload}")
                raise UnauthorizedError("Invalid token payload")

            # Logout-revocation check (red-team HI 2026-04-23): if the
            # user's `revoke_before` marker in Redis is newer than this
            # token's `iat`, reject. Tokens without `iat` (legacy pre-
            # fix) are grandfathered and will cycle out on their own
            # 15-min exp.
            from src.core.token_blocklist import is_token_revoked
            _iat_claim = payload.get("iat")
            if _iat_claim is not None and await is_token_revoked(
                str(user_id), int(_iat_claim)
            ):
                raise UnauthorizedError("Token revoked")

            # Store user info in request state
            user_id_str = str(user_id)
            request.state.user_id = user_id_str
            request.state.user_role = payload.get("role", "user")
            request.state.auth_type = "custom"

            logger.info(
                f"✅ Auth successful (custom JWT) - user_id: {user_id_str}, path: {request.url.path}"
            )
            response = await call_next(request)
            return response
        except JWTError:
            # Custom JWT failed - let dependency handle Auth0 verification
            # This allows dependency to use database session for Auth0 user lookup
            logger.debug(
                "Custom JWT verification failed, Auth0 verification will be handled by dependency"
            )
            # Continue to next middleware/route - dependency will handle Auth0 verification
            # If dependency also fails, it will raise UnauthorizedError
            response = await call_next(request)
            return response
    except UnauthorizedError as e:
        # Return 401 response directly instead of raising
        logger.warning(f"Unauthorized: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Unauthorized", "message": e.message},
        )
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.add_vary_header("Origin")
        return response
    except JWTError as e:
        logger.warning(f"JWT verification failed: {str(e)}")
        # Return 401 response directly instead of raising
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Invalid or expired token"},
        )
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.add_vary_header("Origin")
        return response
    except Exception as e:
        logger.error(f"Auth middleware error: {str(e)}")
        raise
