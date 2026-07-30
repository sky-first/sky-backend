"""BE-04 · Voice/text origin on messages — acceptance suite T-04.1…T-04.4.

Plus the conversation-level derivation (Option A) that powers the History
row's voice/text icon.
"""

from __future__ import annotations

import uuid

import pytest

from src.models.conversation import Message
from src.schemas.message import MessageResponse
from src.services.conversation_service import ConversationService


def _message(session, conversation_id, *, content="hi", origin=None, duration_ms=None):
    kwargs = dict(conversation_id=conversation_id, role="user", content=content)
    if origin is not None:
        kwargs["origin"] = origin
    if duration_ms is not None:
        kwargs["duration_ms"] = duration_ms
    msg = Message(**kwargs)
    session.add(msg)
    return msg


# ─── T-04.1 & T-04.3 · typed / pre-existing message defaults to 'text' ───────


@pytest.mark.asyncio
async def test_t04_1_typed_message_defaults_to_text(db_session):
    msg = _message(db_session, uuid.uuid4())
    await db_session.commit()
    await db_session.refresh(msg)

    assert msg.origin == "text"
    assert msg.duration_ms is None


# ─── T-04.2 · a voice message persists origin + duration ─────────────────────


@pytest.mark.asyncio
async def test_t04_2_voice_message_persists(db_session):
    # This is what the voice pipeline (BE-07) will write on session end.
    msg = _message(
        db_session, uuid.uuid4(), content="spoken turn", origin="voice", duration_ms=12000
    )
    await db_session.commit()
    await db_session.refresh(msg)

    assert msg.origin == "voice"
    assert msg.duration_ms == 12000


# ─── T-04.4 · the API response carries the correct origin per row ────────────


@pytest.mark.asyncio
async def test_t04_4_response_carries_origin(db_session):
    conv = uuid.uuid4()
    typed = _message(db_session, conv, content="typed")
    spoken = _message(db_session, conv, content="spoken", origin="voice", duration_ms=8000)
    await db_session.commit()
    await db_session.refresh(typed)
    await db_session.refresh(spoken)

    r_typed = MessageResponse.model_validate(typed)
    r_spoken = MessageResponse.model_validate(spoken)

    assert r_typed.origin == "text" and r_typed.duration_ms is None
    assert r_spoken.origin == "voice" and r_spoken.duration_ms == 8000


# ─── Option A · conversation-level voice/text derivation (History icon) ──────


@pytest.mark.asyncio
async def test_conversation_voice_origin_derivation(db_session):
    conv_voice = uuid.uuid4()
    conv_text = uuid.uuid4()
    _message(db_session, conv_voice, content="typed")
    _message(db_session, conv_voice, content="spoken", origin="voice", duration_ms=5000)
    _message(db_session, conv_text, content="typed only")
    await db_session.commit()

    svc = ConversationService(db_session)
    voice_ids = await svc.voice_conversation_ids([conv_voice, conv_text])

    assert conv_voice in voice_ids  # has a spoken turn → 'voice' icon
    assert conv_text not in voice_ids  # text only → 'text' icon
    assert await svc.voice_conversation_ids([]) == set()  # no crash on empty
