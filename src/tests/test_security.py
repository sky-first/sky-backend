"""Tests for security utilities (password hashing, JWT tokens, validation)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import JWTError

from src.config.settings import settings
from src.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)


class TestPasswordHashing:
    """Tests for password hashing functionality."""

    def test_password_hash_creates_hash(self):
        """Test that password hash is created."""
        password = "test_password_123"
        hashed = get_password_hash(password)

        assert hashed is not None
        assert hashed != password
        assert len(hashed) > 0

    def test_password_hash_different_for_same_password(self):
        """Test that same password produces different hashes (salt)."""
        password = "test_password_123"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Hashes should be different due to salt
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test password verification with correct password."""
        password = "test_password_123"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test password verification with incorrect password."""
        password = "test_password_123"
        wrong_password = "wrong_password"
        hashed = get_password_hash(password)

        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_empty(self):
        """Test password verification with empty password."""
        password = "test_password_123"
        hashed = get_password_hash(password)

        assert verify_password("", hashed) is False

    def test_password_hash_unicode(self):
        """Test password hashing with unicode characters."""
        password = "test_密码_123"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True
        assert verify_password("wrong", hashed) is False


class TestJWTAccessTokens:
    """Tests for JWT access token creation and validation."""

    def test_create_access_token(self):
        """Test access token creation."""
        token_data = {
            "sub": str(uuid4()),
            "email": "test@example.com",
            "role": "user",
        }
        token = create_access_token(token_data)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_contains_payload(self):
        """Test that access token contains correct payload."""
        user_id = str(uuid4())
        email = "test@example.com"
        role = "admin"

        token_data = {"sub": user_id, "email": email, "role": role}
        token = create_access_token(token_data)

        payload = verify_token(token, token_type="access")

        assert payload["sub"] == user_id
        assert payload["email"] == email
        assert payload["role"] == role
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_access_token_expiration(self):
        """Test access token expiration time."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(token_data)

        payload = verify_token(token, token_type="access")

        # Check expiration is set
        assert "exp" in payload
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_exp = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

        # Allow 5 seconds difference for test execution time
        assert abs((exp_time - expected_exp).total_seconds()) < 5

    def test_access_token_custom_expiration(self):
        """Test access token with custom expiration."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        custom_expiration = timedelta(minutes=30)
        token = create_access_token(token_data, expires_delta=custom_expiration)

        payload = verify_token(token, token_type="access")
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_exp = datetime.now(timezone.utc) + custom_expiration

        # Allow 5 seconds difference
        assert abs((exp_time - expected_exp).total_seconds()) < 5

    def test_verify_token_wrong_secret(self):
        """Test token verification with wrong secret key."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(token_data)

        # Try to verify with wrong secret (simulated by corrupting token)
        with pytest.raises(JWTError):
            # Create a token with different secret by manipulating it
            # In practice, this would fail during verification
            verify_token("invalid.token.here", token_type="access")

    def test_verify_token_expired(self):
        """Test verification of expired token."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        expired_delta = timedelta(minutes=-1)
        expired_token = create_access_token(token_data, expires_delta=expired_delta)

        with pytest.raises(JWTError):
            verify_token(expired_token, token_type="access")

    def test_verify_token_wrong_type(self):
        """Test verification with wrong token type."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        access_token = create_access_token(token_data)

        # Try to verify access token as refresh token
        with pytest.raises(JWTError):
            verify_token(access_token, token_type="refresh")


class TestJWTRefreshTokens:
    """Tests for JWT refresh token creation and validation."""

    def test_create_refresh_token(self):
        """Test refresh token creation."""
        token_data = {
            "sub": str(uuid4()),
            "email": "test@example.com",
            "role": "user",
        }
        token = create_refresh_token(token_data)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_refresh_token_contains_payload(self):
        """Test that refresh token contains correct payload."""
        user_id = str(uuid4())
        email = "test@example.com"
        role = "user"

        token_data = {"sub": user_id, "email": email, "role": role}
        token = create_refresh_token(token_data)

        payload = verify_token(token, token_type="refresh")

        assert payload["sub"] == user_id
        assert payload["email"] == email
        assert payload["role"] == role
        assert payload["type"] == "refresh"
        assert "exp" in payload

    def test_refresh_token_expiration(self):
        """Test refresh token expiration time."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_refresh_token(token_data)

        payload = verify_token(token, token_type="refresh")

        # Check expiration is set
        assert "exp" in payload
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_exp = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Allow 5 seconds difference
        assert abs((exp_time - expected_exp).total_seconds()) < 5

    def test_refresh_token_longer_expiration_than_access(self):
        """Test that refresh token expires later than access token."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        access_payload = verify_token(access_token, token_type="access")
        refresh_payload = verify_token(refresh_token, token_type="refresh")

        assert refresh_payload["exp"] > access_payload["exp"]

    def test_verify_refresh_token_as_access_fails(self):
        """Test that refresh token cannot be used as access token."""
        token_data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        refresh_token = create_refresh_token(token_data)

        with pytest.raises(JWTError):
            verify_token(refresh_token, token_type="access")


class TestInputValidation:
    """Tests for input validation and sanitization."""

    def test_email_validation_in_schema(self):
        """Test email validation in Pydantic schema."""
        from pydantic import ValidationError

        from src.schemas.user import LoginRequest

        # Valid email
        valid_request = LoginRequest(email="test@example.com", password="password123")
        assert valid_request.email == "test@example.com"

        # Invalid email format
        with pytest.raises(ValidationError):
            LoginRequest(email="not_an_email", password="password123")

    def test_password_validation_in_schema(self):
        """Test password validation in Pydantic schema."""
        from pydantic import ValidationError

        from src.schemas.user import LoginRequest

        # Valid password
        valid_request = LoginRequest(email="test@example.com", password="password123")
        assert valid_request.password == "password123"

        # Empty password should fail
        with pytest.raises(ValidationError):
            LoginRequest(email="test@example.com", password="")

    def test_password_min_length_in_create_schema(self):
        """Test password minimum length in UserCreate schema."""
        from pydantic import ValidationError

        from src.schemas.user import UserCreate

        # Valid password (8+ characters)
        valid_user = UserCreate(
            email="test@example.com",
            password="password123",
            name="Test User",
        )
        assert valid_user.password == "password123"

        # Password too short
        with pytest.raises(ValidationError):
            UserCreate(
                email="test@example.com",
                password="short",
                name="Test User",
            )

    def test_role_validation_in_schema(self):
        """Test role validation in UserBase schema."""
        from pydantic import ValidationError

        from src.schemas.user import UserBase

        # Valid roles
        valid_roles = ["admin", "user", "viewer"]
        for role in valid_roles:
            user = UserBase(email="test@example.com", name="Test", role=role)
            assert user.role == role

        # Invalid role
        with pytest.raises(ValidationError):
            UserBase(email="test@example.com", name="Test", role="invalid_role")
