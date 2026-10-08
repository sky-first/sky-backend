# -*- coding: utf-8 -*-
"""O WebSocket da voz, servido pelo Nova Sonic.

── Porque é um handler À PARTE, e não um `if` lá dentro ────────────

O `voice_session_ws` do `voice.py` tem ~500 linhas e uma máquina de
estados em produção: cronómetro de fim de turno, segmentos, descarte de
áudio durante o turno, reabertura da transcrição por língua. Nada disso
existe aqui — o modelo faz tudo.

Enfiar os dois caminhos na mesma função dava um `if` por cada uma dessas
peças, e a cascata — que é o que funciona hoje e o que é demonstrado a
clientes — ficava a pagar o preço de uma experiência.

Então: a bandeira escolhe a função. A cascata não é tocada, nem numa
linha, e voltar atrás é uma variável de ambiente.

── O que este ficheiro NÃO faz ─────────────────────────────────────

Não traduz eventos (é a `voz_ponte_sonic`) nem fala com o Bedrock (é a
`voz_fala_a_fala`). Aqui é só a coreografia: quem espera por quem, o que
mantém a sessão viva, e o que se guarda no fim.

Ver `docs/a-voz-medida-nova-sonic.md`.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time as _time
from typing import Any, Callable, Dict, List, Optional

from src.services import voz_fala_a_fala as falada
from src.services import voz_ponte_sonic as ponte

logger = logging.getLogger(__name__)

#: A voz do modelo, por língua.
#:
#: **Não são as vozes do Polly.** O catálogo é outro, e um id que ele não
#: conheça faz a abertura falhar — não degrada, falha. Só estas duas
#: foram verificadas numa chamada real (`lupe` em es-ES, `ines` em
#: pt-PT); as outras ficam de fora até alguém as ouvir.
VOZES = {
    "pt": "ines",
    "es": "lupe",
    "en": "matthew",
}
VOZ_DE_RECURSO = "matthew"

#: De quanto em quanto tempo se alimenta silêncio quando ninguém fala.
#:
#: O modelo desliga depois de `LIMITE_SEM_AUDIO` (55 s, medido) sem áudio
#: nem conteúdo interactivo. Isto tem de ser folgadamente menor — e o
#: silêncio não é facturado, também medido, por isso não há razão para
#: ser avarento.
BATIDA_DO_SILENCIO = 2.0

#: Quanto tempo se espera pelo `start` do cliente antes de desistir.
#:
#: Sem o `start` não se sabe o projecto nem a língua, e abrir a sessão
#: sem isso era voltar ao defeito que o #713 corrigiu: responder dos
#: dados de outro projecto.
PRAZO_DO_START = 10.0


def voz_do_locale(locale: str, escolhida: Optional[str] = None) -> str:
    """A voz do modelo. A escolha da pessoa só vale se existir no catálogo.

    O ecrã de definições guarda nomes do catálogo do **Polly** («Inês»,
    «Lúcia»). Mandá-los ao Sonic faz a abertura falhar, e o sintoma seria
    «a voz não funciona» sem nada que o explique. Por isso só se aceita
    um id que esteja aqui.
    """
    if escolhida and escolhida in VOZES.values():
        return escolhida
    return VOZES.get((locale or "")[:2], VOZ_DE_RECURSO)


def instrucao_de_sistema(locale: str) -> str:
    """O que a Sky é, em três linhas, na língua de quem fala.

    Curto de propósito. O glossário e as métricas **não** entram aqui:
    entram pelo motor de SQL, que é quem sabe o que fazer com eles — e
    repeti-los no prompt de voz era pagar tokens de entrada em cada turno
    por contexto que já viaja no sítio certo.
    """
    lingua = {
        "pt": "português de Portugal",
        "es": "español",
        "en": "English",
    }.get((locale or "")[:2], "English")
    return (
        f"És a Sky, a analista de dados da empresa. Responde SEMPRE em "
        f"{lingua}, em uma ou duas frases curtas, como numa conversa — "
        f"nunca em listas nem com números enumerados, porque isto é "
        f"falado. Para qualquer pergunta sobre números, clientes, vendas, "
        f"custos ou prazos usa SEMPRE a ferramenta consultar_dados, e "
        f"responde só com o que ela devolver. Nunca inventes números."
    )


async def _esperar_o_start(receber: Callable[[], Any]) -> Optional[Dict[str, Any]]:
    """Lê do socket até chegar o `start`, ou desiste.

    Os pedaços de áudio que cheguem antes são **deitados fora**, e está
    certo: sem o `start` não se sabe de que projecto é a pergunta, e
    adivinhar foi exactamente o defeito do #713.
    """
    limite = _time.monotonic() + PRAZO_DO_START
    while _time.monotonic() < limite:
        try:
            msg = await asyncio.wait_for(receber(), timeout=PRAZO_DO_START)
        except asyncio.TimeoutError:
            return None
        if msg.get("type") == "websocket.disconnect":
            return None
        texto = msg.get("text")
        if not texto:
            continue  # áudio antes do `start`: ainda não sabemos para onde vai
        try:
            ctrl = _json.loads(texto)
        except Exception:
            continue
        if ctrl.get("type") == "control" and ctrl.get("action") == "start":
            return ctrl
    return None


async def servir(
    websocket: Any,
    *,
    user: Any,
    ctx: Any,
    responder: Callable[..., Any],
    persistir: Callable[..., Any],
    abrir_cliente: Callable[[], Any] = falada.abrir_cliente,
) -> None:
    """Serve uma sessão de voz pelo Sonic. O socket já está aceite.

    Tudo o que vem de fora vem por ARGUMENTO: o `responder` (o motor de
    SQL), o `persistir` (guardar a conversa) e o `abrir_cliente`. Duas
    razões, e as duas contam:

    * **o `ctx` não é lido de nenhuma variável de contexto** — sétima vez
      do mesmo defeito, e aqui o ciclo de escuta é uma tarefa de vida
      longa, que é o pior caso possível;
    * sem isto, verificar esta coreografia exigia um WebSocket, a AWS e
      uma base de dados ao mesmo tempo.
    """
    comecou = _time.monotonic()
    turnos: List[Any] = []
    sessao: Optional[falada.SessaoFalada] = None

    async def mandar(m: Dict[str, Any]) -> None:
        if ponte.e_audio(m):
            await websocket.send_bytes(m["pcm"])
        else:
            await websocket.send_text(_json.dumps(m))

    await mandar({"type": "state", "value": "connecting"})

    inicio = await _esperar_o_start(websocket.receive)
    if inicio is None:
        logger.warning(
            "voz/sonic: o cliente nao mandou `start` em %.0f s (cliente=%s)",
            PRAZO_DO_START,
            getattr(ctx, "slug", "?"),
        )
        await websocket.close(code=1002)
        return

    page_id = inicio.get("page_id")
    space_id = inicio.get("space_id")
    conversation_id = inicio.get("conversation_id")
    locale = (inicio.get("locale") or "en")[:2]
    voz = voz_do_locale(locale, inicio.get("voice"))

    try:
        cliente = await abrir_cliente()
        sessao = falada.SessaoFalada(
            ctx=ctx,
            ferramenta=ponte.ferramenta_do_cliente(
                responder,
                user=user,
                page_id=page_id,
                ctx=ctx,
                locale=locale,
                space_id=space_id,
            ),
            instrucao=instrucao_de_sistema(locale),
            voz=voz,
        )
        await sessao.abrir(cliente)
    except Exception:
        # Não arrancou. Dizer-lho é melhor do que deixá-lo com o
        # microfone aberto à espera de uma resposta que não vem — foi
        # esse o silêncio que já foi corrigido três vezes neste produto.
        logger.exception(
            "voz/sonic: nao consegui abrir a sessao (cliente=%s, projeto=%s)",
            getattr(ctx, "slug", "?"),
            space_id,
        )
        try:
            await mandar(
                {
                    "type": "error",
                    "code": "voice_unavailable",
                    "message": "A voz está temporariamente indisponível.",
                }
            )
        except Exception:
            pass
        await websocket.close(code=1011)
        return

    await mandar({"type": "state", "value": "user_speaking"})

    silenciado = False
    ultimo_audio = _time.monotonic()
    fim = asyncio.Event()

    async def reencaminhar() -> None:
        """Eventos da sessão → mensagens para a app."""
        async for ev in sessao.eventos():
            # Os turnos guardam-se aqui porque é aqui que passam os dois
            # lados da conversa.
            if isinstance(ev, falada.Ouvido) and ev.texto.strip():
                turnos.append(("user", ev.texto.strip()))
            elif isinstance(ev, falada.Dito) and ev.texto.strip():
                turnos.append(("sky", ev.texto.strip()))
            for m in ponte.para_o_protocolo(ev):
                try:
                    await mandar(m)
                except Exception:
                    # O socket fechou-se por baixo. Não vale um registo
                    # por pedaço de áudio.
                    fim.set()
                    return
        fim.set()

    async def manter_viva() -> None:
        """Alimenta silêncio quando ninguém fala.

        **É obrigatório, não uma optimização.** O modelo desliga depois de
        55 s sem áudio — medido — e «ninguém fala» inclui o caso em que a
        pessoa silenciou o microfone e foi beber um café.

        O silêncio não é facturado (também medido), por isso isto não
        custa nada.
        """
        while not fim.is_set():
            await asyncio.sleep(BATIDA_DO_SILENCIO / 2)
            if _time.monotonic() - ultimo_audio >= BATIDA_DO_SILENCIO:
                try:
                    await sessao.silencio(BATIDA_DO_SILENCIO)
                except Exception:
                    return

    escuta = asyncio.create_task(sessao.escutar())
    envio = asyncio.create_task(reencaminhar())
    batida = asyncio.create_task(manter_viva())

    try:
        while not fim.is_set():
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if not silenciado:
                    ultimo_audio = _time.monotonic()
                    await sessao.ouvir_microfone(msg["bytes"])
                continue
            texto = msg.get("text")
            if not texto:
                continue
            try:
                ctrl = _json.loads(texto)
            except Exception:
                continue
            if ctrl.get("type") != "control":
                continue
            accao = ctrl.get("action")
            if accao == "mute":
                # Silenciar é parar de MANDAR O MICROFONE, não parar de
                # alimentar: o `manter_viva` continua a mandar silêncio,
                # senão a sessão morre em 55 s.
                silenciado = True
            elif accao == "unmute":
                silenciado = False
            elif accao == "barge_in":
                # O cliente ainda o manda, e aqui não é preciso: a
                # interrupção é detectada pelo MODELO e volta como
                # evento. Reencaminhá-la seria dizer-lhe uma coisa que
                # ele já sabe.
                pass
            elif accao in ("end", "stop", "end_turn"):
                # `stop`/`end_turn` eram o fim de turno do
                # premir-para-falar, que já não existe como modo de
                # conversa. Aqui o turno fecha-se por si; só o `end`
                # fecha a sessão, e os outros não podem fechá-la por
                # engano — um cliente antigo manda-os.
                if accao == "end":
                    break
    except Exception:
        logger.exception(
            "voz/sonic: o ciclo do socket caiu (cliente=%s)",
            getattr(ctx, "slug", "?"),
        )
    finally:
        # ── A ORDEM aqui é o que impede perder o fim da conversa ────
        #
        # A primeira versão cancelava as três tarefas e só depois fechava
        # a sessão. Efeito, apanhado por um teste: quando a pessoa
        # desliga, os eventos que estavam em voo morrem com o
        # cancelamento — **a última coisa que a Sky disse nunca chega à
        # app, e o turno não é guardado.** O registo dizia `turnos=0`
        # numa conversa que teve dois.
        #
        # A ordem certa desenrola-se de dentro para fora:
        #
        #   1. a batida pára — já não é preciso manter nada vivo;
        #   2. a sessão fecha-se, o que termina o fluxo e faz o
        #      `escutar` pôr o seu fim na fila;
        #   3. espera-se que o `reencaminhar` esvazie a fila.
        #
        # Com prazo, porque um socket já morto não pode pendurar o fecho.
        batida.cancel()
        try:
            await sessao.fechar()
        except Exception:
            logger.debug("voz/sonic: falha a fechar", exc_info=True)
        try:
            await asyncio.wait({escuta, envio}, timeout=5)
        except Exception:
            logger.debug("voz/sonic: falha a esvaziar a fila", exc_info=True)
        for t in (escuta, envio):
            t.cancel()

        logger.info(
            "voz/sonic: sessao fechada (cliente=%s, projeto=%s, turnos=%d, "
            "tokens voz %d/%d texto %d/%d)",
            getattr(ctx, "slug", "?"),
            space_id,
            len(turnos),
            sessao.conta.voz_entrada,
            sessao.conta.voz_saida,
            sessao.conta.texto_entrada,
            sessao.conta.texto_saida,
        )

        mensagem = None
        if page_id and turnos:
            try:
                mensagem = await persistir(
                    user=user,
                    ctx=ctx,
                    page_id=page_id,
                    conversation_id=conversation_id,
                    turnos=turnos,
                    duracao_ms=int((_time.monotonic() - comecou) * 1000),
                )
            except Exception:
                # Perder a gravação é mau; derrubar o fecho por causa
                # disso é pior — a app ficaria sem o `final`.
                logger.exception(
                    "voz/sonic: nao consegui guardar a conversa (cliente=%s)",
                    getattr(ctx, "slug", "?"),
                )
        try:
            await mandar({"type": "final", "message_id": mensagem})
            await mandar({"type": "state", "value": "ended"})
        except Exception:
            pass
