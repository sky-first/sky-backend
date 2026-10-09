# -*- coding: utf-8 -*-
"""Mede o Nova Sonic a sério: com voz, com duas perguntas, e a registar TUDO.

Responde a duas perguntas que não se conseguem responder a olhar para o
código, e que custaram dois defeitos ao Lucas:

  1. **Há transcrição parcial?** A app mostra «...» enquanto a pessoa fala
     porque o `textOutput` com `role: USER` só aparece uma vez. Se o modelo
     mandar texto do utilizador por pedaços, isto mostra-o — e então não é
     preciso pagar ao Transcribe por uma legenda ao vivo.

  2. **A sessão aguenta DUAS perguntas?** Na lista do Lucas cada pergunta
     virou uma conversa, e uma conversa é uma sessão de WebSocket. Isto faz
     a segunda pergunta DEPOIS de a primeira ser respondida (incluindo a
     chamada à ferramenta) e diz se o canal ainda está de pé.

O que faz: o Polly diz as frases, o PCM vai para o Sonic ao ritmo real, e
cada evento sai com o relógio desde o início, o tipo, o papel e o conteúdo.
Nada é interpretado — o que se quer ver é o que o modelo manda mesmo.

    python -I scripts/sonda_a_voz_a_serio.py

Precisa de credenciais com `bedrock:InvokeModel` **e**
`bedrock:InvokeModelWithBidirectionalStream` (as duas: a primeira sozinha
dá negado), e de `polly:SynthesizeSpeech`.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import boto3

sys.path.insert(0, ".")

from src.services import voz_fala_a_fala as falada  # noqa: E402

REGIAO = "eu-north-1"
REGIAO_DA_FALA = "eu-west-1"
PERGUNTAS = [
    "Quantos clientes temos?",
    "E qual foi a faturacao do mes passado?",
]


def diz(texto: str) -> bytes:
    """O Polly a falar, em PCM16 a 16 kHz — o formato que o Sonic come."""
    # O Polly NAO tem motor neural em eu-north-1 (so o Sonic la vive).
    # A voz do Polly aqui e so um gerador de fala para a medicao, por isso
    # pode vir de outra regiao sem alterar o que se esta a medir.
    polly = boto3.client("polly", region_name=REGIAO_DA_FALA)
    r = polly.synthesize_speech(
        Text=texto, OutputFormat="pcm", SampleRate="16000", VoiceId="Ines", Engine="neural"
    )
    return r["AudioStream"].read()


async def principal() -> None:
    inicio = time.monotonic()

    def marca() -> str:
        return "%7.3f s" % (time.monotonic() - inicio)

    # Uma ferramenta que responde de imediato: o que se mede aqui é o
    # CANAL, não o nosso SQL. Uma consulta lenta só confundiria a leitura.
    async def ferramenta(pergunta: str) -> str:
        print("%s  FERRAMENTA  pedido: %r" % (marca(), pergunta), flush=True)
        return "Temos 128 clientes activos."

    sessao = falada.SessaoFalada(
        ctx=None,
        voz="ines",
        instrucao=(
            "Es a Sky. Responde em portugues de Portugal, curto. "
            "Usa a ferramenta para qualquer pergunta sobre dados."
        ),
        ferramenta=ferramenta,
    )

    # O MESMO construtor que o servidor usa — se as credenciais nao
    # servirem aqui, tambem nao servem la.
    await sessao.abrir(await falada.abrir_cliente())
    print("%s  canal aberto" % marca(), flush=True)

    escuta = asyncio.create_task(sessao.escutar())

    # ── O registo: tudo o que sai, sem filtro ───────────────────────
    ouvidos: list[tuple[float, str]] = []

    async def registar() -> None:
        async for ev in sessao.eventos():
            nome = type(ev).__name__
            if isinstance(ev, falada.Audio):
                continue  # centenas por turno; o que interessa e o texto
            texto = getattr(ev, "texto", "")
            print("%s  %-12s %r" % (marca(), nome, texto), flush=True)
            if isinstance(ev, falada.Ouvido):
                ouvidos.append((time.monotonic() - inicio, texto))

    leitor = asyncio.create_task(registar())

    async def falar(frase: str) -> None:
        pcm = diz(frase)
        print("%s  >> a dizer %r (%d bytes)" % (marca(), frase, len(pcm)), flush=True)
        # 32 ms de cada vez, ao ritmo real: 16000 amostras/s x 2 bytes.
        passo = int(16000 * 0.032) * 2
        for i in range(0, len(pcm), passo):
            await sessao.ouvir_microfone(pcm[i : i + passo])
            await asyncio.sleep(0.032)

    await falar(PERGUNTAS[0])
    # Silencio para o modelo fechar a frase e responder.
    for _ in range(int(12 / 0.032)):
        await sessao.silencio()
        await asyncio.sleep(0.032)

    print("%s  ===== SEGUNDA PERGUNTA, na MESMA sessao =====" % marca(), flush=True)
    await falar(PERGUNTAS[1])
    for _ in range(int(12 / 0.032)):
        await sessao.silencio()
        await asyncio.sleep(0.032)

    await sessao.fechar()
    await asyncio.wait({escuta, leitor}, timeout=5)
    for t in (escuta, leitor):
        t.cancel()

    print("", flush=True)
    print("===== O QUE ISTO RESPONDE =====", flush=True)
    print("Transcricoes do utilizador recebidas: %d" % len(ouvidos), flush=True)
    for q, (t, txt) in enumerate(ouvidos, 1):
        print("  %d. a %6.3f s: %r" % (q, t, txt), flush=True)
    print("", flush=True)
    print(
        "  1 por pergunta  -> NAO ha parciais: a legenda ao vivo tem de vir"
        " de outro sitio (Transcribe em paralelo).",
        flush=True,
    )
    print(
        "  varias por pergunta -> HA parciais e ja os estamos a mandar;" " o defeito esta na app.",
        flush=True,
    )
    print(
        "  2 perguntas respondidas -> a sessao aguenta varios turnos;"
        " as conversas separadas vem do cliente a reabrir o socket.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(principal())
