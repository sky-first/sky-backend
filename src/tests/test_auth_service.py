"""Tests for AuthenticationService."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnauthorizedError
from src.models.user import RefreshToken
from src.services.auth_service import AuthenticationService


@pytest.mark.asyncio
class TestAuthenticationServiceLogin:
    """Tests for login functionality."""

    async def test_login_success(self, db_session: AsyncSession, test_user: dict):
        """Test successful login.

        Since 2026-05-31 every password-authenticated account without MFA
        enrolled is redirected to the enrolment flow on first login (Lucas
        decision — phished credentials would otherwise walk straight in).
        The service returns force_enrollment=True with an enrolment token
        instead of issuing access/refresh tokens.  This test verifies that
        contract so a regression of either shape fails loudly.
        """
        auth_service = AuthenticationService(db_session)

        response = await auth_service.login(test_user["email"], test_user["password"])

        # New contract: first password login without MFA → force enrolment.
        assert response.force_enrollment is True
        assert response.mfa_enrollment_token is not None
        assert response.mfa_enrollment_secret is not None
        # No tokens yet — they are issued only after the user completes enrolment.
        assert response.access_token is None
        assert response.refresh_token is None

        # last_login_at is intentionally NOT updated here: bumping it before
        # the second factor would let an attacker with only the password mask
        # repeated probes.  It is set in complete_mfa_login after TOTP succeeds.

    async def test_login_invalid_email(self, db_session: AsyncSession, faker):
        """Test login with non-existent email."""
        auth_service = AuthenticationService(db_session)

        with pytest.raises(UnauthorizedError) as exc_info:
            await auth_service.login(faker.email(), "some_password")

        assert "Invalid email or password" in str(exc_info.value)

    async def test_login_invalid_password(self, db_session: AsyncSession, test_user: dict):
        """Test login with incorrect password."""
        auth_service = AuthenticationService(db_session)

        with pytest.raises(UnauthorizedError) as exc_info:
            await auth_service.login(test_user["email"], "wrong_password")

        assert "Invalid email or password" in str(exc_info.value)


@pytest.mark.asyncio
class TestAuthenticationServiceRefreshToken:
    """Tests for refresh token functionality."""

    async def test_refresh_token_success(
        self, db_session: AsyncSession, test_user_with_tokens: dict
    ):
        """Test successful token refresh."""
        auth_service = AuthenticationService(db_session)
        old_refresh_token = test_user_with_tokens["refresh_token"]

        response = await auth_service.refresh_access_token(old_refresh_token)

        # Verify new tokens are returned
        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.token_type == "bearer"
        assert response.expires_in > 0
        assert response.refresh_token != old_refresh_token

        # Verify old token was revoked
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.token == old_refresh_token)
        )
        old_token_model = result.scalar_one_or_none()
        assert old_token_model is not None
        assert old_token_model.revoked_at is not None

        # Verify new token was created
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.token == response.refresh_token)
        )
        new_token_model = result.scalar_one_or_none()
        assert new_token_model is not None
        assert new_token_model.revoked_at is None

    async def test_refresh_token_invalid(self, db_session: AsyncSession):
        """Test refresh with invalid token."""
        auth_service = AuthenticationService(db_session)

        with pytest.raises(UnauthorizedError) as exc_info:
            await auth_service.refresh_access_token("invalid_token")

        assert "Invalid refresh token" in str(exc_info.value)

    async def test_refresh_token_expired(self, db_session: AsyncSession, test_user: dict):
        """Test refresh with expired token."""
        from src.core.security import create_refresh_token

        # Create an expired refresh token
        token_data = {
            "sub": str(test_user["user"].id),
            "email": test_user["email"],
            "role": test_user["user"].role,
        }
        expired_token = create_refresh_token(token_data)

        # Manually create expired token in database
        expired_at = datetime.now(timezone.utc) - timedelta(days=1)
        expired_token_model = RefreshToken(
            user_id=test_user["user"].id,
            token=expired_token,
            expires_at=expired_at,
        )
        db_session.add(expired_token_model)
        await db_session.commit()

        auth_service = AuthenticationService(db_session)

        with pytest.raises(UnauthorizedError) as exc_info:
            await auth_service.refresh_access_token(expired_token)

        assert "Invalid or expired refresh token" in str(exc_info.value)

    async def test_refresh_token_revoked(
        self, db_session: AsyncSession, test_user_with_tokens: dict
    ):
        """Test refresh with revoked token."""
        auth_service = AuthenticationService(db_session)
        refresh_token = test_user_with_tokens["refresh_token"]

        # Revoke the token
        await auth_service.logout(refresh_token)

        # Try to refresh with revoked token
        with pytest.raises(UnauthorizedError) as exc_info:
            await auth_service.refresh_access_token(refresh_token)

        assert "Invalid or expired refresh token" in str(exc_info.value)


@pytest.mark.asyncio
class TestAuthenticationServiceLogout:
    """Tests for logout functionality."""

    async def test_logout_success(self, db_session: AsyncSession, test_user_with_tokens: dict):
        """Test successful logout."""
        auth_service = AuthenticationService(db_session)
        refresh_token = test_user_with_tokens["refresh_token"]

        # Verify token exists and is not revoked
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token)
        )
        token_model = result.scalar_one_or_none()
        assert token_model is not None
        assert token_model.revoked_at is None

        # Logout
        await auth_service.logout(refresh_token)

        # Verify token was revoked
        await db_session.refresh(token_model)
        assert token_model.revoked_at is not None

    async def test_logout_nonexistent_token(self, db_session: AsyncSession):
        """Test logout with non-existent token (should not raise error)."""
        auth_service = AuthenticationService(db_session)

        # Should not raise error even if token doesn't exist
        await auth_service.logout("nonexistent_token")

        # No exception should be raised


@pytest.mark.asyncio
class TestAuthenticationServiceRevokeAllTokens:
    """Tests for revoke all tokens functionality."""

    async def test_revoke_all_tokens_success(self, db_session: AsyncSession, test_user: dict):
        """Test revoking all tokens for a user."""
        from src.core.security import create_refresh_token

        auth_service = AuthenticationService(db_session)
        user = test_user["user"]

        # Create multiple refresh tokens
        # Add a small delay to ensure unique tokens (JWT includes timestamp)
        import asyncio

        tokens = []
        for i in range(3):
            # Add unique identifier to ensure different tokens
            token_data = {
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "nonce": str(uuid4()),  # Add nonce to ensure uniqueness
            }
            refresh_token = create_refresh_token(token_data)
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            token_model = RefreshToken(
                user_id=user.id,
                token=refresh_token,
                expires_at=expires_at,
            )
            db_session.add(token_model)
            tokens.append(refresh_token)
            # Small delay to ensure different timestamps
            await asyncio.sleep(0.01)

        await db_session.commit()

        # Verify tokens are not revoked
        for token in tokens:
            result = await db_session.execute(
                select(RefreshToken).where(RefreshToken.token == token)
            )
            token_model = result.scalar_one_or_none()
            assert token_model is not None
            assert token_model.revoked_at is None

        # Revoke all tokens
        await auth_service.revoke_all_tokens(user.id)

        # Verify all tokens were revoked
        for token in tokens:
            await db_session.refresh(
                (
                    await db_session.execute(
                        select(RefreshToken).where(RefreshToken.token == token)
                    )
                ).scalar_one()
            )
            result = await db_session.execute(
                select(RefreshToken).where(RefreshToken.token == token)
            )
            token_model = result.scalar_one_or_none()
            assert token_model is not None
            assert token_model.revoked_at is not None


@pytest.mark.asyncio
class TestAuthenticationServiceGetCurrentUser:
    """Tests for get current user functionality."""

    async def test_get_current_user_success(self, db_session: AsyncSession, test_user: dict):
        """Test getting current user."""
        auth_service = AuthenticationService(db_session)
        user = test_user["user"]

        response = await auth_service.get_current_user(user.id)

        assert response.id == user.id
        assert response.email == user.email
        assert response.name == user.name

    async def test_get_current_user_not_found(self, db_session: AsyncSession):
        """Test getting non-existent user."""
        auth_service = AuthenticationService(db_session)
        fake_user_id = uuid4()

        with pytest.raises(UnauthorizedError) as exc_info:
            await auth_service.get_current_user(fake_user_id)

        assert "User not found" in str(exc_info.value)
