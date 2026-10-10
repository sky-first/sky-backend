# -*- coding: utf-8 -*-
"""Grava a amostra de cada voz com o PRÓPRIO Sonic — a pré-escuta honesta.

> «tem duas vozes, Lucía e Sérgio. Mas nenhuma das duas é a que está sendo
>  usada… parece que existe uma terceira voz» — Lucas, 10/10

A pré-escuta era o Polly; quem responde é o Sonic, que tem outro catálogo.
Isto pede a cada voz do Sonic que diga a frase de amostra e grava o que
sai, em `src/assets/vozes/<id>.wav`. Correr de novo quando o catálogo mudar:

    AWS_PROFILE=sky-production python -I scripts/gravar_amostras_das_vozes.py

Precisa de `bedrock:InvokeModelWithBidirectionalStream` (eu-north-1) e de
`polly:SynthesizeSpeech` (só para dizer «olá» ao modelo).
"""
from __future__ import annotations

import asyncio
import os
import sys
import wave

import boto3

sys.path.insert(0, ".")

from src.services import voz_fala_a_fala as falada  # noqa: E402
from src.services.vozes import AMOSTRA, CATALOGO  # noqa: E402

DESTINO = os.path.join("src", "assets", "vozes")
OLA = {
    "Portuguese": ("Olá.", "Ines"),
    "Español": ("Hola.", "Lucia"),
    "English": ("Hello.", "Joanna"),
}


def polly(texto: str, voz: str) -> bytes:
    r = boto3.client("polly", region_name="eu-west-1").synthesize_speech(
        Text=texto, OutputFormat="pcm", SampleRate="16000", VoiceId=voz, Engine="neural"
    )
    return r["AudioStream"].read()


async def gravar(sonic_id: str, lingua: str) -> bytes:
    frase = AMOSTRA[lingua]

    async def nada(_p: str) -> str:
        return "{}"

    s = falada.SessaoFalada(
        ctx=None,
        voz=sonic_id,
        instrucao=(
            f"Responde a qualquer coisa que a pessoa diga com ESTA frase e mais "
            f"nada, palavra por palavra: «{frase}»"
        ),
        ferramenta=nada,
    )
    await s.abrir(await falada.abrir_cliente())
    escuta = asyncio.create_task(s.escutar())
    audio = bytearray()
    acabou = asyncio.Event()

    async def ler() -> None:
        async for ev in s.eventos():
            if isinstance(ev, falada.Audio):
                audio.extend(ev.pcm)
            elif isinstance(ev, falada.Dito):
                print(f"  {sonic_id}: {ev.texto}", flush=True)
            elif isinstance(ev, falada.VezDaPessoa):
                acabou.set()

    leitor = asyncio.create_task(ler())
    texto, voz = OLA[lingua]
    pcm = polly(texto, voz)
    passo = int(16000 * 0.032) * 2
    for i in range(0, len(pcm), passo):
        await s.ouvir_microfone(pcm[i : i + passo])
        await asyncio.sleep(0.032)
    for _ in range(int(15 / 0.032)):
        if acabou.is_set():
            break
        await s.silencio()
        await asyncio.sleep(0.032)
    await s.fechar()
    await asyncio.wait({escuta, leitor}, timeout=5)
    return bytes(audio)


async def principal() -> None:
    os.makedirs(DESTINO, exist_ok=True)
    for lingua, vozes in CATALOGO.items():
        for v in vozes:
            pcm = await gravar(v.sonic, lingua)
            caminho = os.path.join(DESTINO, f"{v.id}.wav")
            with wave.open(caminho, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(falada.SAIDA_HZ)
                w.writeframes(pcm)
            print(
                f"{v.id:10s} {lingua:10s} {len(pcm) / 2 / falada.SAIDA_HZ:5.2f} s  {caminho}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(principal())
