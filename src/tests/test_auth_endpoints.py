import pytest
from httpx import AsyncClient

"""Tests for authentication endpoints."""


class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login."""

    # NOTE: password-based login was removed in favour of SSO. The endpoint
    # now unconditionally raises ForbiddenError, so the success/invalid-email/
    # invalid-password paths all collapse to the same 403 response. These
    # tests pin the current contract so a future re-enable is loud.

    @pytest.mark.asyncio
    async def test_login_password_auth_disabled(self, async_client: AsyncClient, test_user: dict):
        """Password login is disabled — endpoint returns 403 regardless of credentials."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert "error" in data
        assert "SSO" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_login_invalid_email_still_403(self, async_client: AsyncClient, faker):
        """Even non-existent emails get 403, not 401 — password auth is off the table."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": faker.email(),
                "password": "some_password",
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_login_invalid_password_still_403(self, async_client: AsyncClient, test_user: dict):
        """Wrong password gets the same 403 — the endpoint never validates credentials anymore."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": "wrong_password",
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_login_invalid_email_format(self, async_client: AsyncClient):
        """Test login with invalid email format."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": "not_an_email",
                "password": "some_password",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_empty_password(self, async_client: AsyncClient, test_user: dict):
        """Test login with empty password."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": "",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, async_client: AsyncClient):
        """Test login with missing fields."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={},
        )

        assert response.status_code == 422


class TestLogoutEndpoint:
    """Tests for POST /api/v1/auth/logout."""

    @pytest.mark.asyncio
    async def test_logout_success(self, async_client: AsyncClient, test_user_with_tokens: dict):
        """Test successful logout."""
        refresh_token = test_user_with_tokens["refresh_token"]

        response = await async_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "success" in data["message"].lower() or "logged out" in data["message"].lower()

        # Verify token was revoked by trying to refresh it
        refresh_response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_invalid_token(self, async_client: AsyncClient):
        """Test logout with invalid token (should still return 200)."""
        response = await async_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "invalid_token"},
        )

        # Logout should not fail even with invalid token
        assert response.status_code == 200


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh."""

    @pytest.mark.asyncio
    async def test_refresh_success(self, async_client: AsyncClient, test_user_with_tokens: dict):
        """Test successful token refresh."""
        old_refresh_token = test_user_with_tokens["refresh_token"]

        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        assert data["refresh_token"] != old_refresh_token

        # Verify old token was revoked by trying to use it again
        old_token_response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )
        assert old_token_response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, async_client: AsyncClient):
        """Test refresh with invalid token."""
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid_token"},
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_refresh_expired_token(self, async_client: AsyncClient, test_user: dict):
        """Test refresh with expired token."""
        # Use an invalid/expired token format
        # The actual expiration check happens in the service layer
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "expired_token_that_will_fail"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_revoked_token(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        """Test refresh with revoked token."""
        refresh_token = test_user_with_tokens["refresh_token"]

        # Revoke token first
        logout_response = await async_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )
        assert logout_response.status_code == 200

        # Try to refresh with revoked token
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 401


class TestMeEndpoint:
    """Tests for GET /api/v1/auth/me."""

    @pytest.mark.asyncio
    async def test_me_success(self, async_client: AsyncClient, test_user_with_tokens: dict):
        """Test getting current user data."""
        access_token = test_user_with_tokens["access_token"]

        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["email"] == test_user_with_tokens["email"]
        assert data["id"] == str(test_user_with_tokens["user"].id)
        assert "name" in data
        assert "role" in data

    @pytest.mark.asyncio
    async def test_me_no_token(self, async_client: AsyncClient):
        """Test /me without authentication token."""
        response = await async_client.get("/api/v1/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_invalid_token(self, async_client: AsyncClient):
        """Test /me with invalid token."""
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401


class TestSessionEndpoint:
    """Tests for GET /api/v1/auth/session."""

    @pytest.mark.asyncio
    async def test_session_success(self, async_client: AsyncClient, test_user_with_tokens: dict):
        """Test getting current session."""
        access_token = test_user_with_tokens["access_token"]

        response = await async_client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["email"] == test_user_with_tokens["email"]
        assert data["id"] == str(test_user_with_tokens["user"].id)

    @pytest.mark.asyncio
    async def test_session_no_token(self, async_client: AsyncClient):
        """Test /session without authentication token."""
        response = await async_client.get("/api/v1/auth/session")

        assert response.status_code == 401


class TestSessionsEndpoint:
    """Tests for session management endpoints."""

    @pytest.mark.asyncio
    async def test_get_sessions_success(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        """Test getting active sessions."""
        access_token = test_user_with_tokens["access_token"]
        response = await async_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "user_agent" in data[0]

    @pytest.mark.asyncio
    async def test_revoke_all_sessions_success(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        """Test revoking all sessions."""
        access_token = test_user_with_tokens["access_token"]
        response = await async_client.delete(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

        # Verify token is revoked
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        # Note: Access token might still be valid until expiry, but refresh token is revoked
        # Checking refresh token revocation
        refresh_response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": test_user_with_tokens["refresh_token"]},
        )
        assert refresh_response.status_code == 401


class TestForgotPasswordEndpoint:
    """Tests for POST /api/v1/auth/forgot-password."""

    @pytest.mark.asyncio
    async def test_forgot_password_disabled(self, async_client: AsyncClient, test_user: dict):
        """Password reset is disabled alongside password login — returns 403."""
        response = await async_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": test_user["email"]},
        )
        assert response.status_code == 403
        assert "SSO" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent_email_also_disabled(self, async_client: AsyncClient, faker):
        """Unknown emails get the same 403 — the endpoint doesn't look anyone up."""
        response = await async_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": faker.email()},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_forgot_password_invalid_email_format(self, async_client: AsyncClient):
        """Test forgot password with invalid email format."""
        response = await async_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "not_an_email"},
        )

        assert response.status_code == 422


class TestResetPasswordEndpoint:
    """Tests for POST /api/v1/auth/reset-password."""

    @pytest.mark.asyncio
    async def test_reset_password_disabled(self, async_client: AsyncClient):
        """Reset-password is disabled — returns 403, not 400."""
        response = await async_client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "some_token",
                "new_password": "new_password123",
            },
        )
        assert response.status_code == 403
        assert "SSO" in response.json()["error"]["message"]


class TestVerifyEmailEndpoint:
    """Tests for POST /api/v1/auth/verify-email."""

    @pytest.mark.asyncio
    async def test_verify_email_not_applicable(self, async_client: AsyncClient):
        """Email verification is not applicable under SSO — returns 403."""
        response = await async_client.post(
            "/api/v1/auth/verify-email",
            json={"token": "some_token"},
        )
        assert response.status_code == 403
        assert "SSO" in response.json()["error"]["message"]
