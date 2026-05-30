"""Multi-Factor Authentication endpoints (Phase 3 — TOTP).

All routes here require an authenticated user (enrolment + management);
the login-time MFA redemption lives in ``src/api/v1/auth.py`` as
``POST /auth/login/mfa`` because it must be callable WITHOUT a valid
access token (the user is mid-login).

Routes mounted at ``/mfa`` under ``/api/v1``:

* ``POST   /api/v1/mfa/enroll/start``          — generate TOTP secret + QR
* ``POST   /api/v1/mfa/enroll/verify``         — confirm code, enable MFA
* ``POST   /api/v1/mfa/recovery-codes/rotate`` — mint a new batch of 10
* ``DELETE /api/v1/mfa``                        — disable MFA
* ``GET    /api/v1/mfa/status``                 — read enrolment status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.user import (
    MFAEnrollStartResponse,
    MFAEnrollVerifyRequest,
    MFAEnrollVerifyResponse,
    MFARotateRecoveryCodesResponse,
    MFAStatusResponse,
)
from src.services.mfa_service import DEFAULT_ISSUER, MFAService

router = APIRouter()


@router.get(
    "/status",
    response_model=MFAStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get MFA status",
    description="Returns whether MFA is currently enabled for the caller.",
)
async def get_mfa_status(
    current_user: User = Depends(get_current_user),
) -> MFAStatusResponse:
    return MFAStatusResponse(
        enabled=bool(getattr(current_user, "mfa_enabled", False)),
        enrolled_at=getattr(current_user, "mfa_enrolled_at", None),
        last_used_at=getattr(current_user, "mfa_last_used_at", None),
    )


@router.post(
    "/enroll/start",
    response_model=MFAEnrollStartResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Start MFA enrolment",
    description=(
        "Generates a TOTP secret + otpauth URL + base64 PNG QR code. "
        "The secret is NOT persisted yet — the caller must echo it back "
        "to ``/enroll/verify`` with a valid 6-digit code to finalise."
    ),
)
async def start_enrollment(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MFAEnrollStartResponse:
    if getattr(current_user, "mfa_enabled", False):
        raise BadRequestError(
            "MFA is already enabled. Disable it first to re-enrol."
        )
    mfa = MFAService(db)
    challenge = await mfa.generate_enrollment(current_user)
    return MFAEnrollStartResponse(
        secret=challenge.secret,
        otpauth_url=challenge.otpauth_url,
        qrcode_png_b64=challenge.qrcode_png_b64,
        issuer=DEFAULT_ISSUER,
    )


@router.post(
    "/enroll/verify",
    response_model=MFAEnrollVerifyResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Verify MFA enrolment",
    description=(
        "Confirms a TOTP code against the enrolment secret and persists "
        "the encrypted secret + a single-show batch of recovery codes."
    ),
)
async def verify_enrollment(
    body: MFAEnrollVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MFAEnrollVerifyResponse:
    if getattr(current_user, "mfa_enabled", False):
        raise BadRequestError("MFA is already enabled.")
    mfa = MFAService(db)
    try:
        result = await mfa.verify_enrollment(
            current_user, secret=body.secret, code=body.code
        )
    except ValueError:
        raise BadRequestError(
            "The 6-digit code did not match. Check your authenticator "
            "app's clock and try again."
        )
    await db.commit()
    return MFAEnrollVerifyResponse(
        enabled=True,
        recovery_codes=result.recovery_codes,
        enrolled_at=result.enrolled_at,
    )


@router.post(
    "/recovery-codes/rotate",
    response_model=MFARotateRecoveryCodesResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Rotate MFA recovery codes",
    description=(
        "Mints a fresh batch of single-use recovery codes, invalidating "
        "the previous batch. The returned plaintext list is shown to "
        "the user exactly once."
    ),
)
async def rotate_recovery_codes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MFARotateRecoveryCodesResponse:
    if not getattr(current_user, "mfa_enabled", False):
        raise BadRequestError("MFA is not enabled.")
    mfa = MFAService(db)
    try:
        codes = await mfa.rotate_recovery_codes(current_user)
    except ValueError:
        raise BadRequestError("MFA is not enabled.")
    await db.commit()
    return MFARotateRecoveryCodesResponse(recovery_codes=codes)


@router.delete(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Disable MFA",
    description="Disables MFA for the caller. The TOTP secret and "
    "recovery codes are deleted.",
)
async def disable_mfa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    if not getattr(current_user, "mfa_enabled", False):
        # Idempotent — disabling already-disabled MFA is a no-op so
        # the FE can simplify state machines.
        return SuccessResponse(message="MFA is already disabled.")
    mfa = MFAService(db)
    await mfa.disable_mfa(current_user)
    await db.commit()
    return SuccessResponse(message="MFA disabled.")
