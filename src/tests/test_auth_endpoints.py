"""Tests for authentication endpoints."""

from fastapi.testclient import TestClient


class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login."""

    def test_login_success(self, client: TestClient, test_user: dict):
        """Test successful login."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        assert data["expires_in"] > 0
        assert "user" in data
        assert data["user"]["email"] == test_user["email"]
        assert data["user"]["id"] == str(test_user["user"].id)

    def test_login_invalid_email(self, client: TestClient, faker):
        """Test login with non-existent email."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": faker.email(),
                "password": "some_password",
            },
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert "message" in data

    def test_login_invalid_password(self, client: TestClient, test_user: dict):
        """Test login with incorrect password."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": "wrong_password",
            },
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert "message" in data

    def test_login_invalid_email_format(self, client: TestClient):
        """Test login with invalid email format."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "not_an_email",
                "password": "some_password",
            },
        )

        assert response.status_code == 422

    def test_login_empty_password(self, client: TestClient, test_user: dict):
        """Test login with empty password."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": "",
            },
        )

        assert response.status_code == 422

    def test_login_missing_fields(self, client: TestClient):
        """Test login with missing fields."""
        response = client.post(
            "/api/v1/auth/login",
            json={},
        )

        assert response.status_code == 422


class TestLogoutEndpoint:
    """Tests for POST /api/v1/auth/logout."""

    def test_logout_success(self, client: TestClient, test_user_with_tokens: dict):
        """Test successful logout."""
        refresh_token = test_user_with_tokens["refresh_token"]

        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "success" in data["message"].lower() or "logged out" in data["message"].lower()

        # Verify token was revoked by trying to refresh it
        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_response.status_code == 401

    def test_logout_invalid_token(self, client: TestClient):
        """Test logout with invalid token (should still return 200)."""
        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "invalid_token"},
        )

        # Logout should not fail even with invalid token
        assert response.status_code == 200


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh."""

    def test_refresh_success(self, client: TestClient, test_user_with_tokens: dict):
        """Test successful token refresh."""
        old_refresh_token = test_user_with_tokens["refresh_token"]

        response = client.post(
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
        old_token_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )
        assert old_token_response.status_code == 401

    def test_refresh_invalid_token(self, client: TestClient):
        """Test refresh with invalid token."""
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid_token"},
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    def test_refresh_expired_token(self, client: TestClient, test_user: dict):
        """Test refresh with expired token."""
        # Use an invalid/expired token format
        # The actual expiration check happens in the service layer
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "expired_token_that_will_fail"},
        )

        assert response.status_code == 401

    def test_refresh_revoked_token(self, client: TestClient, test_user_with_tokens: dict):
        """Test refresh with revoked token."""
        refresh_token = test_user_with_tokens["refresh_token"]

        # Revoke token first
        logout_response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )
        assert logout_response.status_code == 200

        # Try to refresh with revoked token
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 401


class TestMeEndpoint:
    """Tests for GET /api/v1/auth/me."""

    def test_me_success(self, client: TestClient, test_user_with_tokens: dict):
        """Test getting current user data."""
        access_token = test_user_with_tokens["access_token"]

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["email"] == test_user_with_tokens["email"]
        assert data["id"] == str(test_user_with_tokens["user"].id)
        assert "name" in data
        assert "role" in data

    def test_me_no_token(self, client: TestClient):
        """Test /me without authentication token."""
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401

    def test_me_invalid_token(self, client: TestClient):
        """Test /me with invalid token."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401


class TestSessionEndpoint:
    """Tests for GET /api/v1/auth/session."""

    def test_session_success(self, client: TestClient, test_user_with_tokens: dict):
        """Test getting current session."""
        access_token = test_user_with_tokens["access_token"]

        response = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["email"] == test_user_with_tokens["email"]
        assert data["id"] == str(test_user_with_tokens["user"].id)

    def test_session_no_token(self, client: TestClient):
        """Test /session without authentication token."""
        response = client.get("/api/v1/auth/session")

        assert response.status_code == 401


class TestForgotPasswordEndpoint:
    """Tests for POST /api/v1/auth/forgot-password."""

    def test_forgot_password_success(self, client: TestClient, test_user: dict):
        """Test forgot password with existing email."""
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": test_user["email"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    def test_forgot_password_nonexistent_email(self, client: TestClient, faker):
        """Test forgot password with non-existent email (should still return 200)."""
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": faker.email()},
        )

        # Should return 200 even for non-existent email (security)
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    def test_forgot_password_invalid_email_format(self, client: TestClient):
        """Test forgot password with invalid email format."""
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "not_an_email"},
        )

        assert response.status_code == 422


class TestResetPasswordEndpoint:
    """Tests for POST /api/v1/auth/reset-password."""

    def test_reset_password_not_implemented(self, client: TestClient):
        """Test reset password (not implemented yet)."""
        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "some_token",
                "new_password": "new_password123",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data


class TestVerifyEmailEndpoint:
    """Tests for POST /api/v1/auth/verify-email."""

    def test_verify_email_not_implemented(self, client: TestClient):
        """Test verify email (not implemented yet)."""
        response = client.post(
            "/api/v1/auth/verify-email",
            json={"token": "some_token"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
