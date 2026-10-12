# -*- coding: utf-8 -*-
"""O Sonic corta a pergunta numa pausa a meio? E com o portão?

> «¿Cuál es el precio del gasoil…» — e a Sky respondeu a meio, numa
> pausa curta. — Lucas, 12/10/2026

Mede contra o Sonic VERDADEIRO, com a voz do Polly e uma pausa de sala
(ruído baixo, não zeros) no meio da pergunta:

    «¿Cuál es el precio del gasoil» + pausa + «en Madrid, hoy?»

Para cada pausa, com e sem o `PortaoDaVez`:

  * CORTOU — o Sonic fechou o turno antes da 2.ª metade, ou ouviu a
    pergunta em mais do que um turno;
  * fecho  — quanto depois do fim da fala o Sonic deu o turno por
    acabado (`FalaAcabou`), e quando chegou o primeiro som.

    AWS_PROFILE=... python -I scripts/sonda_a_paciencia.py [patient|normal]

Precisa de `bedrock:InvokeModelWithBidirectionalStream` em eu-north-1 e
de `polly:SynthesizeSpeech` em eu-west-1. Custa cêntimos (8 sessões
curtas). Resultados de 12/10/2026 em `docs/a-voz-medida-nova-sonic.md`.
"""
from __future__ import annotations

import asyncio
import random
import sys
import time

import boto3

sys.path.insert(0, ".")

from src.services import voz_fala_a_fala as falada  # noqa: E402
from src.services import voz_paciencia as vp  # noqa: E402

PRIMEIRA = "¿Cuál es el precio del gasoil"
SEGUNDA = "en Madrid, hoy?"
PAUSAS = [0.7, 1.2]


def diz(texto: str) -> bytes:
    r = boto3.client("polly", region_name="eu-west-1").synthesize_speech(
        Text=texto, OutputFormat="pcm", SampleRate="16000", VoiceId="Lucia", Engine="neural"
    )
    return r["AudioStream"].read()


def aparar(pcm: bytes) -> bytes:
    """Tira o silêncio que o Polly põe antes e depois — senão a pausa
    medida não é a pausa que se pediu (o Polly junta ~0,15 s de cada lado,
    e uma «pausa de 1,2 s» era de 1,45 s)."""
    import array

    a = array.array("h")
    a.frombytes(pcm)
    i, j = 0, len(a)
    while i < j and abs(a[i]) < 300:
        i += 1
    while j > i and abs(a[j - 1]) < 300:
        j -= 1
    return a[i:j].tobytes()


def sala(segundos: float) -> bytes:
    rnd = random.Random(1)
    n = int(16000 * segundos)
    return b"".join(rnd.randint(-60, 60).to_bytes(2, "little", signed=True) for _ in range(n))


async def corrida(a: bytes, b: bytes, pausa: float, portao: vp.PortaoDaVez | None) -> None:
    t0 = time.monotonic()

    def agora() -> float:
        return time.monotonic() - t0

    async def ferramenta(_p: str) -> str:
        return "El gasóleo A cuesta 1,45 euros el litro en Madrid."

    s = falada.SessaoFalada(
        ctx=None,
        voz="lupe",
        ferramenta=ferramenta,
        instrucao="Eres Sky. Responde en español, breve. Usa la herramienta para datos.",
    )
    await s.abrir(await falada.abrir_cliente())
    escuta = asyncio.create_task(s.escutar())
    registo: list[tuple[float, str, str]] = []

    async def ler() -> None:
        som = False
        async for ev in s.eventos():
            if isinstance(ev, falada.Audio):
                if not som:
                    som = True
                    registo.append((agora(), "Audio", ""))
                continue
            registo.append((agora(), type(ev).__name__, getattr(ev, "texto", "")))

    leitor = asyncio.create_task(ler())
    marcos: dict[str, float] = {}

    async def mandar(pcm: bytes, nome: str) -> None:
        passo = int(16000 * 0.032) * 2
        for i in range(0, len(pcm), passo):
            p = pcm[i : i + passo]
            for q in portao.ouvir(p) if portao else [p]:
                await s.ouvir_microfone(q)
            await asyncio.sleep(0.032)
        marcos[nome] = agora()

    await mandar(sala(0.5), "antes")
    if portao:
        portao.ouvi_texto(PRIMEIRA)
    await mandar(a, "a")
    await mandar(sala(pausa), "pausa")
    if portao:
        portao.ouvi_texto(f"{PRIMEIRA} {SEGUNDA}")
    await mandar(b, "b")
    await mandar(sala(6.0), "fim")
    await s.fechar()
    await asyncio.wait({escuta, leitor}, timeout=8)

    # Cortou: reagiu antes da 2.ª metade, ou ouviu a pergunta em pedaços
    # (turnos separados — a pausa passou a paciência).
    cortou = (
        any(
            t < marcos["pausa"]
            for t, n, _ in registo
            if n in ("FalaAcabou", "APensar", "Dito", "Audio")
        )
        or sum(1 for _, n, _x in registo if n == "Ouvido") > 1
    )
    fecho = next(
        (t - marcos["b"] for t, n, _ in registo if n == "FalaAcabou" and t >= marcos["pausa"]), None
    )
    som = next(
        (t - marcos["b"] for t, n, _ in registo if n == "Audio" and t >= marcos["pausa"]), None
    )
    ouvido = [x for _, n, x in registo if n == "Ouvido"]
    print(
        "pausa %.1f s  portao=%-8s  CORTOU=%-5s  fecho=%s  1.o som=%s  ouviu=%r"
        % (
            pausa,
            "sim" if portao else "nao",
            cortou,
            "%+.2f s" % fecho if fecho is not None else "-",
            "%+.2f s" % som if som is not None else "-",
            ouvido,
        ),
        flush=True,
    )


async def principal() -> None:
    nome = sys.argv[1] if len(sys.argv) > 1 else "patient"
    a, b = aparar(diz(PRIMEIRA)), aparar(diz(SEGUNDA))
    print("paciencia=%s %s" % (nome, vp.paciencia_de(nome)), flush=True)
    for pausa in PAUSAS:
        for com in (False, True):
            portao = vp.PortaoDaVez(paciencia=vp.paciencia_de(nome)) if com else None
            try:
                await corrida(a, b, pausa, portao)
            except Exception as exc:  # noqa: BLE001
                print("pausa %.1f falhou: %s: %s" % (pausa, type(exc).__name__, exc), flush=True)


if __name__ == "__main__":
    asyncio.run(principal())
