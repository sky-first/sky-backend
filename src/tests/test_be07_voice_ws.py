"""BE-07 — voice-session WebSocket: auth + protocol acceptance tests (T-07.x).

Auth is exercised for real (subprotocol vs ?token=). The happy-path protocol
mocks the token/user lookup (the handler resolves the user via AsyncSessionLocal,
a separate connection from the test engine) so it can drive the StubVoiceProvider
pipeline offline — no Transcribe/Polly/engine needed in Phase A.
"""

import json
import types

import pytest
from starlette.websockets import WebSocketDisconnect

from src.api.v1.voice import VOICE_SUBPROTOCOL

_UID = "00000000-0000-0000-0000-000000000001"


def _mock_auth(monkeypatch):
    monkeypatch.setattr(
        "src.core.security.verify_token",
        lambda token, token_type="access": {"sub": _UID},
    )

    async def _get_by_id(self, uid):
        return types.SimpleNamespace(id=_UID)

    monkeypatch.setattr("src.repositories.user.UserRepository.get_by_id", _get_by_id)


def test_t07_2_unauthorized_rejected(client):
    """No subprotocol / no token → handshake rejected with 4401, no session."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/v1/voice/session"):
            pass
    assert exc.value.code == 4401


def test_t07_3_query_token_rejected(client, monkeypatch):
    """A token in the query string is rejected even if valid (no token in logs)."""
    _mock_auth(monkeypatch)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/v1/voice/session?token=leaky",
            subprotocols=[VOICE_SUBPROTOCOL, "leaky"],
        ):
            pass
    assert exc.value.code == 4401


def test_t07_1_authorized_connects(client, monkeypatch):
    """Authorized client opens the WS → first frame is state:connecting."""
    _mock_auth(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        first = json.loads(ws.receive_text())
        assert first == {"type": "state", "value": "connecting"}


def test_t07_4_happy_turn(client, monkeypatch):
    """Full turn: speech → partial → thinking → speaking + tts_audio → final.

    The grounded answer (engine) is mocked so the turn runs offline; the stub
    provides STT + TTS. Loud frames drive the stub's energy VAD; control:stop
    forces the end-of-utterance.
    """
    _mock_auth(monkeypatch)

    async def _fake_answer(user, page_id, text, ctx):
        return "There are 374 clients."

    monkeypatch.setattr("src.api.v1.voice._voice_answer", _fake_answer)
    loud = (4000).to_bytes(2, "little", signed=True) * 160  # int16 RMS 4000 → speech

    states: list[str] = []
    partials = 0
    audio_frames = 0
    got_final = False
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        for _ in range(9):
            ws.send_bytes(loud)  # speech frames → partial transcripts
        ws.send_text(json.dumps({"type": "control", "action": "stop"}))  # end of turn

        # Drive one full turn, then end the session.
        for _ in range(80):
            m = ws.receive()
            if m.get("type") == "websocket.close":
                break
            if m.get("bytes") is not None:
                audio_frames += 1
            else:
                d = json.loads(m["text"])
                if d["type"] == "state":
                    states.append(d["value"])
                elif d["type"] == "partial_transcript":
                    partials += 1
            if "speaking" in states and states[-1] == "user_speaking" and audio_frames:
                break  # turn complete, back to listening

        ws.send_text(json.dumps({"type": "control", "action": "end"}))
        for _ in range(20):
            m = ws.receive()
            if m.get("type") == "websocket.close":
                break
            if m.get("bytes") is not None:
                continue
            if json.loads(m["text"]).get("type") == "final":
                got_final = True
                break

    assert "connecting" in states and "user_speaking" in states
    assert "thinking" in states and "speaking" in states
    assert states.index("thinking") < states.index("speaking")  # ordering
    assert partials >= 1  # partial transcript streamed
    assert audio_frames >= 1  # tts_audio streamed
    assert got_final
