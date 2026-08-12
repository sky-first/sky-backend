"""Voice pipeline providers (BE-07 / §8).

The WS handler in ``api/v1/voice.py`` is provider-agnostic: it speaks the locked
BE-07 protocol, feeds mic audio to a ``VoiceProvider`` and consumes the
transcript events the provider emits (partials + a final on end-of-utterance).
The provider owns STT **and endpointing** — Amazon Transcribe detects the end of
a turn for real; the stub approximates it with an energy VAD so the protocol and
the state machine are verifiable offline.

Two implementations:
  * ``StubVoiceProvider`` — no network, deterministic. Canned transcript, energy
    VAD, fake PCM. Used for offline/CI verification and when no AWS creds exist.
  * ``AwsVoiceProvider`` (``voice_aws.py``) — Amazon Transcribe streaming STT +
    Amazon Polly TTS. Selected via ``VOICE_STT_PROVIDER=aws``. Credentials never
    reach the device: the app talks to this backend, the backend talks to AWS
    (IRSA in prod, temporary SSO creds in dev).
"""

from __future__ import annotations

import array
import asyncio
import os
from typing import AsyncIterator, Dict, Protocol

# Energy VAD for the stub (Amazon Transcribe does this for real): a turn ends
# after speech FOLLOWED BY a short silence, so silence alone never ends a turn.
_SPEECH_RMS = 500
_MIN_SPEECH_FRAMES = 5
_SILENCE_HANG = 8


def frame_rms(chunk: bytes) -> float:
    """RMS of a little-endian int16 PCM frame (0 for silence)."""
    samples = array.array("h")
    samples.frombytes(chunk[: (len(chunk) // 2) * 2])
    if not samples:
        return 0.0
    return (sum(v * v for v in samples) / len(samples)) ** 0.5


class VoiceProvider(Protocol):
    """STT + TTS boundary. Swapping it never touches the WS protocol."""

    async def start(self, lang: str) -> None: ...

    async def feed_audio(self, chunk: bytes) -> None:
        """Push one mic frame into the STT stream."""
        ...

    async def flush(self) -> None:
        """Force an end-of-utterance (manual stop control)."""
        ...

    async def restart_stt(self) -> None:
        """Start a fresh STT stream for the next turn (see AwsVoiceProvider)."""
        ...

    def transcripts(self) -> AsyncIterator[Dict]:
        """Yield ``{"text": str, "final": bool}`` — final marks end-of-turn."""
        ...

    def synthesize(self, text: str, voice: str) -> AsyncIterator[bytes]:
        """Stream TTS audio (PCM16 mono 16 kHz) for a sentence."""
        ...

    async def close(self) -> None: ...


class StubVoiceProvider:
    """Deterministic, no-network provider so Phase A/C are testable offline.

    Ignores the audio *content* — it returns a canned transcript — but honours
    the audio *energy* for endpointing, so a spoken turn ends on a real pause
    and silence never triggers a turn. Phase B replaces it with Transcribe.
    """

    _PARTIALS = ("How many", "How many clients", "How many clients do we have")
    _FINAL = "How many clients do we have?"

    def __init__(self) -> None:
        self._q: asyncio.Queue = asyncio.Queue()
        self._speech = 0
        self._silence = 0
        self._emitted = 0
        self._closed = False

    async def start(self, lang: str) -> None:
        self._speech = self._silence = self._emitted = 0

    async def feed_audio(self, chunk: bytes) -> None:
        if frame_rms(chunk) > _SPEECH_RMS:
            self._speech += 1
            self._silence = 0
            if self._speech in (3, 6, 9) and self._emitted < len(self._PARTIALS):
                await self._q.put({"text": self._PARTIALS[self._emitted], "final": False})
                self._emitted += 1
        elif self._speech >= _MIN_SPEECH_FRAMES:
            self._silence += 1
            if self._silence >= _SILENCE_HANG:
                await self._endpoint()

    async def _endpoint(self) -> None:
        self._speech = self._silence = self._emitted = 0
        await self._q.put({"text": self._FINAL, "final": True})

    async def flush(self) -> None:
        await self._endpoint()

    async def restart_stt(self) -> None:
        # Nothing to restart — the stub has no network stream. Just reset the
        # VAD counters so the next turn starts clean.
        self._speech = self._silence = self._emitted = 0

    async def transcripts(self) -> AsyncIterator[Dict]:
        while not self._closed:
            ev = await self._q.get()
            if ev is None:
                break
            yield ev

    async def synthesize(self, text: str, voice: str) -> AsyncIterator[bytes]:
        # Spread fake PCM frames over ~1.5s so the "speaking" state is visible.
        for _ in range(6):
            await asyncio.sleep(0.25)
            yield b"\x00\x01" * 4000

    async def close(self) -> None:
        self._closed = True
        await self._q.put(None)


def build_voice_provider() -> VoiceProvider:
    """Stub by default; ``VOICE_STT_PROVIDER=aws`` selects Transcribe + Polly."""
    if os.getenv("VOICE_STT_PROVIDER", "stub").lower() == "aws":
        from src.services.voice_aws import AwsVoiceProvider

        return AwsVoiceProvider()
    return StubVoiceProvider()
