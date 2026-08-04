"""Amazon Transcribe (streaming STT) + Amazon Polly (TTS) voice provider (BE-07).

Selected via ``VOICE_STT_PROVIDER=aws``. Credentials are resolved from the
standard AWS chain — IRSA on the cluster, temporary SSO/STS creds in dev — and
NEVER travel to the device: the app speaks the BE-07 WebSocket to this backend,
and only the backend talks to AWS.

Data-residency / privacy: before this runs against real customer audio, the AWS
Organizations *AI services opt-out policy* MUST be enabled (Transcribe/Polly
otherwise may store content for service improvement, possibly out-of-region) —
otherwise it breaks the Trust Center claims. See the voice runbook.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Dict, Optional


def _transcribe_lang(lang: str) -> str:
    return {"English": "en-US", "Portuguese": "pt-BR", "Español": "es-ES"}.get(lang, "en-US")


def _polly_voice(lang: str, requested: str) -> str:
    # A sensible neural default per language; the caller may override.
    if requested and requested not in ("Clara", "Joanna"):
        return requested
    return {"English": "Joanna", "Portuguese": "Camila", "Español": "Lucia"}.get(lang, "Joanna")


class AwsVoiceProvider:
    """STT via Transcribe streaming (own endpointing) + TTS via Polly (PCM16 16k)."""

    def __init__(self) -> None:
        self._q: asyncio.Queue = asyncio.Queue()
        self._region = os.getenv("AWS_REGION", "eu-west-1")
        self._lang = "English"
        self._stream = None
        self._pump: Optional[asyncio.Task] = None
        self._polly = None

    async def start(self, lang: str) -> None:
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler

        self._lang = lang
        client = TranscribeStreamingClient(region=self._region)
        self._stream = await client.start_stream_transcription(
            language_code=_transcribe_lang(lang),
            media_sample_rate_hz=16000,
            media_encoding="pcm",
        )

        queue = self._q

        class _Handler(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, event) -> None:  # noqa: ANN001
                for result in event.transcript.results:
                    if not result.alternatives:
                        continue
                    text = result.alternatives[0].transcript
                    # is_partial False → Transcribe's endpointing closed the turn.
                    await queue.put({"text": text, "final": not result.is_partial})

        handler = _Handler(self._stream.output_stream)
        self._pump = asyncio.create_task(handler.handle_events())

    async def feed_audio(self, chunk: bytes) -> None:
        if self._stream is not None:
            await self._stream.input_stream.send_audio_event(audio_chunk=chunk)

    async def flush(self) -> None:
        # Transcribe endpoints on silence by itself; a manual stop is a no-op so
        # the streaming session survives across turns.
        return None

    async def transcripts(self) -> AsyncIterator[Dict]:
        while True:
            ev = await self._q.get()
            if ev is None:
                break
            yield ev

    async def synthesize(self, text: str, voice: str) -> AsyncIterator[bytes]:
        import boto3

        if self._polly is None:
            self._polly = boto3.client("polly", region_name=self._region)
        voice_id = _polly_voice(self._lang, voice)

        def _synth():
            return self._polly.synthesize_speech(
                Text=text,
                OutputFormat="pcm",  # signed 16-bit, mono, at SampleRate
                SampleRate="16000",
                VoiceId=voice_id,
                Engine="neural",
            )

        resp = await asyncio.to_thread(_synth)
        body = resp["AudioStream"]
        while True:
            chunk = await asyncio.to_thread(body.read, 8000)
            if not chunk:
                break
            yield chunk

    async def close(self) -> None:
        try:
            if self._stream is not None:
                await self._stream.input_stream.end_stream()
        except Exception:
            pass
        if self._pump is not None:
            self._pump.cancel()
        await self._q.put(None)
