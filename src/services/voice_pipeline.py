"""Voice pipeline providers (BE-07 / §8).

The WS handler in ``api/v1/voice.py`` is provider-agnostic: it speaks the locked
BE-07 protocol (state / partial_transcript / tts_audio / final / error) and
delegates STT, the answer turn and TTS to a ``VoiceProvider``.

Phase A ships ``StubVoiceProvider`` — no network, deterministic — so the
protocol, the subprotocol auth and the state machine can be verified end to end
offline. Phase B swaps in Amazon Transcribe (streaming STT) + Amazon Polly
(TTS), with the answer coming from the existing Bedrock chat graph. Same
interface, no handler change — that is the whole point of the seam.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional, Protocol


class VoiceProvider(Protocol):
    """The audio boundary the WS handler depends on (mirror of the client-side
    SpeechAdapter). Swapping the implementation never touches the protocol."""

    async def start(self, lang: str) -> None: ...

    async def feed_audio(self, chunk: bytes) -> Optional[str]:
        """Ingest one mic frame; return a partial transcript if one is ready."""
        ...

    async def end_of_turn(self) -> str:
        """Finalize the current utterance (VAD/stop) → the full user transcript."""
        ...

    def answer(self, text: str) -> AsyncIterator[str]:
        """Stream the assistant's reply text (Phase B: the Bedrock graph)."""
        ...

    def synthesize(self, text: str, voice: str) -> AsyncIterator[bytes]:
        """Stream TTS audio chunks for a sentence (Phase B: Polly)."""
        ...

    async def close(self) -> None: ...


class StubVoiceProvider:
    """Deterministic, no-network provider so Phase A is testable offline.

    STT ignores the audio bytes and returns a canned transcript; the answer and
    TTS are canned. It exists only to exercise the protocol + state machine
    until Transcribe + Polly + the live engine land in Phase B.
    """

    _PARTIALS = ("How many", "How many clients", "How many clients do we have")
    _FINAL = "How many clients do we have?"
    _ANSWER = (
        "This is a stubbed voice answer — Transcribe, Polly and the live "
        "engine arrive in phase B."
    )

    def __init__(self) -> None:
        self._frames = 0

    async def start(self, lang: str) -> None:
        self._frames = 0

    async def feed_audio(self, chunk: bytes) -> Optional[str]:
        # Emit a growing partial every couple of frames, ignoring the bytes.
        self._frames += 1
        if self._frames in (2, 4, 6):
            return self._PARTIALS[self._frames // 2 - 1]
        return None

    async def end_of_turn(self) -> str:
        self._frames = 0
        return self._FINAL

    async def answer(self, text: str) -> AsyncIterator[str]:
        for word in self._ANSWER.split(" "):
            yield word + " "

    async def synthesize(self, text: str, voice: str) -> AsyncIterator[bytes]:
        # Two short fake PCM frames so the client exercises audio playback.
        yield b"\x00\x01" * 512
        yield b"\x00\x01" * 512

    async def close(self) -> None:
        return None


def build_voice_provider() -> VoiceProvider:
    """Phase A returns the stub. Phase B swaps in Transcribe + Polly here."""
    return StubVoiceProvider()
