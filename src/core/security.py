"""Security utilities: JWT, password hashing."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from src.config.settings import settings

logger = logging.getLogger(__name__)


def get_password_hash(password: str) -> str:
    """
    Hash a password.

    Args:
        password: Plain text password

    Returns:
        str: Hashed password
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password

    Returns:
        bool: True if password matches
    """
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token.

    Args:
        data: Data to encode in token
        expires_delta: Optional expiration delta (if None, uses default from settings)

    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        # Use default expiration from settings
        expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    # `iat` (issued-at) is required by the revocation blocklist: on
    # logout we write a `revoke_before` marker per user and any access
    # token with `iat` older than it is rejected. See
    # src/core/token_blocklist.py + src/api/middleware/auth.py.
    to_encode.update({"exp": expire, "iat": now, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def refresh_ttl_days(client_type: Optional[str] = None) -> int:
    """BE-05 — refresh-token lifetime in days for a given client type.

    Mobile devices get a longer TTL (``JWT_REFRESH_TOKEN_EXPIRE_DAYS_MOBILE``)
    so users aren't logged out weekly; everything else keeps the web default.
    Single source of truth so the JWT ``exp`` and the RefreshToken row's
    ``expires_at`` never drift apart.
    """
    if client_type == "mobile":
        return settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS_MOBILE
    return settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS


def create_refresh_token(data: Dict[str, Any], client_type: Optional[str] = None) -> str:
    """
    Create JWT refresh token.

    Args:
        data: Data to encode in token
        client_type: 'mobile' → longer TTL + a signed ``ctyp`` claim so the
            lifetime survives rotation; anything else uses the web default.

    Returns:
        str: Encoded JWT refresh token
    """
    from uuid import uuid4

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=refresh_ttl_days(client_type))
    claims = {"exp": expire, "type": "refresh", "jti": str(uuid4())}
    # Stamp the client type so /auth/refresh can carry the mobile TTL forward
    # across rotations without re-reading it from the request.
    if client_type:
        claims["ctyp"] = client_type
    to_encode.update(claims)
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> Dict[str, Any]:
    """
    Verify and decode JWT token (hybrid: custom JWT or Auth0).

    Tries to verify as custom JWT first, then as Auth0 token if that fails.

    Args:
        token: JWT token to verify
        token_type: Expected token type ('access' or 'refresh') - only for custom JWT

    Returns:
        Dict[str, Any]: Decoded token payload

    Raises:
        JWTError: If token is invalid
    """
    # First, try to verify as custom JWT
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != token_type:
            raise JWTError("Invalid token type")
        logger.debug("✅ Token verified as custom JWT")
        return payload
    except JWTError as jwt_err:
        # If custom JWT fails, this function only handles custom JWT
        # Auth0 verification is handled separately in middleware/dependencies
        raise JWTError(f"Invalid custom JWT token: {str(jwt_err)}")
    except Exception as e:
        raise JWTError(f"Invalid token: {str(e)}")


async def verify_auth0_token_async(token: str) -> Dict[str, Any]:
    """
    Verify Auth0 JWT token asynchronously.

    This is a helper function for use in async contexts (middleware, dependencies).

    Args:
        token: Auth0 JWT token

    Returns:
        Dict[str, Any]: Decoded token payload

    Raises:
        JWTError: If token is invalid
    """
    try:
        from src.config.auth0 import auth0_settings
        from src.config.database import get_db
        from src.services.auth0_service import Auth0Service

        if not auth0_settings.is_auth0_enabled:
            raise JWTError("Auth0 is not configured")

        # Create a temporary db session for Auth0Service
        # Note: In production, this should use dependency injection
        async for db in get_db():
            auth0_service = Auth0Service(db)
            payload = await auth0_service.verify_auth0_token(token)
            return payload
    except Exception as e:
        logger.error(f"Auth0 token verification failed: {str(e)}")
        raise JWTError(f"Invalid Auth0 token: {str(e)}")
