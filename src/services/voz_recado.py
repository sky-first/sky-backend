"""O que a Sky diz enquanto procura.

> «Não está trazendo voz… ele não está dizendo, por exemplo, *ok, você
> quer saber quantos clientes vocês têm? Estou buscando informação*.
> Enquanto isso a gente já ganhou ali um ou dois ou três segundos.»
> — Lucas, 09/10/2026

── Porque é que é nosso e não do modelo ────────────────────────────

Medido a 08/10 (ver ``docs/a-voz-medida-nova-sonic.md``): o Sonic **cala-se**
enquanto a ferramenta corre, e nenhuma das três formas de o convencer a
avisar funcionou — pedir-lho na instrução de sistema (ignora), duas
ferramentas em cadeia (cola o «déjame ver» ao fim), empurrar texto (não abre
turno). Só fala quando não tem nada pendente. Logo, o recado vem de nós,
no momento em que a ferramenta é chamada.

── Porque repete a pergunta ────────────────────────────────────────

É o que um assistente de voz bom faz, e serve para duas coisas: a pessoa
ganha a certeza de que foi ouvida, e se foi ouvida MAL sabe-o logo — em
vez de esperar seis segundos por uma resposta à pergunta errada. O Sonic
reescreve a pergunta antes de a passar à ferramenta; é essa versão, a que
vai mesmo ser respondida, que se repete.

── A mesma pessoa a falar ──────────────────────────────────────────

O Sonic fala com as vozes «ines», «lupe» e «matthew». O Polly tem vozes
neurais com os mesmos nomes. Sai a 16 kHz, que é o que a app toca — não
passa pelo reamostrador do Sonic (que converte de 24 kHz).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

#: Voz do Sonic → voz do Polly com o mesmo nome.
_POLLY = {"ines": "Ines", "lupe": "Lupe", "matthew": "Matthew"}

#: Onde o Polly corre. A Irlanda: o mesmo sítio do pod e do Transcribe.
REGIAO = os.getenv("VOICE_ACK_REGION", "eu-west-1")

#: As palavras com que começa uma pergunta que se pode repetir tal e qual
#: («quer saber QUANTOS clientes temos»). Uma pergunta de sim/não («as
#: vendas subiram?») não cabe na frase e leva o recado curto.
_INTERROGATIVAS = {
    "pt": r"(quant[oa]s?|qua[il]s?|como|onde|quando|quem|o\s+que|que|porqu[eê]|por\s+que)",
    "es": r"(cu[aá]nt[oa]s?|cu[aá]l(es)?|c[oó]mo|d[oó]nde|cu[aá]ndo|qui[eé]n(es)?|qu[eé]|por\s+qu[eé])",
    "en": r"(how|what|which|where|when|who|why)",
}

_FRASES = {
    "pt": ("Quer saber {q} — vou ver.", "Deixe-me ver isso."),
    "es": ("Quiere saber {q}; déjeme mirarlo.", "Déjeme mirarlo."),
    "en": ("You want to know {q} — let me check.", "Let me check that."),
}

#: Uma pergunta muito comprida não se repete: ninguém quer ouvir o
#: parágrafo de volta antes da resposta.
_MAX_PALAVRAS = 14


def ligado() -> bool:
    return os.getenv("VOICE_SPOKEN_ACK", "1").strip().lower() not in ("0", "false", "off", "no")


def recado_de_espera(pergunta: str, locale: str) -> str:
    """A frase a dizer enquanto a consulta corre, na língua da conversa."""
    lingua = (locale or "en")[:2].lower()
    if lingua not in _FRASES:
        lingua = "en"
    com_pergunta, curto = _FRASES[lingua]
    # Em inglês a pergunta não encaixa tal e qual: «you want to know how
    # many stores DO WE HAVE» (ouvido em produção a 10/10). Em português e
    # castelhano a ordem das palavras não muda entre a pergunta e a frase.
    if lingua == "en":
        return curto
    q = " ".join((pergunta or "").split()).strip().strip("¿?¡!.;: ")
    if not q or len(q.split()) > _MAX_PALAVRAS:
        return curto
    # Só se repete uma pergunta que comece por uma interrogativa DESTA
    # língua. Se o modelo a passou noutra («cuántos clientes» numa
    # conversa em português), a frase misturava duas línguas.
    if not re.match(rf"^{_INTERROGATIVAS[lingua]}\b", q, re.IGNORECASE):
        return curto
    # Minúscula à cabeça para encaixar a meio da frase — só quando a
    # segunda letra também é minúscula, para não estragar uma sigla.
    if len(q) > 1 and q[0].isupper() and q[1].islower():
        q = q[0].lower() + q[1:]
    return com_pergunta.format(q=q)


async def sintetizar(texto: str, voz: str) -> AsyncIterator[bytes]:
    """PCM 16 kHz mono, em pedaços, com a voz do Polly que tem o nome da do Sonic."""
    import boto3

    from src.services.vozes import polly_da_sonic

    # A voz do Polly mais parecida com a do Sonic que vai responder: a
    # `carlos` não existe no Polly, e um recado de mulher antes de uma
    # resposta de homem soava a duas pessoas.
    voice_id = polly_da_sonic((voz or "").lower()) or _POLLY.get((voz or "").lower(), "Matthew")
    cliente = boto3.client("polly", region_name=REGIAO)

    def _pedir():
        return cliente.synthesize_speech(
            Text=texto,
            OutputFormat="pcm",
            SampleRate="16000",
            VoiceId=voice_id,
            Engine="neural",
        )

    resposta = await asyncio.to_thread(_pedir)
    corpo = resposta["AudioStream"]
    while True:
        pedaco = await asyncio.to_thread(corpo.read, 8000)
        if not pedaco:
            break
        yield pedaco


async def dizer(enviar_bytes, texto: str, voz: str, *, prazo: float = 4.0) -> bool:
    """Diz o recado. Nunca levanta, e nunca demora mais do que `prazo`.

    Devolve se conseguiu. Um recado que falha é silêncio — exactamente o que
    havia antes — e por isso não pode levar a consulta atrás dele.
    """

    async def _tudo():
        async for pedaco in sintetizar(texto, voz):
            await enviar_bytes(pedaco)

    try:
        await asyncio.wait_for(_tudo(), timeout=prazo)
        return True
    except Exception:  # noqa: BLE001
        logger.info("voz: o recado de espera nao saiu", exc_info=True)
        return False
