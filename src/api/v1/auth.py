"""Authentication endpoints."""

from typing import List, Optional
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (  # get_current_user usado em outros endpoints
    get_current_user,
    get_db_session,
)
from src.config.auth0 import auth0_settings
from src.core.exceptions import BadRequestError
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.permission import EffectivePermissionsResponse
from src.schemas.user import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    InviteGenerateRequest,
    InviteGenerateResponse,
    InviteLoginRequest,
    InviteValidateRequest,
    InviteValidateResponse,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    UserResponse,
    VerifyEmailRequest,
)
from src.services.auth0_service import Auth0Service
from src.services.auth_service import AuthenticationService, user_to_response_dict
from src.services.invite_service import InviteService
from src.services.rbac_service import RBACService

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
    request: Request,
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
    return await auth_service.register_with_tokens(
        register_data,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


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
    request: Request,
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
    try:
        auth_service = AuthenticationService(db)
        result = await auth_service.login(
            login_data.email,
            login_data.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        return result
    except Exception as e:
        # Log the error for debugging
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Login error: {str(e)}", exc_info=True)
        # Re-raise to let FastAPI handle it properly
        raise


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


@router.get(
    "/me/effective-permissions",
    response_model=EffectivePermissionsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get effective permissions",
    description="Return effective permissions for the current user, optionally scoped by space/crew/connection.",
)
async def get_effective_permissions(
    space_id: Optional[str] = Query(None, description="Space context (optional)"),
    crew_id: Optional[str] = Query(None, description="Crew context (optional)"),
    connection_id: Optional[str] = Query(None, description="Connection context (optional)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EffectivePermissionsResponse:
    def _to_uuid(v: Optional[str]) -> Optional[UUID]:
        if not v:
            return None
        try:
            return UUID(v)
        except Exception:
            return None

    rbac = RBACService(db)
    eff = await rbac.get_effective_permissions(
        current_user,
        space_id=_to_uuid(space_id),
        crew_id=_to_uuid(crew_id),
        connection_id=_to_uuid(connection_id),
    )
    return EffectivePermissionsResponse(
        platform_role=eff.platform_role,
        crew_role=eff.crew_role,
        permissions=eff.permissions,
    )


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


@router.get(
    "/sessions",
    response_model=List[SessionResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get active sessions",
    description="Get list of active sessions for the current user",
)
async def get_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[SessionResponse]:
    """
    Get active sessions endpoint.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[SessionResponse]: List of active sessions
    """
    auth_service = AuthenticationService(db)
    sessions = await auth_service.get_active_sessions(current_user.id)
    return [SessionResponse(**s) for s in sessions]


@router.delete(
    "/sessions",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Revoke all sessions",
    description="Revoke all sessions (except usually current one, but here all)",
)
async def revoke_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Revoke all sessions endpoint.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    auth_service = AuthenticationService(db)
    await auth_service.revoke_all_tokens(current_user.id)
    return SuccessResponse(message="All sessions revoked successfully")


@router.post(
    "/change-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Change password",
    description="Change authenticated user password",
)
async def change_password(
    request_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Change password endpoint.

    Args:
        request_data: Current and new password
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    auth_service = AuthenticationService(db)
    await auth_service.change_password(
        current_user.id, request_data.current_password, request_data.new_password
    )
    return SuccessResponse(message="Password changed successfully")


# Invite Endpoints


@router.post(
    "/invite/validate",
    response_model=InviteValidateResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Validate Invite Token",
    description="Validate an invite token and return invite information",
)
async def validate_invite(
    request_data: InviteValidateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> InviteValidateResponse:
    """
    Validate invite token endpoint.

    Args:
        request_data: Invite token to validate
        db: Database session

    Returns:
        InviteValidateResponse: Invite information if valid

    Raises:
        BadRequestError: If token is invalid or expired
    """
    invite_service = InviteService(db)
    try:
        invite_info = await invite_service.validate_invite_token(request_data.token)
        return InviteValidateResponse(
            valid=True,
            email=invite_info.get("email"),
            expires_at=invite_info.get("expires_at"),
            invited_by_name=invite_info.get("invited_by_name"),
            name=invite_info.get("name"),
            message="Invite token is valid",
        )
    except BadRequestError as e:
        return InviteValidateResponse(
            valid=False,
            message=str(e),
        )


@router.post(
    "/invite/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Login with Invite Token",
    description="Authenticate user using invite token and password",
)
async def login_with_invite(
    login_data: InviteLoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Login with invite token endpoint.

    Args:
        login_data: Invite token and password
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If token is invalid or expired
        UnauthorizedError: If password is incorrect
    """
    invite_service = InviteService(db)
    login_response = await invite_service.login_with_invite(login_data.token, login_data.password)
    return LoginResponse(**login_response)


@router.post(
    "/invite/accept",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Accept Invite",
    description="Accept invite, set password and login",
)
async def accept_invite_endpoint(
    login_data: InviteLoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Accept invite endpoint.

    Args:
        login_data: Invite token and new password
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If token is invalid or expired
    """
    invite_service = InviteService(db)
    login_response = await invite_service.accept_invite(login_data.token, login_data.password)
    return LoginResponse(**login_response)


@router.post(
    "/invite/generate",
    response_model=InviteGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Generate Invite Token",
    description="Generate an invite token for a new user (admin only)",
)
async def generate_invite(
    invite_data: InviteGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InviteGenerateResponse:
    """
    Generate invite token endpoint.

    Args:
        invite_data: Email and expiration settings
        current_user: Current authenticated user (must be admin)
        db: Database session

    Returns:
        InviteGenerateResponse: Generated invite token and information

    Raises:
        ForbiddenError: If user is not admin
        BadRequestError: If email already exists
    """
    from src.core.exceptions import ForbiddenError

    # Check if user is admin
    if current_user.role != "admin":
        raise ForbiddenError("Only admins can generate invite tokens")

    invite_service = InviteService(db)
    token = await invite_service.create_invite(
        invited_by=current_user,
        email=invite_data.email,
        expires_days=invite_data.expires_days,
        name=invite_data.name,
    )

    # Get expiration date
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(days=invite_data.expires_days)

    return InviteGenerateResponse(
        token=token,
        email=invite_data.email,
        expires_at=expires_at.isoformat(),
        message=f"Invite token generated successfully. Expires in {invite_data.expires_days} days.",
    )


# SSO Endpoints


@router.get(
    "/sso/{provider}/login",
    status_code=status.HTTP_302_FOUND,
    responses={400: {"model": ErrorResponse}},
    summary="SSO Login",
    description="Redirect to SSO provider login page",
)
async def sso_login(
    provider: str,
    request: Request,
    redirect_uri: Optional[str] = Query(None, description="Redirect URI after authentication"),
    db: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """
    SSO login endpoint - redirects to provider OAuth page.

    Args:
        provider: SSO provider (google, azure, okta)
        redirect_uri: Optional redirect URI (defaults to callback URL)
        request: FastAPI request
        db: Database session

    Returns:
        RedirectResponse: Redirect to provider OAuth page

    Raises:
        BadRequestError: If provider is not supported or not configured
    """
    if provider not in ["google", "azure", "okta"]:
        raise BadRequestError(f"Unsupported SSO provider: {provider}")

    auth0_service = Auth0Service(db)

    # Get redirect URI
    if not redirect_uri:
        base_url = str(request.base_url)
        redirect_uri = f"{base_url.rstrip('/')}/api/v1/auth/sso/{provider}/callback"

    # Get OAuth URL based on provider
    if provider == "google":
        if not auth0_settings.is_google_enabled:
            raise BadRequestError("Google SSO is not configured")
        state = auth0_service._generate_state()
        params = {
            "client_id": auth0_settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        oauth_url = f"{auth0_settings.google_authorization_url}?{urlencode(params)}"
    elif provider == "azure":
        if not auth0_settings.is_azure_enabled:
            raise BadRequestError("Azure AD SSO is not configured")
        state = auth0_service._generate_state()
        params = {
            "client_id": auth0_settings.AZURE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        oauth_url = f"{auth0_settings.azure_authorization_url}?{urlencode(params)}"
    elif provider == "okta":
        if not auth0_settings.is_okta_enabled:
            raise BadRequestError("Okta SSO is not configured")
        state = auth0_service._generate_state()
        params = {
            "client_id": auth0_settings.OKTA_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        oauth_url = f"{auth0_settings.okta_authorization_url}?{urlencode(params)}"
    else:
        raise BadRequestError(f"Unsupported provider: {provider}")

    return RedirectResponse(url=oauth_url, status_code=302)


@router.get(
    "/sso/{provider}/callback",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="SSO Callback",
    description="Handle OAuth callback from SSO provider",
)
async def sso_callback(
    provider: str,
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: Optional[str] = Query(None, description="State parameter from OAuth flow"),
    redirect_uri: Optional[str] = Query(None, description="Redirect URI used in authorization"),
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    SSO callback endpoint - processes OAuth callback and returns tokens.

    Args:
        provider: SSO provider (google, azure, okta)
        code: Authorization code from OAuth provider
        state: Optional state parameter
        redirect_uri: Optional redirect URI (defaults to callback URL)
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If provider is not supported, not configured, or callback fails
    """
    if provider not in ["google", "azure", "okta"]:
        raise BadRequestError(f"Unsupported SSO provider: {provider}")

    auth0_service = Auth0Service(db)

    # Get redirect URI if not provided
    # Note: redirect_uri should be provided by the frontend
    if not redirect_uri:
        redirect_uri = "http://localhost:3000/login/sso/callback"

    # Handle callback based on provider
    if provider == "google":
        user = await auth0_service.handle_google_callback(code, redirect_uri)
    elif provider == "azure":
        user = await auth0_service.handle_azure_callback(code, redirect_uri)
    elif provider == "okta":
        user = await auth0_service.handle_okta_callback(code, redirect_uri)
    else:
        raise BadRequestError(f"Unsupported provider: {provider}")

    # Create login response
    login_response = await auth0_service.create_login_response(user)
    return LoginResponse(**login_response)
