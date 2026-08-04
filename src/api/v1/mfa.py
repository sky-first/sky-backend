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


# Note (2026-05-31, Lucas decision):
# The self-service opt-in enrolment endpoints (POST /enroll/start,
# POST /enroll/verify) and the self-service DELETE /mfa endpoint
# were removed. MFA is no longer an opt-in toggle. It is enforced
# on every password login at /auth/login: the BE returns
# ``force_enrollment=true`` on the first password login and the FE
# walks the user through a mandatory QR-scan + 6-digit code step
# closed by /auth/login/mfa-finalize. Regular users cannot disable
# MFA once enrolled. Admin-impersonation support flows still call
# ``MFAService.disable_mfa`` directly via an Internal Console
# endpoint (see services/mfa_service.py docstring).


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


# DELETE /mfa intentionally removed. See note at top of file.
