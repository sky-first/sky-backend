"""Tests for authentication middleware."""

from fastapi.testclient import TestClient


class TestPublicRoutes:
    """Tests for public routes that don't require authentication."""

    def test_health_endpoint(self, client: TestClient):
        """Test /health endpoint is public."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_ready_endpoint(self, client: TestClient):
        """Test /ready endpoint is public."""
        response = client.get("/ready")
        assert response.status_code in [200, 503]  # Can be ready or not ready

    def test_live_endpoint(self, client: TestClient):
        """Test /live endpoint is public."""
        response = client.get("/live")
        assert response.status_code == 200

    def test_docs_endpoint(self, client: TestClient):
        """Test /docs endpoint is public."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_endpoint(self, client: TestClient):
        """Test /openapi.json endpoint is public."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_redoc_endpoint(self, client: TestClient):
        """Test /redoc endpoint is public."""
        response = client.get("/redoc")
        assert response.status_code == 200

    def test_login_endpoint_public(self, client: TestClient):
        """Test /api/v1/auth/login endpoint is public."""
        # Should not require auth, but will fail with 401 for invalid credentials
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrong"},
        )
        # Should get 401 for invalid credentials, not for missing auth
        assert response.status_code == 401

    def test_refresh_endpoint_public(self, client: TestClient):
        """Test /api/v1/auth/refresh endpoint is public."""
        # Should not require auth header, but will fail with 401 for invalid token
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid"},
        )
        # Should get 401 for invalid token, not for missing auth
        assert response.status_code == 401

    def test_forgot_password_endpoint_public(self, client: TestClient):
        """Test /api/v1/auth/forgot-password endpoint is public."""
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "test@example.com"},
        )
        assert response.status_code == 200


class TestProtectedRoutes:
    """Tests for protected routes that require authentication."""

    def test_protected_route_no_token(self, client: TestClient):
        """Test protected route without token."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert "Unauthorized" in data["error"]

    def test_protected_route_invalid_header_format(self, client: TestClient):
        """Test protected route with invalid header format."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "InvalidFormat token"},
        )
        assert response.status_code == 401

    def test_protected_route_missing_bearer(self, client: TestClient):
        """Test protected route without Bearer prefix."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "token123"},
        )
        assert response.status_code == 401

    def test_protected_route_invalid_token(self, client: TestClient):
        """Test protected route with invalid token."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    def test_protected_route_expired_token(self, client: TestClient, expired_token: str):
        """Test protected route with expired token."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    def test_protected_route_refresh_token_as_access(
        self, client: TestClient, valid_refresh_token: str
    ):
        """Test protected route with refresh token instead of access token."""
        # Try to use refresh token as access token (should fail)
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {valid_refresh_token}"},
        )
        assert response.status_code == 401

    def test_protected_route_valid_token(self, client: TestClient, test_user_with_tokens: dict):
        """Test protected route with valid token."""
        access_token = test_user_with_tokens["access_token"]

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user_with_tokens["email"]


class TestMiddlewareTokenExtraction:
    """Tests for token extraction and validation in middleware."""

    def test_token_extracts_user_id(self, client: TestClient, test_user_with_tokens: dict):
        """Test that user_id is extracted from token."""
        access_token = test_user_with_tokens["access_token"]

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user_with_tokens["user"].id)

    def test_token_extracts_role(self, client: TestClient, test_user_with_tokens: dict):
        """Test that role is extracted from token."""
        access_token = test_user_with_tokens["access_token"]

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "role" in data
        assert data["role"] == test_user_with_tokens["user"].role

    def test_workspace_endpoint_requires_auth(self, client: TestClient):
        """Test that workspace endpoints require authentication."""
        response = client.get("/api/v1/workspaces")
        assert response.status_code == 401

    def test_dashboard_endpoint_requires_auth(self, client: TestClient):
        """Test that dashboard endpoints require authentication."""
        response = client.get("/api/v1/dashboards")
        assert response.status_code == 401
