import pytest
from httpx import AsyncClient

"""Tests for authentication endpoints."""


class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login.

    Password login is now per-tenant (controlled by
    ``tenant.auth_methods.password``). When the request does not carry
    a Host header that resolves to a tenant, the helper falls back to
    ``DEFAULT_AUTH_METHODS`` (Google-only) so the endpoint still
    rejects with 403. These tests pin that default path. The
    tenant-enabled path is covered in ``TestLoginPerTenantAuthMethods``
    below.
    """

    @pytest.mark.asyncio
    async def test_login_com_credenciais_validas(self, async_client: AsyncClient, test_user: dict):
        """A password passou a ser o metodo por omissao.

        Este teste afirmava 403 ("password login is disabled"), o que so
        era verdade porque o defeito global era Google-only. O defeito
        passou a password — a base que funciona sempre e para a qual a
        pipeline gera uma credencial em cada cliente novo. O caminho
        desligado continua coberto em
        test_login_recusado_quando_o_cliente_desliga_a_password.
        """
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_login_email_inexistente_da_401(self, async_client: AsyncClient, faker):
        """Email desconhecido: 401, e a mesma resposta que uma password errada.

        Nao se distingue "esse email nao existe" de "a password esta
        errada" — dizer a diferenca deixa qualquer pessoa descobrir quem
        tem conta.
        """
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": faker.email(),
                "password": "some_password",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_password_errada_da_401(self, async_client: AsyncClient, test_user: dict):
        """Password errada: 401, indistinguivel de um email que nao existe."""
        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user["email"],
                "password": "wrong_password",
            },
        )
        assert response.status_code == 401

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
    async def test_forgot_password_aceite(self, async_client: AsyncClient, test_user: dict):
        """Com a password ligada por omissao, ha password para repor."""
        response = await async_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": test_user["email"]},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_forgot_password_email_desconhecido_responde_igual(self, async_client: AsyncClient, faker):
        """Emails desconhecidos recebem a MESMA resposta que os conhecidos —
        senao este endpoint torna-se um verificador de quem tem conta."""
        response = await async_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": faker.email()},
        )
        assert response.status_code == 200

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
    async def test_reset_password_token_invalido(self, async_client: AsyncClient):
        """Com a password ligada, o endpoint avalia mesmo o token — e um
        token inventado e' recusado por ser invalido, nao por o metodo
        estar desligado."""
        response = await async_client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "some_token",
                "new_password": "new_password123",
            },
        )
        assert response.status_code == 400


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
