"""Voice session endpoints (BE-07 slice).

Today: persist a finished transcript (screen 13 → 08). Later this grows into
the full ``WS /voice/session`` duplex pipeline (§8) — the persistence logic
here becomes its on-close handler.
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.voice import VoiceSessionCreate, VoiceSessionResponse, VoiceTurn
from src.services.voice_session_service import VoiceSessionService

router = APIRouter()

# The client authenticates the WS by offering this subprotocol followed by the
# access token as a second subprotocol (Sec-WebSocket-Protocol). A browser can
# set subprotocols but not headers, and — unlike ?token= — they never land in
# access logs (BE-07 T-07.3).
VOICE_SUBPROTOCOL = "sky.voice.v1"


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


@router.websocket("/session")
async def voice_session_ws(websocket: WebSocket) -> None:
    """Duplex voice pipeline (BE-07 / §8).

    Audio flows both ways, so this is a WebSocket, not SSE. The socket
    authenticates via ``Sec-WebSocket-Protocol`` — NEVER ``?token=`` (a token in
    the URL lands in access logs). Wire format: JSON text frames for
    control/state/transcript/final/error, raw binary frames for audio (mic up,
    TTS down). On close the transcript is persisted as a voice Conversation,
    reusing the REST slice's service.

    Phase A drives a StubVoiceProvider so the protocol + state machine are
    verifiable offline; Phase B swaps in Amazon Transcribe + Polly + the live
    engine behind the same VoiceProvider seam.
    """
    import json as _json
    import time as _time

    from src.config.database import AsyncSessionLocal
    from src.core.security import verify_token
    from src.repositories.user import UserRepository
    from src.services.voice_pipeline import build_voice_provider

    # ── Auth (T-07.1/.2/.3) ───────────────────────────────────────────────
    # A token in the query string is rejected outright — it would be logged.
    if websocket.query_params.get("token"):
        await websocket.close(code=4401)
        return
    protos = [
        p.strip()
        for p in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if p.strip()
    ]
    token = protos[1] if len(protos) >= 2 and protos[0] == VOICE_SUBPROTOCOL else None
    user = None
    if token:
        try:
            payload = verify_token(token, token_type="access")
            uid = payload.get("sub")
            if uid:
                async with AsyncSessionLocal() as db:
                    user = await UserRepository(db).get_by_id(uid)
        except Exception:
            user = None
    if user is None:
        await websocket.close(code=4401)  # handshake rejected, no session
        return

    await websocket.accept(subprotocol=VOICE_SUBPROTOCOL)

    async def send(obj: dict) -> None:
        await websocket.send_text(_json.dumps(obj))

    async def state(value: str) -> None:
        await send({"type": "state", "value": value})

    provider = build_voice_provider()
    await provider.start("en-US")
    started = _time.monotonic()
    turns: list[VoiceTurn] = []
    page_id = None
    muted = False
    persisted = False

    async def finalize(send_final: bool) -> None:
        nonlocal persisted
        if persisted:
            return
        persisted = True
        message_id = None
        if page_id and turns:
            try:
                async with AsyncSessionLocal() as db:
                    u = await UserRepository(db).get_by_id(str(user.id))
                    dur = int((_time.monotonic() - started) * 1000)
                    conv_id, _title, _n = await VoiceSessionService(db).persist(
                        u,
                        VoiceSessionCreate(page_id=page_id, turns=turns, duration_ms=dur),
                    )
                    message_id = str(conv_id)
            except Exception:
                message_id = None
        if send_final:
            try:
                await send({"type": "final", "message_id": message_id})
            except Exception:
                pass

    await state("connecting")
    await state("user_speaking")
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:  # a mic audio frame
                if muted:
                    continue
                partial = await provider.feed_audio(msg["bytes"])
                if partial:
                    await send({"type": "partial_transcript", "text": partial})
                continue
            raw = msg.get("text")
            if not raw:
                continue
            try:
                ctrl = _json.loads(raw)
            except Exception:
                continue
            if ctrl.get("type") != "control":
                continue
            action = ctrl.get("action")
            if action == "start":
                page_id = ctrl.get("page_id") or page_id
                await state("user_speaking")
            elif action == "mute":
                muted = True
            elif action == "unmute":
                muted = False
            elif action == "barge_in":
                # Phase B cancels the in-flight Polly stream; the stub has none.
                await state("user_speaking")
            elif action in ("stop", "end_turn"):
                utter = (await provider.end_of_turn()).strip()
                if not utter:
                    continue
                turns.append(VoiceTurn(role="user", text=utter))
                await state("thinking")
                answer = "".join([tok async for tok in provider.answer(utter)]).strip()
                if answer:
                    turns.append(VoiceTurn(role="sky", text=answer))
                    await state("speaking")
                    async for audio in provider.synthesize(answer, "Joanna"):
                        await websocket.send_bytes(audio)
                await state("user_speaking")
            elif action == "end":
                await state("ended")
                await finalize(send_final=True)
                break
    except WebSocketDisconnect:
        pass
    finally:
        await provider.close()
        await finalize(send_final=False)  # best-effort persist on an abrupt close
    try:
        await websocket.close()
    except Exception:
        pass
