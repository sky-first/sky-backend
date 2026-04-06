"""Auth0 service for authentication and SSO integration."""

import logging
import secrets
from typing import Dict, Optional

import httpx
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.auth0 import auth0_settings
from src.core.exceptions import BadRequestError, UnauthorizedError
from src.core.security import create_access_token, create_refresh_token
from src.models.user import RefreshToken, User
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
        import secrets

        from src.core.security import get_password_hash

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

        # Ensure default page/space for new users
        from src.services.onboarding_service import ensure_default_page_and_space

        await ensure_default_page_and_space(self.db, user)

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

    def _generate_state(self) -> str:
        """
        Generate a random state for OAuth flow.

        Returns:
            str: Random state string
        """
        return secrets.token_urlsafe(32)

    async def get_sso_user_info(self, provider: str, access_token: str) -> Dict:
        """
        Get user info from SSO provider using access token.

        Args:
            provider: Provider name (google, azure, okta)
            access_token: OAuth access token

        Returns:
            Dict: User info from provider

        Raises:
            ValueError: If provider is not supported or configured
            UnauthorizedError: If token is invalid
        """
        if provider == "google":
            if not self.settings.is_google_enabled:
                raise ValueError("Google SSO is not configured")
            userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        elif provider == "azure":
            if not self.settings.is_azure_enabled:
                raise ValueError("Azure AD SSO is not configured")
            userinfo_url = "https://graph.microsoft.com/v1.0/me"
        elif provider == "okta":
            if not self.settings.is_okta_enabled:
                raise ValueError("Okta SSO is not configured")
            userinfo_url = f"https://{self.settings.OKTA_DOMAIN}/oauth2/v1/userinfo"
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"Bearer {access_token}"}
                response = await client.get(userinfo_url, headers=headers, timeout=10.0)
                response.raise_for_status()
                user_info = response.json()
                logger.debug(f"✅ Fetched user info from {provider}")
                return user_info
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Failed to fetch user info from {provider}: {e.response.status_code}")
            raise UnauthorizedError(f"Failed to fetch user info from {provider}")
        except httpx.HTTPError as e:
            logger.error(f"❌ Network error fetching user info from {provider}: {str(e)}")
            raise UnauthorizedError(f"Network error: {str(e)}")

    async def handle_google_callback(self, code: str, redirect_uri: str) -> User:
        """
        Handle Google OAuth callback.

        Args:
            code: Authorization code from Google
            redirect_uri: Redirect URI used in authorization

        Returns:
            User: Authenticated user

        Raises:
            BadRequestError: If Google SSO is not configured or callback fails
        """
        if not self.settings.is_google_enabled:
            raise BadRequestError("Google SSO is not configured")

        try:
            # Exchange code for access token
            token_data = {
                "code": code,
                "client_id": self.settings.GOOGLE_CLIENT_ID,
                "client_secret": self.settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.settings.google_token_url,
                    data=token_data,
                    timeout=10.0,
                )
                response.raise_for_status()
                token_response = response.json()
                access_token = token_response.get("access_token")

                if not access_token:
                    raise BadRequestError("Failed to get access token from Google")

                # Get user info
                user_info = await self.get_sso_user_info("google", access_token)

                # Extract user data
                email = user_info.get("email")
                name = user_info.get("name", email.split("@")[0])
                avatar = user_info.get("picture")
                google_id = user_info.get("id")

                if not email:
                    raise BadRequestError("Email not provided by Google")

                # Get or create user
                user = await self.get_user_from_auth0(google_id, provider="google")
                if not user:
                    user = await self.create_user_from_auth0(
                        auth0_id=google_id,
                        email=email,
                        name=name,
                        provider="google",
                        provider_id=google_id,
                        avatar=avatar,
                        sso_metadata={
                            "google_id": google_id,
                            "verified_email": user_info.get("verified_email"),
                        },
                    )
                else:
                    # Sync user data
                    await self.sync_user_from_auth0(
                        user,
                        email=email,
                        name=name,
                        avatar=avatar,
                        sso_metadata={
                            "google_id": google_id,
                            "verified_email": user_info.get("verified_email"),
                        },
                    )

                # Ensure default page exists (idempotent — safe for new and existing users)
                from src.services.onboarding_service import ensure_default_page_and_space
                await ensure_default_page_and_space(self.db, user)

                logger.info(f"✅ Google SSO authentication successful: {email}")
                return user

        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response is not None else "(no body)"
            logger.error(f"❌ Google OAuth callback failed: {e.response.status_code} — {body}")
            raise BadRequestError(f"Google OAuth callback failed: {body}")
        except httpx.HTTPError as e:
            logger.error(f"❌ Google OAuth callback failed: {str(e)}")
            raise BadRequestError(f"Google OAuth callback failed: {str(e)}")

    async def handle_azure_callback(self, code: str, redirect_uri: str) -> User:
        """
        Handle Azure AD OAuth callback.

        Args:
            code: Authorization code from Azure AD
            redirect_uri: Redirect URI used in authorization

        Returns:
            User: Authenticated user

        Raises:
            BadRequestError: If Azure AD SSO is not configured or callback fails
        """
        if not self.settings.is_azure_enabled:
            raise BadRequestError("Azure AD SSO is not configured")

        try:
            # Exchange code for access token
            token_data = {
                "code": code,
                "client_id": self.settings.AZURE_CLIENT_ID,
                "client_secret": self.settings.AZURE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid profile email",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.settings.azure_token_url,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
                response.raise_for_status()
                token_response = response.json()
                access_token = token_response.get("access_token")

                if not access_token:
                    raise BadRequestError("Failed to get access token from Azure AD")

                # Get user info
                user_info = await self.get_sso_user_info("azure", access_token)

                # Extract user data
                email = user_info.get("mail") or user_info.get("userPrincipalName")
                name = user_info.get("displayName") or user_info.get(
                    "givenName", email.split("@")[0] if email else "User"
                )
                avatar = None  # Azure AD doesn't provide avatar in basic profile
                azure_id = user_info.get("id") or user_info.get("userPrincipalName")

                if not email:
                    raise BadRequestError("Email not provided by Azure AD")

                # Get or create user
                user = await self.get_user_from_auth0(azure_id, provider="azure")
                if not user:
                    user = await self.create_user_from_auth0(
                        auth0_id=azure_id,
                        email=email,
                        name=name,
                        provider="azure",
                        provider_id=azure_id,
                        avatar=avatar,
                        sso_metadata={
                            "azure_id": azure_id,
                            "job_title": user_info.get("jobTitle"),
                        },
                    )
                else:
                    # Sync user data
                    await self.sync_user_from_auth0(
                        user,
                        email=email,
                        name=name,
                        avatar=avatar,
                        sso_metadata={
                            "azure_id": azure_id,
                            "job_title": user_info.get("jobTitle"),
                        },
                    )

                from src.services.onboarding_service import ensure_default_page_and_space
                await ensure_default_page_and_space(self.db, user)

                logger.info(f"✅ Azure AD SSO authentication successful: {email}")
                return user

        except httpx.HTTPError as e:
            logger.error(f"❌ Azure AD OAuth callback failed: {str(e)}")
            raise BadRequestError(f"Azure AD OAuth callback failed: {str(e)}")

    async def handle_okta_callback(self, code: str, redirect_uri: str) -> User:
        """
        Handle Okta OAuth callback.

        Args:
            code: Authorization code from Okta
            redirect_uri: Redirect URI used in authorization

        Returns:
            User: Authenticated user

        Raises:
            BadRequestError: If Okta SSO is not configured or callback fails
        """
        if not self.settings.is_okta_enabled:
            raise BadRequestError("Okta SSO is not configured")

        try:
            # Exchange code for access token
            token_data = {
                "code": code,
                "client_id": self.settings.OKTA_CLIENT_ID,
                "client_secret": self.settings.OKTA_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.settings.okta_token_url,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
                response.raise_for_status()
                token_response = response.json()
                access_token = token_response.get("access_token")

                if not access_token:
                    raise BadRequestError("Failed to get access token from Okta")

                # Get user info
                user_info = await self.get_sso_user_info("okta", access_token)

                # Extract user data
                email = user_info.get("email")
                name = user_info.get("name") or user_info.get(
                    "preferred_username", email.split("@")[0] if email else "User"
                )
                avatar = None  # Okta doesn't provide avatar in basic userinfo
                okta_id = user_info.get("sub")

                if not email:
                    raise BadRequestError("Email not provided by Okta")

                # Get or create user
                user = await self.get_user_from_auth0(okta_id, provider="okta")
                if not user:
                    user = await self.create_user_from_auth0(
                        auth0_id=okta_id,
                        email=email,
                        name=name,
                        provider="okta",
                        provider_id=okta_id,
                        avatar=avatar,
                        sso_metadata={
                            "okta_id": okta_id,
                            "email_verified": user_info.get("email_verified"),
                        },
                    )
                else:
                    # Sync user data
                    await self.sync_user_from_auth0(
                        user,
                        email=email,
                        name=name,
                        avatar=avatar,
                        sso_metadata={
                            "okta_id": okta_id,
                            "email_verified": user_info.get("email_verified"),
                        },
                    )

                from src.services.onboarding_service import ensure_default_page_and_space
                await ensure_default_page_and_space(self.db, user)

                logger.info(f"✅ Okta SSO authentication successful: {email}")
                return user

        except httpx.HTTPError as e:
            logger.error(f"❌ Okta OAuth callback failed: {str(e)}")
            raise BadRequestError(f"Okta OAuth callback failed: {str(e)}")

    async def create_login_response(self, user: User) -> Dict:
        """
        Create login response with tokens for SSO user.

        Args:
            user: Authenticated user

        Returns:
            Dict: Login response with access_token, refresh_token, expires_in, and user
        """
        from datetime import datetime, timedelta, timezone

        from src.schemas.user import UserResponse
        from src.services.auth_service import user_to_response_dict

        # Create tokens
        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Save refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 100)  # Effectively infinite
        refresh_token_model = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at,
        )
        self.db.add(refresh_token_model)
        await self.db.commit()

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 365 * 100 * 24 * 60 * 60,  # 100 years in seconds
            "user": UserResponse.model_validate(user_to_response_dict(user)),
        }
