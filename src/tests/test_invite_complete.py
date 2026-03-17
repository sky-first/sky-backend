from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.core.security import verify_password
from src.models.user import User
from src.schemas.user import UserCreate
from src.services.invite_service import InviteService
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_invite_user_flow(db_session, faker):
    """Test the complete user invitation flow."""
    # Setup
    # Create admin user
    admin = User(
        id=uuid4(),
        email="admin@example.com",
        name="Admin",
        role="admin",
        password_hash="hash",
        email_verified=True,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    # Create a user to be invited
    new_user_data = UserCreate(
        email="invitee@example.com",
        name="Invitee",
        role="user",
        avatar=None,
        password="TempPassword123!",
    )

    # Instantiate services
    user_service = UserService(db_session)
    invite_service = InviteService(db_session)

    # Mock EmailService to verify it was called
    with patch("src.services.user_service.EmailService") as MockEmailService:
        mock_email_instance = MockEmailService.return_value
        mock_email_instance.send_invite_email.return_value = True

        # 1. Create User (triggers invite)
        created_user = await user_service.create_user(new_user_data, admin)

        assert created_user.email == "invitee@example.com"

        # Verify invite email was sent
        assert mock_email_instance.send_invite_email.called

        # Get the token from the user object in DB
        result = await db_session.execute(
            select(User).where(User.email == "invitee@example.com")
        )
        user_db = result.scalar_one()

        invite_token = user_db.invite_token
        assert invite_token is not None

        # 2. Validate Token
        validation = await invite_service.validate_invite_token(invite_token)
        assert validation["email"] == "invitee@example.com"
        assert validation["invited_by_name"] == "Admin"

        # 3. Accept Invite
        new_password = "SecurePassword123!"
        login_response = await invite_service.accept_invite(invite_token, new_password)

        assert "access_token" in login_response
        assert login_response["user"].email == "invitee@example.com"

        # Verify user status is now active
        await db_session.refresh(user_db)
        assert user_db.status == "active"
        assert user_db.invite_token is None  # Should be cleared

        # Verify password was updated
        assert verify_password(new_password, user_db.password_hash)


@pytest.mark.asyncio
async def test_reinvite_user_flow(db_session):
    """Test re-inviting a user whose token might have expired."""
    # Setup
    user_service = UserService(db_session)

    # Create admin
    admin = User(
        id=uuid4(),
        email="admin2@example.com",
        role="admin",
        password_hash="x",
        name="Admin",
    )
    db_session.add(admin)

    # Create user with expired token or no token
    user = User(
        id=uuid4(),
        email="reinvite@example.com",
        name="Reinvite",
        role="user",
        status="offline",
        password_hash="oldhash",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Mock Email
    with patch("src.services.user_service.EmailService") as MockEmailService:
        mock_email_instance = MockEmailService.return_value
        mock_email_instance.send_invite_email.return_value = True

        # Invite user
        await user_service.invite_user(user.id, {}, admin)

        # Verify token generated
        await db_session.refresh(user)
        assert user.invite_token is not None


@pytest.mark.asyncio
async def test_email_service_mock_mode(faker):
    """Test email service when SMTP is not configured (mock mode)."""
    from src.services.email_service import EmailService

    # Ensure SMTP_HOST is empty
    with patch("src.services.email_service.settings.SMTP_HOST", ""):
        email_service = EmailService()

        # Test successful send (logged only)
        success = email_service.send_invite_email(
            "test@example.com", "http://localhost:3000/invite?token=123", "Admin Name"
        )
        assert success is True


@pytest.mark.asyncio
async def test_email_service_smtp_mode(faker):
    """Test email service with SMTP configuration."""
    from src.services.email_service import EmailService

    with patch("src.services.email_service.settings") as mock_settings:
        mock_settings.SMTP_HOST = "smtp.example.com"
        mock_settings.SMTP_PORT = 587
        mock_settings.SMTP_USER = "user"
        mock_settings.SMTP_PASSWORD = "password"
        mock_settings.SMTP_FROM_EMAIL = "noreply@example.com"
        mock_settings.SMTP_USE_TLS = True

        email_service = EmailService()

        with patch("src.services.email_service.smtplib.SMTP") as MockSMTP:
            # The context manager returns the server instance
            mock_server = MockSMTP.return_value.__enter__.return_value

            success = email_service.send_invite_email(
                "test@example.com",
                "http://localhost:3000/invite?token=123",
                "Admin Name",
            )

            assert success is True
            assert MockSMTP.called
            mock_server.starttls.assert_called()
            mock_server.login.assert_called_with("user", "password")
            mock_server.sendmail.assert_called()
            # quit is not called because of context manager __exit__


@pytest.mark.asyncio
async def test_email_service_failure(faker):
    """Test email service failure handling."""
    from src.services.email_service import EmailService

    with patch("src.services.email_service.settings") as mock_settings:
        mock_settings.SMTP_HOST = "smtp.example.com"
        mock_settings.SMTP_PORT = 587

        email_service = EmailService()

        with patch("src.services.email_service.smtplib.SMTP") as MockSMTP:
            mock_server = MockSMTP.return_value.__enter__.return_value
            # configure mock to raise exception on sendmail
            mock_server.sendmail.side_effect = Exception("SMTP Connection Failed")

            success = email_service.send_invite_email(
                "test@example.com", "link", "Admin"
            )

            assert success is False
