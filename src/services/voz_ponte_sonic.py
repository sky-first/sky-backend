# -*- coding: utf-8 -*-
"""As duas peças entre a sessão falada e o protocolo que a app já fala.

── Porquê um módulo, e não dentro do `voice.py` ────────────────────

O `voice.py` já tem ~1000 linhas e uma máquina de estados a funcionar em
produção. As duas peças aqui são puras — uma tradução e um invólucro — e
num ficheiro próprio verificam-se sem WebSocket, sem AWS e sem base de
dados.

As dependências entram por ARGUMENTO, não por import: é o que evita o
ciclo (o `voice.py` é que chama isto) e é o que torna os testes possíveis
sem montar meia aplicação.

── A regra que não se vê daqui, e vale a pena saber ───────────────

O protocolo com a app **não muda**. Nem um campo. A app e a web não sabem
que o motor por baixo é outro — e é essa a condição para se poder voltar
atrás numa variável de ambiente, num produto que é demonstrado a
clientes.

Ver `docs/a-voz-medida-nova-sonic.md`.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.services import voz_fala_a_fala as falada

logger = logging.getLogger(__name__)

#: O que a Sky diz quando o motor avaria.
#:
#: Vai para o modelo em TEXTO, não como excepção, e a diferença é a
#: sessão sobreviver: se não respondermos ao `toolResult`, ele espera até
#: aos 55 s e a sessão morre com a pessoa à espera. Com isto, ele DIZ que
#: não conseguiu — que é melhor do que o silêncio que a voz tem hoje.
AVARIOU = (
    "Não consegui chegar aos dados neste momento. Diz à pessoa que houve "
    "um problema técnico e que pode tentar outra vez."
)

#: E quando não avariou — simplesmente não há resposta nos dados.
#:
#: Separado do anterior de propósito. «Não encontrei» e «avariou» são
#: coisas diferentes para quem ouve, e juntá-las foi metade do defeito
#: que o #713 corrigiu: a voz dizia «não encontrei dados» quando o que se
#: passava era que o motor não recebia metade do contexto.
SEM_RESPOSTA = (
    "Os dados não têm resposta para essa pergunta. Diz isso à pessoa, sem " "inventar números."
)


def ferramenta_do_cliente(
    responder: Callable[..., Awaitable[Optional[str]]],
    *,
    user: Any,
    page_id: Any,
    ctx: Any,
    locale: str,
    space_id: Optional[str],
) -> falada.Ferramenta:
    """A ferramenta que o modelo chama: o nosso motor de SQL.

    O `responder` é o `_voice_answer` do `voice.py`, injectado. Vale a
    pena dizer porquê, porque não é preguiça: ele já carrega **todo** o
    trabalho de paridade com o chat escrito — as ligações todas do
    projecto, o glossário, o tom escolhido, a língua. Foi o que o #713
    corrigiu, e era exactamente a razão pela qual a voz «não encontrava
    dados».

    Reescrever isto para o Sonic era herdar o defeito de novo.

    ── Três respostas, três frases ─────────────────────────────────

    O `responder` tem três saídas e as três têm de chegar ao modelo em
    texto, porque **só ele pode falar**:

      * texto      → os dados, como vieram;
      * `""`       → não há resposta nos dados;
      * `None`     → avariou.

    Nenhuma delas pode levantar excepção daqui para fora: um `toolResult`
    que não chega deixa o modelo à espera, e a sessão morre.
    """

    async def consultar(pergunta: str) -> str:
        if not (pergunta or "").strip():
            # Sem pergunta não há consulta. Acontece se o modelo chamar a
            # ferramenta com o argumento vazio — devolver o nosso texto
            # de «sem resposta» é melhor do que correr um SQL ao calhas.
            return SEM_RESPOSTA
        try:
            resposta = await responder(user, page_id, pergunta, ctx, locale, space_id=space_id)
        except Exception:
            # O `responder` já registra o que lhe acontece; aqui é a
            # última rede, para o modelo receber SEMPRE algo que possa
            # dizer.
            logger.exception(
                "voz/sonic: a consulta rebentou (cliente=%s, projeto=%s)",
                getattr(ctx, "slug", "?"),
                space_id,
            )
            return AVARIOU
        if resposta is None:
            return AVARIOU
        if not resposta.strip():
            return SEM_RESPOSTA
        return resposta

    return consultar


def para_o_protocolo(evento: falada.Evento) -> List[Dict[str, Any]]:
    """Um evento da sessão → as mensagens BE-07 que a app já entende.

    Devolve uma LISTA porque há eventos que valem duas mensagens, e uma
    que é vazia porque há eventos que são só nossos.

    As mensagens saem no formato que o `voice.py` envia: um dicionário
    por mensagem, com `type`. O áudio é a excepção — vai em binário — e
    por isso sai marcado para quem envia saber o que fazer.
    """
    # A transcrição do que a pessoa disse. Vem de graça com o modelo;
    # hoje paga-se ao Transcribe à parte.
    if isinstance(evento, falada.Ouvido):
        return [{"type": "partial_transcript", "text": evento.texto, "final": True}]

    # ── A legenda, e o momento em que ela começa a falar ────────────
    #
    # Duas mensagens, e a segunda era um buraco que quase ficou: sem o
    # `speaking`, a app continuava a mostrar «a Sky está a pensar»
    # enquanto ela já falava.
    #
    # Vai com a legenda e não com o áudio por uma razão medida: o
    # `textOutput` chega **imediatamente antes** do primeiro pedaço de
    # som. Pendurá-lo no áudio obrigava a mandar o estado centenas de
    # vezes por turno, ou a guardar estado aqui — e esta função é pura de
    # propósito. A legenda chega uma vez por frase, que é o ritmo certo.
    if isinstance(evento, falada.Dito):
        return [
            {"type": "state", "value": "speaking"},
            {"type": "sky_text", "text": evento.texto},
        ]

    if isinstance(evento, falada.Audio):
        # Marcado, não formatado: o áudio vai em binário pelo socket e
        # quem envia é que sabe disso. Pôr os bytes num JSON aqui seria
        # inflá-los em base64 por nada.
        return [{"type": "tts_audio", "pcm": evento.pcm}]

    # ── O fim da fala é o nosso «a pensar» ──────────────────────────
    #
    # O modelo diz que a pessoa acabou de falar ~400 ms depois de ela
    # acabar, sem cronómetro nosso. Para a app, é o momento de parar de
    # mostrar «a ouvir».
    if isinstance(evento, falada.FalaAcabou):
        return [{"type": "state", "value": "thinking"}]

    # ── O recado, que é a razão deste evento existir ────────────────
    #
    # **Medido: o modelo cala-se enquanto a ferramenta corre, e não há
    # como o convencer a avisar** — nem por instrução de sistema, nem com
    # duas ferramentas em cadeia, nem empurrando os dados depois. O
    # «deixa-me ver» tem de vir do CLIENTE, e isto é o que lhe diz
    # quando.
    #
    # Vai como `state` e não como um tipo novo: a app já trata o
    # `thinking`, e um tipo novo obrigava a uma build nativa para
    # qualquer coisa acontecer. Sem OTA, isso é semanas.
    if isinstance(evento, falada.APensar):
        return [{"type": "state", "value": "thinking"}]

    # ── A interrupção ───────────────────────────────────────────────
    #
    # Duas mensagens, e as duas são precisas. O `discard_audio` deita
    # fora o que já ia a caminho (sem ele a Sky é cortada no servidor e
    # continua a falar no auscultador); o `state` diz à app que o
    # microfone volta a ser dela.
    if isinstance(evento, falada.Interrompido):
        return [
            {"type": "discard_audio"},
            {"type": "state", "value": "user_speaking"},
        ]

    # ── A avaria ────────────────────────────────────────────────────
    #
    # `turn_failed` e não um erro qualquer: a app distingue-os pelo
    # CÓDIGO — este significa «esta pergunta falhou, continua a ouvir»,
    # e um erro sem código desliga a sessão inteira.
    #
    # A razão fica nos registos, não no ouvido de quem está do outro
    # lado.
    if isinstance(evento, falada.Falhou):
        # ── SÓ o código. Sem `message`. ─────────────────────────────
        #
        # A app faz `onError(e.message || e.code)` e depois escolhe a
        # frase pelo CÓDIGO — tem a tradução nas três línguas. Mandar uma
        # `message` atropela isso: ela ganha ao código e vai para o ecrã
        # tal e qual.
        #
        # Foi o que aconteceu. A minha primeira versão mandava «Não
        # consegui responder a isso.» cravado em português, e o Lucas
        # viu-o **por cima de uma app em espanhol**.
        #
        # A cascata já fazia isto bem, e tinha-o escrito ao lado: «a
        # frase escolhe-se na app, na língua de quem lê». Eu li e não
        # segui.
        return [{"type": "error", "code": "turn_failed"}]

    return []


def e_audio(mensagem: Dict[str, Any]) -> bool:
    """Esta mensagem é áudio binário, e não JSON?"""
    return mensagem.get("type") == "tts_audio" and "pcm" in mensagem
