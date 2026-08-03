"""Voice session endpoints (BE-07 slice).

Today: persist a finished transcript (screen 13 → 08). Later this grows into
the full ``WS /voice/session`` duplex pipeline (§8) — the persistence logic
here becomes its on-close handler.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.voice import VoiceSessionCreate, VoiceSessionResponse
from src.services.voice_session_service import VoiceSessionService

router = APIRouter()


@router.post(
    "/sessions",
    response_model=VoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Persist a finished voice session as a conversation",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def create_voice_session(
    payload: VoiceSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VoiceSessionResponse:
    try:
        conv_id, title, count = await VoiceSessionService(db).persist(current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=404, detail=str(err))  # avoid page existence leak
    return VoiceSessionResponse(conversation_id=conv_id, title=title, message_count=count)
