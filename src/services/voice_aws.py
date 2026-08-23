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


# As vozes vivem no `src/services/vozes.py`, que e o catalogo unico — nomes,
# genero e a voz Polly correspondente. Esta tabela existia aqui em duplicado e
# tinha, em portugues, «Clara» e «Suave» a apontar as duas para a MESMA voz:
# escolher no ecra nao mudava nada porque nao havia nada para mudar.
#
# Deixa-se passar um VoiceId cru do Polly, que e o que os agendamentos antigos
# e os testes mandam.
from src.services.vozes import CATALOGO as _CATALOGO, voz_polly as _voz_polly


def _polly_voice(lang: str, requested: str) -> str:
    """A voz Polly a usar. Nunca devolve um id invalido.

    Ficar sem som porque a preferencia guardada envelheceu seria pior do que
    a voz nao ser a preferida — por isso o desconhecido cai na omissao da
    lingua em vez de rebentar no Polly.
    """
    conhecidas = {v.polly for vs in _CATALOGO.values() for v in vs}
    if requested in conhecidas:
        return requested  # ja e um VoiceId do Polly
    return _voz_polly(lang, requested)


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
        self._lang = lang
        await self._open()

    async def _open(self) -> None:
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler

        client = TranscribeStreamingClient(region=self._region)
        self._stream = await client.start_stream_transcription(
            language_code=_transcribe_lang(self._lang),
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
        # Transcribe endpoints on silence by itself; a manual stop is a no-op.
        return None

    async def restart_stt(self) -> None:
        """Open a fresh Transcribe stream for the next turn.

        A single long-lived stream goes several seconds without audio while
        Sky speaks (the mic is gated during her turn), and the awscrt HTTP/2
        session can wedge — after that, the *next* turn silently produces no
        transcripts. Restarting per turn keeps each turn on a healthy stream.
        The queue is shared, so ``transcripts()`` keeps yielding across the swap.
        """
        old_stream, old_pump = self._stream, self._pump
        self._stream, self._pump = None, None
        try:
            if old_stream is not None:
                await old_stream.input_stream.end_stream()
        except Exception:
            pass
        if old_pump is not None:
            old_pump.cancel()
        await self._open()

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
