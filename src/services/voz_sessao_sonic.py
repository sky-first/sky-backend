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
from src.services import voz_legenda_ao_vivo as legenda_viva
from src.services import voz_ponte_sonic as ponte
from src.services import voz_recado as recado
from src.services.numeros_falados import em_algarismos
from src.services.pontuacao import pontuar_pergunta

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
    """A voz do modelo: a ESCOLHIDA nas definições, se o Sonic a tiver.

    O catálogo do ecrã é o do Sonic desde 10/10 (`vozes.py`). Escolhas
    antigas (vozes do Polly: «lucia», «sergio») passam à voz do Sonic do
    mesmo género; um id desconhecido cai na voz da língua — nunca num id que
    o Sonic recuse, porque isso faz a abertura falhar.
    """
    from src.services.vozes import voz_sonic

    lingua = {"pt": "Portuguese", "es": "Español", "en": "English"}.get(
        (locale or "")[:2], "English"
    )
    if escolhida and escolhida in VOZES.values():
        return escolhida
    return voz_sonic(lingua, escolhida)


#: O fuso de cada língua, quando a app não manda o seu.
FUSO_DA_LINGUA = {"pt": "Europe/Lisbon", "es": "Europe/Madrid"}

_DIAS = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]


def agora_em(locale: str, fuso: Optional[str] = None) -> str:
    """«sábado, 10/10/2026, 15:20 (Europe/Madrid)» — o que a Sky sabe do relógio.

    > «pergunto que dia é hoje. E ele não tem essa informação… isso é muito
    >  prejudicial» — Lucas, 10/10
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    nome = fuso or FUSO_DA_LINGUA.get((locale or "")[:2], "UTC")
    try:
        zona = ZoneInfo(nome)
    except Exception:  # noqa: BLE001 — um fuso inválido da app não parte a voz
        nome, zona = "UTC", ZoneInfo("UTC")
    t = datetime.now(zona)
    return f"{_DIAS[t.weekday()]}, {t:%d/%m/%Y}, {t:%H:%M} ({nome})"


def instrucao_de_sistema(locale: str, fuso: Optional[str] = None) -> str:
    """O que a Sky é, na língua de quem fala.

    Curto de propósito. O glossário e as métricas **não** entram aqui:
    entram pelo motor de SQL, que é quem sabe o que fazer com eles — e
    repeti-los no prompt de voz era pagar tokens de entrada em cada turno
    por contexto que já viaja no sítio certo.

    Três regras novas a 10/10, todas pedidas pelo Lucas a testar:
      * a data e a hora — «no tengo acceso a la fecha actual»;
      * números em algarismos — a legenda dizia «veintisiete mil»;
      * o resultado da ferramenta dito tal e qual — o sky-ai respondia
        «não há dados de clientes; o mais próximo são os pedidos» e o
        Sonic resumia-o em «não encontrei, reformula».
    """
    lingua = {
        "pt": "português de Portugal",
        "es": "español",
        "en": "English",
    }.get((locale or "")[:2], "English")
    return (
        f"És a Sky, a analista de dados da empresa. Responde SEMPRE em "
        f"{lingua}, em uma ou duas frases curtas, como numa conversa — "
        f"nunca em listas. Agora é {agora_em(locale, fuso)}; usa isto para "
        f"«hoje», «ontem», «este mês» e para dizer a data ou a hora. "
        f"Escreve SEMPRE os números com algarismos (27.000, 4,5 %, 1.250 €), "
        f"nunca por extenso. Para qualquer pergunta sobre números, clientes, "
        f"vendas, custos, pessoas ou prazos usa SEMPRE a ferramenta "
        f"consultar_dados. Quando ela devolver um resultado, diz o campo "
        f"«resultado» TAL E QUAL, palavra por palavra, traduzido só se vier "
        f"noutra língua: não o resumas, não o troques por «não encontrei», não "
        f"acrescentes conselhos. Nunca inventes números."
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

    # O modelo fala a 24 kHz; o protocolo leva 16 kHz, que é o que todas
    # as apps instaladas tocam. Sem isto a fala sai 1,5x mais lenta e
    # mais grave — ver `ParaORitmoDaApp`, na ponte. Um por sessão: ele
    # guarda a emenda entre pedaços.
    ritmo = ponte.ParaORitmoDaApp(falada.SAIDA_HZ)

    async def mandar(m: Dict[str, Any]) -> None:
        if ponte.e_audio(m):
            await websocket.send_bytes(ritmo.alimentar(m["pcm"]))
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

    # ── O ditado NÃO é uma conversa ─────────────────────────────────
    #
    # > «El dictado se detuvo» — Lucas, 09/10/2026, com o ditado a
    # > rebentar logo a seguir a ligar isto.
    #
    # O ditado usa o MESMO WebSocket e só consome `partial_transcript`:
    # quer o texto do que a pessoa disse, para o pôr na caixa de
    # escrita. Nunca pediu uma resposta a ninguém.
    #
    # Sem esta distinção, ditar passava a: chamar o nosso SQL (custo e
    # demora por nada), gerar uma resposta falada, e **o telemóvel
    # dizia-a em voz alta por cima de quem está a ditar**.
    #
    # Hoje o único cliente que manda `push-to-talk` é o ditado — o
    # premir-para-falar saiu como modo de conversa (sky-mobile#75). Um
    # cliente antigo em premir-para-falar também cai aqui, e também
    # fica melhor servido: transcrição é o que ele espera do gesto.
    e_ditado = inicio.get("mode") == "push-to-talk"

    async def nao_consultar(_pergunta: str) -> str:
        """A ditar, o nosso SQL não corre.

        Tem de devolver ALGUMA coisa — um `toolResult` que não chega
        deixa o modelo à espera até aos 55 s e mata a sessão. Devolve
        uma instrução para ele não dizer nada de útil, e o que ele disser
        não sai daqui de qualquer maneira.
        """
        logger.info(
            "voz/sonic: ditado — consulta ignorada (cliente=%s)",
            getattr(ctx, "slug", "?"),
        )
        return "Modo de ditado: não respondas, limita-te a ouvir."

    consulta = ponte.ferramenta_do_cliente(
        responder,
        user=user,
        page_id=page_id,
        ctx=ctx,
        locale=locale,
        space_id=space_id,
    )

    async def consulta_com_recado(pergunta: str) -> str:
        """A consulta, com a Sky a dizer o que vai procurar enquanto procura.

        Ver `voz_recado`. O recado corre EM PARALELO com a consulta — não
        lhe acrescenta tempo nenhum — e o resultado só segue para o modelo
        depois de o recado ter saído: o WebSocket garante a ordem, e assim
        a resposta nunca fala por cima do «vou ver».
        """
        if not recado.ligado():
            return await consulta(pergunta)
        texto = recado.recado_de_espera(pergunta, locale)

        async def _dizer() -> None:
            try:
                await mandar({"type": "sky_text", "text": texto})
            except Exception:  # noqa: BLE001
                return
            await recado.dizer(websocket.send_bytes, texto, voz)

        tarefa = asyncio.create_task(_dizer())
        try:
            return await consulta(pergunta)
        finally:
            try:
                await asyncio.wait_for(asyncio.shield(tarefa), timeout=5)
            except Exception:  # noqa: BLE001
                pass

    try:
        cliente = await abrir_cliente()
        sessao = falada.SessaoFalada(
            ctx=ctx,
            ferramenta=(nao_consultar if e_ditado else consulta_com_recado),
            instrucao=instrucao_de_sistema(locale, inicio.get("timezone")),
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
    # A pessoa interrompeu (tocou na bola) e a resposta em curso já não
    # interessa: o resto do som e da legenda dela vai para o lixo até ela
    # acabar ou até a pessoa voltar a falar. Ver o `barge_in` em baixo.
    a_descartar = False

    async def reencaminhar() -> None:
        """Eventos da sessão → mensagens para a app."""
        nonlocal a_descartar
        async for ev in sessao.eventos():
            if a_descartar:
                if isinstance(ev, (falada.Ouvido, falada.FalaAcabou, falada.VezDaPessoa)):
                    # A resposta interrompida acabou, ou a pessoa já está a
                    # falar outra vez: a partir daqui tudo conta.
                    a_descartar = False
                    if isinstance(ev, falada.VezDaPessoa):
                        continue  # a app já tem a vez desde o `barge_in`
                elif isinstance(ev, (falada.Audio, falada.Dito)):
                    continue
            # O que se lê — no ecrã de voz e no fio — arrumado aqui, uma vez:
            # a pergunta com «¿…?», e os números ditos em algarismos (o texto
            # do Sonic é o que ele DIZ, e vem sempre por extenso).
            if not e_ditado:
                if isinstance(ev, falada.Ouvido):
                    ev = falada.Ouvido(texto=pontuar_pergunta(ev.texto, locale))
                elif isinstance(ev, falada.Dito):
                    ev = falada.Dito(texto=em_algarismos(ev.texto, locale))
            # Os turnos guardam-se aqui porque é aqui que passam os dois
            # lados da conversa.
            if isinstance(ev, falada.Ouvido) and ev.texto.strip():
                turnos.append(("user", ev.texto.strip()))
            elif isinstance(ev, falada.Dito) and ev.texto.strip():
                turnos.append(("sky", ev.texto.strip()))
            # A ditar, só o que a PESSOA disse atravessa. A resposta da
            # Sky — texto e som — fica aqui: ninguém a pediu, e o
            # telemóvel diria-a em voz alta por cima de quem dita.
            if e_ditado and not isinstance(ev, (falada.Ouvido, falada.Falhou)):
                continue
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
    # ── A legenda que aparece ENQUANTO se fala ──────────────────────
    #
    # O Sonic so manda a transcricao no FIM da frase (medido), e por
    # isso o ecra ficava com tres pontinhos a girar durante toda a
    # fala. O mesmo PCM vai tambem para o Transcribe, que devolve
    # parciais em ~300 ms.
    #
    # A do Sonic continua a ser a que conta: chega a seguir, com
    # `final: true`, e substitui a legenda no ecra. Ver
    # `voz_legenda_ao_vivo`.
    legenda = None
    if legenda_viva.esta_ligada() and not e_ditado:
        # No ditado nao: la a transcricao do Sonic JA e a resposta, e
        # pagar um segundo servico para escrever o mesmo duas vezes
        # nao tem onde se agarrar.
        legenda = legenda_viva.LegendaAoVivo(locale)
        await legenda.abrir()

    async def reencaminhar_a_legenda() -> None:
        """Os parciais do Transcribe, no formato que a app ja entende.

        `final: false` de proposito: quem fecha a frase e o Sonic.
        """
        if legenda is None:
            return
        try:
            async for texto in legenda.parciais():
                await mandar({"type": "partial_transcript", "text": texto, "final": False})
        except Exception:  # noqa: BLE001
            # A legenda nunca pode levar a conversa atras dela.
            logger.debug("voz/sonic: legenda parou", exc_info=True)

    envio = asyncio.create_task(reencaminhar())
    batida = asyncio.create_task(manter_viva())
    legendagem = asyncio.create_task(reencaminhar_a_legenda())

    try:
        while not fim.is_set():
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if not silenciado:
                    ultimo_audio = _time.monotonic()
                    await sessao.ouvir_microfone(msg["bytes"])
                    # So o que vem do MICROFONE. A batida de silencio
                    # que mantem a sessao do Sonic viva nao passa por
                    # aqui: paga-la era pagar a sessao inteira em vez
                    # da fala.
                    if legenda is not None:
                        await legenda.ouvir(msg["bytes"])
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
                # Tocar na bola enquanto a Sky fala: pára JÁ e ouve.
                #
                # Durante a resposta o telemóvel desliga o microfone (para
                # não se ouvir a si própria), por isso o modelo nunca chega
                # a detectar a interrupção sozinho. Sem isto o resto da
                # resposta antiga continuava a chegar e a tocar por cima da
                # pergunta nova — o contrário do que o Gemini e o ChatGPT
                # fazem.
                a_descartar = True
                try:
                    await mandar({"type": "discard_audio"})
                    await mandar({"type": "state", "value": "user_speaking"})
                except Exception:  # noqa: BLE001
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
        legendagem.cancel()
        if legenda is not None:
            await legenda.fechar()
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
