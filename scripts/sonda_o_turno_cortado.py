# -*- coding: utf-8 -*-
"""O turno cortado de 16/10 contra o Sonic VERDADEIRO.

«¿Qué tienda tuvo más pedidos el último mes?» dita pelo Polly (Lucia),
inteira ou com uma pausa depois de «más», a nível de estúdio (1.0) ou a
nível de Android baixo (0.15, ruído 60). Passa pelo portão antigo
(origin/main), pelo novo, ou por nenhum, e com cada sensibilidade do LOW.

    AWS_PROFILE=... python scripts/sonda_o_turno_cortado.py PCM_DIR SAIDA cenario[,...]

PCM_DIR tem Lucia_inteira.pcm, Lucia_a.pcm («¿Qué tienda tuvo más») e
Lucia_b.pcm («pedidos el último mes?»): PCM16 16 kHz do Polly neural.
Os cenários «antigo_*» precisam de uma cópia do `voz_paciencia.py` de
antes de 16/10 em PCM_DIR/voz_paciencia_antigo.py (`git show
70cfa75e:src/services/voz_paciencia.py`). Escreve o WAV do que o Sonic
ouviu (depois do portão) por cenário. Resultados de 16/10 em
`docs/a-voz-medida-nova-sonic.md`.
"""
from __future__ import annotations

import array
import asyncio
import importlib.util
import json
import os
import random
import sys
import time
import wave

sys.path.insert(0, ".")

from src.services import voz_fala_a_fala as falada  # noqa: E402
from src.services import voz_paciencia as novo  # noqa: E402

PCM, SAIDA = sys.argv[1], sys.argv[2]
antigo = None
_caminho_antigo = os.path.join(PCM, "voz_paciencia_antigo.py")
if os.path.exists(_caminho_antigo):
    _spec = importlib.util.spec_from_file_location("antigo", _caminho_antigo)
    antigo = importlib.util.module_from_spec(_spec)
    sys.modules["antigo"] = antigo
    _spec.loader.exec_module(antigo)
os.makedirs(SAIDA, exist_ok=True)
rnd = random.Random(7)


def ler(n):
    a = array.array("h")
    a.frombytes(open(os.path.join(PCM, n), "rb").read())
    i, j = 0, len(a)
    while i < j and abs(a[i]) < 300:
        i += 1
    while j > i and abs(a[j - 1]) < 300:
        j -= 1
    return a[i:j]


def mix(sig, ganho, ruido):
    return array.array(
        "h", [max(-32768, min(32767, int(x * ganho + rnd.gauss(0, ruido)))) for x in sig]
    ).tobytes()


def sala(seg, ruido):
    return array.array(
        "h", [max(-32768, min(32767, int(rnd.gauss(0, ruido)))) for _ in range(int(16000 * seg))]
    ).tobytes()


# nome: (frase, pausa, ganho, ruido, portao, sensibilidade)
CENARIOS = {
    "sens_low_inteira": ("inteira", 0, 1.0, 60, None, "LOW"),
    "sens_medium_inteira": ("inteira", 0, 1.0, 60, None, "MEDIUM"),
    "sens_high_inteira": ("inteira", 0, 1.0, 60, None, "HIGH"),
    "sens_low_pausa09": ("ab", 0.9, 1.0, 60, None, "LOW"),
    "sens_medium_pausa09": ("ab", 0.9, 1.0, 60, None, "MEDIUM"),
    "sens_high_pausa09": ("ab", 0.9, 1.0, 60, None, "HIGH"),
    "antigo_estudio_inteira": ("inteira", 0, 1.0, 60, "antigo", "LOW"),
    "novo_estudio_inteira": ("inteira", 0, 1.0, 60, "novo", "LOW"),
    "antigo_android_inteira": ("inteira", 0, 0.15, 60, "antigo", "LOW"),
    "novo_android_inteira": ("inteira", 0, 0.15, 60, "novo", "LOW"),
    "antigo_android_pausa09": ("ab", 0.9, 0.15, 60, "antigo", "LOW"),
    "novo_android_pausa09": ("ab", 0.9, 0.15, 60, "novo", "LOW"),
    "antigo_estudio_pausa09": ("ab", 0.9, 1.0, 60, "antigo", "LOW"),
    "novo_estudio_pausa09": ("ab", 0.9, 1.0, 60, "novo", "LOW"),
    "antigo_muitobaixo_pausa09": ("ab", 0.9, 0.1, 40, "antigo", "LOW"),
    "novo_muitobaixo_pausa09": ("ab", 0.9, 0.1, 40, "novo", "LOW"),
    "antigo_muitobaixo_inteira": ("inteira", 0, 0.1, 40, "antigo", "LOW"),
    "novo_muitobaixo_inteira": ("inteira", 0, 0.1, 40, "novo", "LOW"),
}


async def corrida(nome: str) -> dict:
    frase, pausa, ganho, ruido, qual, sens = CENARIOS[nome]
    falada.SENSIBILIDADE_DO_FIM_DE_TURNO = sens
    portao = None
    if qual == "antigo":
        portao = antigo.PortaoDaVez()
    elif qual == "novo":
        portao = novo.PortaoDaVez()
    t0 = time.monotonic()

    def agora():
        return time.monotonic() - t0

    perguntas = []

    async def ferramenta(p: str) -> str:
        perguntas.append((agora(), p))
        return "La Tienda cero uno, de Madrid, tuvo cuatro mil trescientos ochenta y ocho pedidos el último mes."

    s = falada.SessaoFalada(
        ctx=None,
        voz="tiffany",
        ferramenta=ferramenta,
        instrucao=(
            "Eres Sky, la analista de datos. Responde en español de España, breve. "
            "Para cualquier pregunta sobre datos usa SIEMPRE la herramienta consultar_dados "
            "con la pregunta del usuario tal cual."
        ),
    )
    await s.abrir(await falada.abrir_cliente())
    escuta = asyncio.create_task(s.escutar())
    reg = []

    async def ler_eventos():
        som = False
        async for ev in s.eventos():
            if isinstance(ev, falada.Audio):
                if not som:
                    som = True
                    reg.append((agora(), "Audio", ""))
                continue
            reg.append((agora(), type(ev).__name__, getattr(ev, "texto", "")))

    leitor = asyncio.create_task(ler_eventos())
    enviado = bytearray()
    marcos = {}

    async def mandar(pcm: bytes, rotulo: str):
        passo = int(16000 * 0.032) * 2
        for i in range(0, len(pcm), passo):
            p = pcm[i : i + passo]
            for q in portao.ouvir(p) if portao else [p]:
                enviado.extend(q)
                await s.ouvir_microfone(q)
            await asyncio.sleep(0.032)
        marcos[rotulo] = agora()

    await mandar(sala(0.6, ruido), "antes")
    if frase == "inteira":
        await mandar(mix(ler("Lucia_inteira.pcm"), ganho, ruido), "fala")
    else:
        await mandar(mix(ler("Lucia_a.pcm"), ganho, ruido), "a")
        await mandar(sala(pausa, ruido), "pausa")
        await mandar(mix(ler("Lucia_b.pcm"), ganho, ruido), "fala")
    # Depois da fala, o microfone continua a mandar sala até a Sky responder.
    fim = agora() + 12
    while agora() < fim and not any(n == "Audio" for _, n, _x in reg):
        await mandar(sala(0.096, ruido), "sala")
    await asyncio.sleep(2.0)
    await s.fechar()
    await asyncio.wait({escuta, leitor}, timeout=8)

    fim_fala = marcos["fala"]
    ouvidos = [x for _, n, x in reg if n == "Ouvido"]
    cortou = (
        (
            "pausa" in marcos
            and any(
                t < marcos["pausa"] for t, n, _ in reg if n in ("FalaAcabou", "APensar", "Audio")
            )
        )
        or (perguntas and perguntas[0][0] < fim_fala)
        or len(ouvidos) > 1
    )
    fecho = next((t - fim_fala for t, n, _ in reg if n == "FalaAcabou"), None)
    pergunta = perguntas[0] if perguntas else None
    som = next((t - fim_fala for t, n, _ in reg if n == "Audio"), None)
    wav = os.path.join(SAIDA, nome + "_o_que_o_sonic_ouviu.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(enviado))
    out = {
        "cenario": nome,
        "sens": sens,
        "portao": qual or "-",
        "ganho": ganho,
        "pausa": pausa,
        "CORTOU": bool(cortou),
        "ouviu": ouvidos,
        "pergunta_a_ferramenta": pergunta[1] if pergunta else None,
        "ferramenta_s": round(pergunta[0] - fim_fala, 2) if pergunta else None,
        "fecho_s": round(fecho, 2) if fecho is not None else None,
        "primeiro_som_s": round(som, 2) if som is not None else None,
        "medidas_portao": portao.medidas() if hasattr(portao, "medidas") else None,
        "wav": wav,
    }
    print(json.dumps(out, ensure_ascii=False), flush=True)
    with open(os.path.join(SAIDA, "resultados.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    return out


async def principal():
    for nome in sys.argv[3].split(","):
        try:
            await corrida(nome)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"cenario": nome, "erro": repr(exc)}), flush=True)


if __name__ == "__main__":
    asyncio.run(principal())
