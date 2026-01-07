"""Auth0 service for authentication and SSO integration."""

import logging
from typing import Dict, Optional
from uuid import UUID

import httpx
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.auth0 import auth0_settings
from src.core.exceptions import UnauthorizedError
from src.models.user import User
from src.repositories.user import UserRepository

logger = logging.getLogger(__name__)


class Auth0Service:
    """Service for Auth0 authentication and SSO integration."""

    def __init__(self, db: AsyncSession):
        """
        Initialize Auth0 service.

        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)
        self.settings = auth0_settings
        self._jwks_cache: Optional[Dict] = None

    async def get_jwks(self) -> Dict:
        """
        Get Auth0 JWKS (JSON Web Key Set) for token verification.

        Returns:
            Dict: JWKS data

        Raises:
            ValueError: If Auth0 is not configured
        """
        if not self.settings.is_auth0_enabled:
            raise ValueError("Auth0 is not configured")

        # Cache JWKS to avoid repeated requests
        if self._jwks_cache is None:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(self.settings.auth0_jwks_url, timeout=10.0)
                    response.raise_for_status()
                    self._jwks_cache = response.json()
                    logger.info("✅ Fetched Auth0 JWKS successfully")
            except httpx.HTTPError as e:
                logger.error(f"❌ Failed to fetch Auth0 JWKS: {str(e)}")
                raise ValueError(f"Failed to fetch Auth0 JWKS: {str(e)}")

        return self._jwks_cache

    def _get_signing_key(self, token: str, jwks: Dict) -> Dict:
        """
        Get the signing key from JWKS for a given token.

        Args:
            token: JWT token (not decoded)
            jwks: JWKS data

        Returns:
            Dict: Signing key

        Raises:
            ValueError: If no matching key found
        """
        try:
            # Decode token header to get kid (key ID)
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            if not kid:
                raise ValueError("Token header missing 'kid'")

            # Find matching key in JWKS
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    return key

            raise ValueError(f"No matching key found for kid: {kid}")
        except Exception as e:
            logger.error(f"Error getting signing key: {str(e)}")
            raise ValueError(f"Invalid token header: {str(e)}")

    async def verify_auth0_token(self, token: str) -> Dict:
        """
        Verify Auth0 JWT token and return payload.

        Args:
            token: Auth0 JWT token

        Returns:
            Dict: Decoded token payload

        Raises:
            UnauthorizedError: If token is invalid
            ValueError: If Auth0 is not configured
        """
        if not self.settings.is_auth0_enabled:
            raise ValueError("Auth0 is not configured")

        try:
            # Get JWKS
            jwks = await self.get_jwks()

            # Get signing key
            signing_key = self._get_signing_key(token, jwks)

            # Verify and decode token
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[self.settings.AUTH0_ALGORITHM],
                audience=self.settings.AUTH0_AUDIENCE,
                issuer=f"https://{self.settings.AUTH0_DOMAIN}/",
            )

            logger.debug(f"✅ Auth0 token verified successfully: {payload.get('sub')}")
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("❌ Auth0 token expired")
            raise UnauthorizedError("Token expired")
        except jwt.JWTClaimsError as e:
            logger.warning(f"❌ Auth0 token claims error: {str(e)}")
            raise UnauthorizedError(f"Invalid token claims: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Auth0 token verification failed: {str(e)}")
            raise UnauthorizedError(f"Invalid Auth0 token: {str(e)}")

    async def get_user_from_auth0(self, auth0_id: str, provider: str = "auth0") -> Optional[User]:
        """
        Get or create user from Auth0 ID.

        Args:
            auth0_id: Auth0 user ID (sub claim)
            provider: Authentication provider (auth0, google, azure, okta)

        Returns:
            Optional[User]: User if found or created, None otherwise
        """
        # Try to find user by auth0_id
        user = await self.user_repo.get_by_auth0_id(auth0_id)

        if user:
            logger.debug(f"✅ Found existing user with auth0_id: {auth0_id}")
            return user

        # Try to find user by auth_provider_id
        if provider != "auth0":
            user = await self.user_repo.get_by_auth_provider_id(auth0_id, provider)
            if user:
                logger.debug(f"✅ Found existing user with provider {provider} and id: {auth0_id}")
                return user

        logger.debug(f"ℹ️ No user found with auth0_id: {auth0_id}, provider: {provider}")
        return None

    async def create_user_from_auth0(
        self,
        auth0_id: str,
        email: str,
        name: str,
        provider: str = "auth0",
        provider_id: Optional[str] = None,
        avatar: Optional[str] = None,
        sso_metadata: Optional[Dict] = None,
    ) -> User:
        """
        Create new user from Auth0 data.

        Args:
            auth0_id: Auth0 user ID (sub claim)
            email: User email
            name: User name
            provider: Authentication provider (auth0, google, azure, okta)
            provider_id: Provider-specific user ID
            avatar: User avatar URL
            sso_metadata: Additional SSO metadata

        Returns:
            User: Created user

        Raises:
            BadRequestError: If email already exists
        """
        from src.core.exceptions import BadRequestError

        # Check if email already exists
        existing_user = await self.user_repo.get_by_email(email)
        if existing_user:
            # If user exists but doesn't have auth0_id, link it
            if not existing_user.auth0_id and not existing_user.auth_provider_id:
                existing_user.auth0_id = auth0_id
                existing_user.auth_provider = provider
                existing_user.auth_provider_id = provider_id or auth0_id
                existing_user.sso_metadata = sso_metadata
                await self.db.commit()
                await self.db.refresh(existing_user)
                logger.info(f"✅ Linked Auth0 account to existing user: {email}")
                return existing_user
            else:
                raise BadRequestError("User with this email already exists")

        # Create new user
        # For SSO users, we don't set a password (they authenticate via provider)
        # Use a random hash that will never match (SSO users can't login with password)
        from src.core.security import get_password_hash
        import secrets

        # Generate a random password hash that will never be used
        random_password = secrets.token_urlsafe(32)
        password_hash = get_password_hash(random_password)

        user = await self.user_repo.create(
            email=email,
            password_hash=password_hash,
            name=name,
            avatar=avatar,
            role="user",
            auth0_id=auth0_id,
            auth_provider=provider,
            auth_provider_id=provider_id or auth0_id,
            sso_metadata=sso_metadata,
            email_verified=True,  # SSO providers verify emails
        )

        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"✅ Created new user from Auth0: {email}, provider: {provider}")

        # Ensure default planet/space for new users
        from src.services.onboarding_service import ensure_default_planet_and_space

        await ensure_default_planet_and_space(self.db, user)

        return user

    async def sync_user_from_auth0(
        self,
        user: User,
        email: Optional[str] = None,
        name: Optional[str] = None,
        avatar: Optional[str] = None,
        sso_metadata: Optional[Dict] = None,
    ) -> User:
        """
        Sync user data from Auth0.

        Args:
            user: User to update
            email: Updated email (if changed)
            name: Updated name (if changed)
            avatar: Updated avatar (if changed)
            sso_metadata: Updated SSO metadata

        Returns:
            User: Updated user
        """
        updated = False

        if email and user.email != email:
            user.email = email
            updated = True

        if name and user.name != name:
            user.name = name
            updated = True

        if avatar and user.avatar != avatar:
            user.avatar = avatar
            updated = True

        if sso_metadata:
            user.sso_metadata = sso_metadata
            updated = True

        if updated:
            await self.db.commit()
            await self.db.refresh(user)
            logger.info(f"✅ Synced user data from Auth0: {user.email}")

        return user

