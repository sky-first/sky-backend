"""Authentication endpoints."""

import secrets
from typing import Optional
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session  # get_current_user usado em outros endpoints
from src.config.auth0 import auth0_settings
from src.core.exceptions import BadRequestError
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.user import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ResetPasswordRequest,
    UserResponse,
    VerifyEmailRequest,
)
from src.services.auth_service import AuthenticationService, user_to_response_dict
from src.services.auth0_service import Auth0Service

router = APIRouter()


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="User registration",
    description="Register a new user and return access and refresh tokens",
)
async def register(
    register_data: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Register endpoint.

    Args:
        register_data: Registration data (email, password, optional name and token)
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If email already exists or validation fails
    """
    auth_service = AuthenticationService(db)
    return await auth_service.register_with_tokens(register_data)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="User login",
    description="Authenticate user and return access and refresh tokens",
)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Login endpoint.

    Args:
        login_data: Login credentials
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data
    """
    auth_service = AuthenticationService(db)
    return await auth_service.login(login_data.email, login_data.password)


@router.post(
    "/logout",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="User logout",
    description="Logout user by revoking refresh token",
)
async def logout(
    refresh_token_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Logout endpoint.

    Args:
        refresh_token_data: Refresh token to revoke
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    auth_service = AuthenticationService(db)
    await auth_service.logout(refresh_token_data.refresh_token)
    return SuccessResponse(message="Logged out successfully")


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Refresh access token",
    description="Get new access token using refresh token",
)
async def refresh_token(
    refresh_token_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db_session),
) -> RefreshTokenResponse:
    """
    Refresh token endpoint.

    Args:
        refresh_token_data: Refresh token
        db: Database session

    Returns:
        RefreshTokenResponse: New access and refresh tokens
    """
    auth_service = AuthenticationService(db)
    return await auth_service.refresh_access_token(refresh_token_data.refresh_token)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get current user",
    description="Get authenticated user information",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Get current user endpoint.

    Args:
        current_user: Current authenticated user

    Returns:
        UserResponse: User data
    """
    return UserResponse.model_validate(user_to_response_dict(current_user))


@router.post(
    "/forgot-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Forgot password",
    description="Request password reset email",
)
async def forgot_password(
    request_data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Forgot password endpoint.

    Args:
        request_data: Email address
        db: Database session

    Returns:
        SuccessResponse: Success message (always returns success for security)
    """
    # TODO: Implement email sending
    # For now, just return success to prevent email enumeration
    return SuccessResponse(message="If the email exists, a password reset link has been sent")


@router.post(
    "/reset-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Reset password",
    description="Reset password using reset token",
)
async def reset_password(
    request_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Reset password endpoint.

    Args:
        request_data: Reset token and new password
        db: Database session

    Returns:
        SuccessResponse: Success message

    Raises:
        BadRequestError: If token is invalid
    """
    # TODO: Implement password reset token validation
    # For now, return error
    raise BadRequestError("Password reset not implemented yet")


@router.post(
    "/verify-email",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Verify email",
    description="Verify user email address",
)
async def verify_email(
    request_data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Verify email endpoint.

    Args:
        request_data: Email verification token
        db: Database session

    Returns:
        SuccessResponse: Success message

    Raises:
        BadRequestError: If token is invalid
    """
    # TODO: Implement email verification
    # For now, return error
    raise BadRequestError("Email verification not implemented yet")


@router.get(
    "/session",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get current session",
    description="Get current authenticated user session information",
)
async def get_session(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Get current session endpoint.

    Args:
        current_user: Current authenticated user

    Returns:
        UserResponse: Current user session data
    """
    return UserResponse.model_validate(user_to_response_dict(current_user))

