"""Public demo signup endpoint — Cenário B (per-visitor sandbox).

POST /demo/signup is the only path a non-authenticated visitor has into
the platform. Anti-fraud is layered: server-side Turnstile verification,
per-IP rate limit, throwaway-email block list.

The endpoint is intentionally NOT mounted behind get_current_user — it
issues the JWT itself.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request, status
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.schemas.common import ErrorResponse
from src.schemas.demo import DemoSignupRequest, DemoSignupResponse
from src.services.demo_service import DemoService

router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    """Extracts the visitor IP, honouring X-Forwarded-For when set by the
    ingress. Returns None when nothing is reachable (used for tests)."""
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post(
    "/signup",
    response_model=DemoSignupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Public demo signup",
    description=(
        "Provisions a per-visitor sandbox (Space + guest user) and returns a "
        "JWT pair. Requires a valid Cloudflare Turnstile token. Rate-limited "
        "per source IP. Returning visitors with the same email get their "
        "existing sandbox re-issued instead of a fresh one."
    ),
)
async def signup(
    payload: DemoSignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DemoSignupResponse:
    service = DemoService(db)
    return await service.signup(
        payload=payload,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
