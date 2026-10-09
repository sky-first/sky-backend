# -*- coding: utf-8 -*-
"""A legenda que aparece enquanto a pessoa fala.

── Porque é que isto existe ────────────────────────────────────────

O Nova Sonic **não manda transcrição parcial**. Medido a 09/10/2026 com
voz a sério (`scripts/sonda_a_voz_a_serio.py`): duas falas, exactamente
dois `textOutput` com `role: USER`, cada um no FIM da frase.

    7,395 s  Ouvido  'quantos clientes temos?'
   28,695 s  Ouvido  'e qual foi a faturação do mês passado?'

Do lado de quem fala isso são três pontinhos a girar durante toda a
frase, e depois o texto a aparecer de uma vez:

> «ele está colocando três pontinhos… Ele não pode ficar aqueles três
>  pontinhos ali. Ele tem que, à medida que eu vou falando, ele tem que
>  escrever alguma coisa» — Lucas, 09/10/2026

Não há como tirar isso ao Sonic. Tira-se a outro: o mesmo PCM do
microfone vai também para o Transcribe, que devolve parciais em ~300 ms,
e é dele que sai a legenda.

── O que isto NÃO é ────────────────────────────────────────────────

**Não é a transcrição da conversa.** A que conta — a que vai para o fio
e fica guardada — continua a ser a do Sonic, porque é essa que o modelo
ouviu e sobre a qual respondeu. Esta serve só para haver texto no ecrã
enquanto a frase ainda está a ser dita, e é substituída pela do Sonic
assim que ela chega (a app já trata do `final: true`).

É por isso que uma avaria aqui **não pode calar a conversa**. Se o
Transcribe não abrir, ou rebentar a meio, perde-se a legenda e mais
nada. Todos os caminhos deste módulo engolem o erro e desligam-se.

── O que custa ─────────────────────────────────────────────────────

Pela API de preços da AWS a 09/10/2026, `EU-StreamingAudio` na Irlanda:
**0,0001667 USD/segundo = 0,010 USD/min**, sem escalões. (Estocolmo, onde
vive o Sonic, não tem streaming — só lote.)

Uma pergunta falada tem 3 a 5 s. Quinhentas perguntas por mês num
cliente dão ~0,42 USD. Para passar de 10 USD/mês teria de falar 17 horas.

Só se manda o que vem do MICROFONE. A batida de silêncio que mantém a
sessão do Sonic viva não passa por aqui — pagá-la seria pagar a sessão
inteira em vez da fala.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

#: A região do Transcribe em streaming.
#:
#: **Não é a do Sonic.** O Sonic só existe em `eu-north-1` e essa região
#: não serve `StreamingAudio` — confirmado na API de preços, onde só
#: aparece `TranscribeAudio` (lote). A legenda vem da Irlanda.
REGIAO = os.getenv("VOICE_CAPTION_REGION", "eu-west-1")

#: A língua, pelo locale que a app manda no `start`.
_LINGUAS = {"pt": "pt-PT", "es": "es-ES", "en": "en-US"}
_LINGUA_DE_RECURSO = "en-US"


def lingua_do_locale(locale: str) -> str:
    return _LINGUAS.get((locale or "")[:2], _LINGUA_DE_RECURSO)


def esta_ligada() -> bool:
    """A legenda ao vivo está ligada?

    Ligada por omissão — foi pedida. O interruptor existe para a poder
    desligar sem uma entrega, que é o que se quer ter à mão quando uma
    coisa nova se porta mal num cliente.
    """
    return (os.getenv("VOICE_LIVE_CAPTION", "1") or "").strip().lower() not in {
        "0",
        "false",
        "nao",
        "não",
        "off",
    }


class LegendaAoVivo:
    """O Transcribe a correr ao lado, só para escrever o que se vai dizendo.

    Usa-se assim, e nenhum dos passos levanta:

        legenda = LegendaAoVivo(locale="es")
        await legenda.abrir()
        ...
        await legenda.ouvir(pcm)          # a cada pedaço do microfone
        async for texto in legenda.parciais(): ...
        await legenda.fechar()
    """

    def __init__(self, locale: str, *, regiao: str = REGIAO) -> None:
        self.lingua = lingua_do_locale(locale)
        self.regiao = regiao
        self._fluxo = None
        self._bomba: Optional[asyncio.Task] = None
        self._fila: asyncio.Queue = asyncio.Queue()
        #: Desliga-se sozinha à primeira avaria. Uma legenda que tenta
        #: outra vez a cada pedaço de áudio enche os registos e não
        #: melhora nada.
        self._viva = False

    @property
    def viva(self) -> bool:
        return self._viva

    async def abrir(self) -> None:
        try:
            from amazon_transcribe.client import TranscribeStreamingClient
            from amazon_transcribe.handlers import TranscriptResultStreamHandler
        except Exception as exc:  # noqa: BLE001
            logger.warning("legenda: biblioteca do Transcribe indisponível: %s", exc)
            return

        fila = self._fila

        class _Ouvinte(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, evento) -> None:  # noqa: ANN001
                for resultado in evento.transcript.results:
                    if not resultado.alternatives:
                        continue
                    texto = resultado.alternatives[0].transcript
                    if texto:
                        # O `final` do Transcribe é ignorado de propósito:
                        # quem fecha a frase é o Sonic, e é a transcrição
                        # dele que fica guardada. Daqui só saem parciais.
                        await fila.put(texto)

        try:
            cliente = TranscribeStreamingClient(region=self.regiao)
            self._fluxo = await cliente.start_stream_transcription(
                language_code=self.lingua,
                media_sample_rate_hz=16000,
                media_encoding="pcm",
            )
            self._bomba = asyncio.create_task(_Ouvinte(self._fluxo.output_stream).handle_events())
            self._viva = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("legenda: não abriu (%s: %s)", type(exc).__name__, exc)
            self._viva = False

    async def ouvir(self, pcm: bytes) -> None:
        """Um pedaço do microfone. **Nunca levanta.**"""
        if not self._viva or not pcm:
            return
        try:
            await self._fluxo.input_stream.send_audio_event(audio_chunk=pcm)
        except Exception as exc:  # noqa: BLE001
            # Desliga-se. A conversa continua sem legenda, que é o
            # compromisso que este módulo assume no cabeçalho.
            logger.warning("legenda: desligada a meio (%s: %s)", type(exc).__name__, exc)
            self._viva = False

    async def parciais(self) -> AsyncIterator[str]:
        """O que se vai ouvindo, ainda por confirmar."""
        while True:
            texto = await self._fila.get()
            if texto is None:
                break
            yield texto

    async def fechar(self) -> None:
        self._viva = False
        try:
            if self._fluxo is not None:
                await self._fluxo.input_stream.end_stream()
        except Exception:  # noqa: BLE001
            logger.debug("legenda: falha a fechar o fluxo", exc_info=True)
        if self._bomba is not None:
            self._bomba.cancel()
        # Acorda quem estiver em `parciais()`.
        await self._fila.put(None)
