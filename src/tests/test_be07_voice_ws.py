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
    """Full turn: audio → partial_transcript → thinking → speaking + tts_audio → final."""
    _mock_auth(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        for _ in range(6):
            ws.send_bytes(b"\x00" * 320)  # mic frames (bytes ignored by the stub)
        ws.send_text(json.dumps({"type": "control", "action": "stop"}))  # end of turn
        ws.send_text(json.dumps({"type": "control", "action": "end"}))  # end session

        states: list[str] = []
        partials = 0
        audio_frames = 0
        got_final = False
        for _ in range(60):
            try:
                m = ws.receive()
            except WebSocketDisconnect:
                break
            if m.get("type") == "websocket.close":
                break
            if m.get("bytes") is not None:
                audio_frames += 1
                continue
            data = json.loads(m["text"])
            if data["type"] == "state":
                states.append(data["value"])
            elif data["type"] == "partial_transcript":
                partials += 1
            elif data["type"] == "final":
                got_final = True
                break

    assert "connecting" in states and "user_speaking" in states
    assert "thinking" in states and "speaking" in states and "ended" in states
    assert states.index("thinking") < states.index("speaking")  # ordering
    assert partials >= 1  # partial transcript streamed
    assert audio_frames >= 1  # tts_audio streamed
    assert got_final
