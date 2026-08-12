"""Device registry endpoints (BE-06) — register/unregister push tokens.

A mobile client registers its push token after login (and on foreground)
and unregisters on logout. Tenancy is by database, so every row here
already belongs to the caller's tenant; the (user_id, push_token) unique
key makes register idempotent across app relaunches.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.repositories.device_repository import DeviceRepository
from src.schemas.device import DeviceRegister, DeviceResponse

router = APIRouter()


@router.post("", response_model=DeviceResponse, summary="Register (upsert) a push token")
async def register_device(
    payload: DeviceRegister,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DeviceResponse:
    """Register this device's push token, or refresh it if already known.

    Idempotent (T-06.2): re-registering the same token on relaunch updates
    the existing row rather than creating a duplicate.
    """
    device = await DeviceRepository(db).upsert(current_user.id, payload)
    return DeviceResponse.model_validate(device)


@router.delete(
    "/{push_token}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister a push token (logout)",
)
async def unregister_device(
    push_token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Remove a token so the device stops receiving pushes (T-06.12).

    Scoped to the caller, so a user can only ever delete their own token.
    """
    await DeviceRepository(db).delete_by_token(current_user.id, push_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
