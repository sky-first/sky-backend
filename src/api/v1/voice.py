"""Voice session endpoints (BE-07 slice).

Today: persist a finished transcript (screen 13 → 08). Later this grows into
the full ``WS /voice/session`` duplex pipeline (§8) — the persistence logic
here becomes its on-close handler.
"""

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.voice import VoiceSessionCreate, VoiceSessionResponse, VoiceTurn
from src.services.speech_text import speech_text
from src.services.voice_session_service import VoiceSessionService


#: Quanto silêncio conta como «acabei de falar», em segundos.
#:
#: Uma vírgula ou uma respiração ficam bem abaixo disto; hesitar a meio de uma
#: frase também. Baixar este número traz de volta, em ponto pequeno, o defeito
#: que ele existe para resolver — corta quem fala devagar a meio da pergunta.
#:
#: Ao nível do módulo para os testes o poderem encurtar: um teste que espera
#: 1,6 s de verdade é um teste que alguém acaba por apagar.
SILENCIO_QUE_FECHA_O_TURNO = 1.6

logger = logging.getLogger(__name__)

#: As linguas que a voz sabe ouvir e falar, do codigo de duas letras que a
#: app manda para o nome que o fornecedor de transcricao espera.
#:
#: Estava escrito no meio da funcao, com `.get(locale, "English")` — e uma
#: lingua fora do mapa caia em ingles sem uma linha nos registos. No dia em
#: que a app ganhasse uma lingua e este sitio nao, a voz respondia em ingles
#: e parecia que «a lingua nao funciona».
#:
#: Tem de acompanhar o `LINGUAS` da app e o `SUPPORTED_LANGUAGES` do motor.
#: O `test_qa_voz_na_lingua_certa.py` compara-os.
_LINGUAS_DA_VOZ = {
    "en": "English",
    "pt": "Portuguese",
    "es": "Español",
}

router = APIRouter()

# The client authenticates the WS by offering this subprotocol followed by the
# access token as a second subprotocol (Sec-WebSocket-Protocol). A browser can
# set subprotocols but not headers, and — unlike ?token= — they never land in
# access logs (BE-07 T-07.3).
VOICE_SUBPROTOCOL = "sky.voice.v1"


async def _resolve_voice_tenant(claims: dict):
    """Resolve (and authorize) the tenant for a voice WS from its token claims.

    Mirrors the device-tenant gate wired into the REST path
    (``deps.enforce_device_tenant``, BE-01): a mobile token carries a signed
    ``tid`` and membership is re-checked live, so an off-boarded user is
    refused even with a still-valid token. Returns the caller's
    ``TenantContext``, or ``None`` when a device token is unresolved/forbidden
    (the handshake is then closed 4401). Web/console tokens (no ``tid``) and
    single-tenant mode both resolve to the default context.
    """
    from src.config.settings import settings
    from src.core.tenant_context import DEFAULT_TENANT_CONTEXT

    if not settings.MULTI_TENANT_ENABLED:
        return DEFAULT_TENANT_CONTEXT

    from src.core.device_tenant import TENANT_CLAIM

    if not claims.get(TENANT_CLAIM):
        return DEFAULT_TENANT_CONTEXT  # web/console token — no device tenant

    from src.api.middleware.tenant_resolver import _load_tenant_by_id
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.device_tenant import DeviceResolution, resolve_device_tenant
    from src.services.tenant_membership_service import TenantMembershipService

    async def _is_member(user_id: str, tid: str) -> bool:
        # Na base do **cliente**, que é onde as linhas de pertença de facto
        # vivem — e não na da plataforma, como aqui se dizia.
        #
        # O comentário estava errado e ninguém reparou porque a voz nunca
        # chegou tão longe: o caminho REST (`deps.enforce_device_tenant`) lê
        # com a sessão do pedido, que é a do cliente, e o login escreve com a
        # mesma. Só este sítio procurava noutro lado — e não encontrava nunca.
        #
        # O sintoma foi "Servidor de voz indisponível" no microfone e no live
        # talk, no mesmo dia em que o `/auth/me` passou a responder 200: as
        # duas verificações são a mesma, mas uma delas olhava para a gaveta
        # errada.
        ctx_do_cliente = await _load_tenant_by_id(tid)
        if ctx_do_cliente is None:
            return False
        async with tenant_connection_manager.session_for(ctx_do_cliente) as db:
            return await TenantMembershipService.is_member(db, user_id, tid)

    result = await resolve_device_tenant(
        claims, load_tenant_by_id=_load_tenant_by_id, is_member=_is_member
    )
    return result.context if result.resolution is DeviceResolution.RESOLVED else None


async def _voice_answer(
    user, page_id, text: str, ctx, locale: str = "en", space_id: str | None = None
) -> str:
    """The grounded answer for one voice turn — the same Bedrock engine as chat.

    Resolves the caller's connection and asks the AI engine, so a spoken
    question gets the same data-grounded answer the typed chat gives. Returns
    "" on any failure (the turn simply yields no TTS instead of erroring).
    Runs against ``ctx``'s tenant database, never the platform default.
    """
    import json as _json

    from src.ai.http_client import AIServiceHTTPClient
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.services.ai_service import AIService

    try:
        async with tenant_connection_manager.session_for(ctx) as db:
            servico = AIService(db)
            if space_id:
                # ── A voz responde DO PROJETO ONDE A PESSOA ESTÁ ────────────
                #
                # Antes: `_get_first_active_connection(user.id)` — a primeira
                # ligação activa da pessoa, fosse ela de que projeto fosse, e
                # `space_id="default"` para o motor. Perguntar pela voz dentro
                # de um projeto SEM DADOS respondia com os dados de outro. Foi
                # o que o Lucas apanhou: o projeto "Felipe e Lucas", com zero
                # ligações, a dizer "o total de clientes é 46".
                #
                # Isto contorna o modelo inteiro: os dados pertencem ao
                # projeto, o acesso vem da equipa, e o chat escrito respeita-o.
                # A voz era uma porta ao lado que dava para todas as salas.
                #
                # `_get_all_connections_for_space` é o que sabe quem alcança o
                # quê (dono, membro do projeto, ou membro de uma equipa lá
                # dentro). Só se escolhe DENTRO desse conjunto.
                permitidas = set(
                    await servico._get_all_connections_for_space(  # noqa: SLF001
                        user.id, space_id
                    )
                )
                if not permitidas:
                    # **Calar é a resposta certa.** O projeto não tem dados
                    # que esta pessoa alcance; cair na "primeira ligação" era
                    # precisamente o defeito.
                    logger.info(
                        "voice: space=%s sem ligações alcançáveis para user=%s — sem resposta",
                        space_id,
                        user.id,
                    )
                    return ""
                escolhida = await servico._get_first_active_connection_for_space(  # noqa: SLF001
                    user.id, space_id, text
                )
                # Aquele ajudante cai na primeira ligação do utilizador quando
                # não encontra nada no projeto — a mesma fuga por outro nome.
                # Só se aceita o que estiver no conjunto permitido.
                conn_id = escolhida if escolhida in permitidas else None
            else:
                # Sem projeto: é o modo pessoal, onde a primeira ligação da
                # própria pessoa é o âmbito certo.
                conn_id = await servico._get_first_active_connection(user.id)  # noqa: SLF001
        if not conn_id:
            return ""
        # Use the same streaming path as /ai/chat/stream — the non-streaming
        # /query rejects space_id="default" (UserContext UUID validation).
        answer = ""
        async for line in AIServiceHTTPClient().stream_query_connection(
            connection_id=conn_id,
            question=text,
            user_id=str(user.id),
            # O projeto vai a sério quando existe. `"default"` só fica para o
            # modo pessoal, onde não há projeto nenhum — era o valor fixo que
            # dizia ao motor "responde do que quiseres".
            space_id=space_id or "default",
            locale=locale,
        ):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = _json.loads(line[5:].strip())
            except Exception:
                continue
            if ev.get("type") == "chunk":
                answer += ev.get("content", "")
            elif ev.get("type") == "answer":
                answer = ev.get("text", answer)
        return answer.strip()
    except Exception:
        return ""


@router.post(
    "/sessions",
    response_model=VoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Persist a finished voice session as a conversation",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def create_voice_session(
    payload: VoiceSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VoiceSessionResponse:
    try:
        conv_id, title, count = await VoiceSessionService(db).persist(current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=404, detail=str(err))  # avoid page existence leak
    return VoiceSessionResponse(conversation_id=conv_id, title=title, message_count=count)


@router.get(
    "/voices",
    summary="As vozes disponiveis, por lingua",
)
async def listar_vozes(current_user: User = Depends(get_current_user)) -> dict:
    """O catalogo, para o ecra de definicoes se desenhar a partir do servidor.

    A app tem uma copia da lista para nao esperar pela rede a desenhar o ecra.
    Se as duas divergirem, ganha esta — e o `voz_polly` so devolve vozes que
    existem, portanto uma preferencia velha nunca fica sem som.
    """
    from src.services.vozes import catalogo_como_json

    return {"voices": catalogo_como_json()}


@router.get(
    "/preview",
    summary="Ouvir uma voz antes de a escolher",
)
async def ouvir_voz(
    voice: str,
    language: str = "English",
    current_user: User = Depends(get_current_user),
):
    """Uma frase curta, dita pela voz escolhida.

    **Porque isto faltava.** Escolher entre duas vozes a olhar para dois
    circulos coloridos e escolher as cegas: o que distingue duas vozes e o
    som. Na web havia pre-escuta pelo sintetizador do browser — que nao e a
    voz que responde, portanto mentia. No telemovel nao havia nada, e o
    comentario no codigo dizia porque: «ate haver um endpoint de amostra».

    E este. Sintetiza a MESMA voz que vai responder, que e a unica pre-escuta
    que vale alguma coisa.

    Devolve MP3 e nao PCM: e para tocar num leitor de audio normal, nao para
    entrar no fluxo do WebSocket.
    """
    import asyncio as _aio
    import os as _os

    from fastapi.responses import Response

    from src.services.vozes import AMOSTRA, voz_polly

    texto = AMOSTRA.get(language) or AMOSTRA["English"]
    voice_id = voz_polly(language, voice)

    def _sintetizar() -> bytes:
        import boto3

        polly = boto3.client(
            "polly", region_name=_os.getenv("AWS_REGION", "eu-west-1")
        )
        r = polly.synthesize_speech(
            Text=texto,
            OutputFormat="mp3",
            VoiceId=voice_id,
            Engine="neural",
        )
        return r["AudioStream"].read()

    try:
        audio = await _aio.to_thread(_sintetizar)
    except Exception as exc:  # noqa: BLE001
        # Sem Polly (local, ou permissoes em falta) nao ha amostra. 503 e nao
        # 500: nao esta partido, esta indisponivel — e a app sabe distinguir
        # «nao deu para ouvir» de «esta avariado».
        raise HTTPException(
            status_code=503, detail=f"Voice preview unavailable: {exc}"
        )

    return Response(
        content=audio,
        media_type="audio/mpeg",
        # A amostra nao muda. Deixar o telemovel guarda-la evita pagar Polly
        # de cada vez que alguem toca no mesmo circulo duas vezes.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.websocket("/session")
async def voice_session_ws(websocket: WebSocket) -> None:
    """Duplex voice pipeline (BE-07 / §8).

    Audio flows both ways, so this is a WebSocket, not SSE. The socket
    authenticates via ``Sec-WebSocket-Protocol`` — NEVER ``?token=`` (a token in
    the URL lands in access logs). Wire format: JSON text frames for
    control/state/transcript/final/error, raw binary frames for audio (mic up,
    TTS down). On close the transcript is persisted as a voice Conversation,
    reusing the REST slice's service.

    Phase A drives a StubVoiceProvider so the protocol + state machine are
    verifiable offline; Phase B swaps in Amazon Transcribe + Polly + the live
    engine behind the same VoiceProvider seam.
    """
    import asyncio as _asyncio
    import json as _json
    import time as _time

    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.security import verify_token
    from src.core.tenant_context import (
        DEFAULT_TENANT_CONTEXT,
        reset_current_tenant,
        set_current_tenant,
    )
    from src.repositories.user import UserRepository
    from src.services.voice_pipeline import build_voice_provider

    # ── Auth (T-07.1/.2/.3) ───────────────────────────────────────────────
    # A token in the query string is rejected outright — it would be logged.
    if websocket.query_params.get("token"):
        await websocket.close(code=4401)
        return
    protos = [
        p.strip()
        for p in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if p.strip()
    ]
    token = protos[1] if len(protos) >= 2 and protos[0] == VOICE_SUBPROTOCOL else None
    user = None
    ctx = DEFAULT_TENANT_CONTEXT
    if token:
        try:
            payload = verify_token(token, token_type="access")
            uid = payload.get("sub")
            # Route to the caller's tenant DB, not the platform default: a
            # mobile token carries the tenant in a signed ``tid`` claim and
            # membership is re-checked live, so an off-boarded user is refused
            # even with a valid token (BE-01). ``None`` → reject the handshake.
            ctx = await _resolve_voice_tenant(payload)
            if uid and ctx is not None:
                async with tenant_connection_manager.session_for(ctx) as db:
                    user = await UserRepository(db).get_by_id(uid)
        except Exception:
            user = None
            ctx = None
    if user is None or ctx is None:
        await websocket.close(code=4401)  # handshake rejected, no session
        return

    tenant_reset = set_current_tenant(ctx)  # downstream services route to ctx
    await websocket.accept(subprotocol=VOICE_SUBPROTOCOL)

    async def send(obj: dict) -> None:
        await websocket.send_text(_json.dumps(obj))

    async def state(value: str) -> None:
        await send({"type": "state", "value": value})

    provider = build_voice_provider()
    try:
        await provider.start("en-US")
    except Exception:
        # STT couldn't start (e.g. expired AWS creds) — tell the client instead
        # of leaving it stuck in "listening" forever, then close.
        try:
            await send({"type": "error", "code": "voice_unavailable",
                        "message": "Voice is temporarily unavailable."})
        except Exception:
            pass
        await websocket.close(code=1011)
        return
    started = _time.monotonic()
    turns: list[VoiceTurn] = []
    page_id = None
    #: O projeto onde a pessoa está a falar. Vem no `start`.
    #: Sem ele, a resposta saía da primeira ligação do utilizador —
    #: ver `_voice_answer`. `None` é o modo pessoal, que é legítimo.
    space_id: str | None = None
    conversation_id = None  # set from `start` → thread voice into an open chat
    # The app language ('en'|'pt'|'es') drives STT language, the answer language,
    # and the Polly voice, so a PT app gets a PT-spoken answer. Set from `start`.
    locale = "en"
    voice_lang = "English"
    #: A voz escolhida nas definicoes. Vem no `start`; ate agora NAO VINHA —
    #: o servidor escolhia so pela lingua e o ecra de definicoes era
    #: decoracao. Ver `src/services/vozes.py`.
    voz_escolhida: Optional[str] = None
    muted = False
    persisted = False
    turn_active = False
    barge = _asyncio.Event()
    ptt = False       # push-to-talk: the user's release ends the turn, not VAD
    last_partial = ""  # latest transcript, committed on a push-to-talk release

    # ── Uma frase nao acaba na primeira pausa ────────────────────────────────
    #
    # O Lucas fez uma pergunta longa em voz alta e a Sky recebeu «reven».
    #
    # O Transcribe emite SEGMENTOS, e fecha um segmento a cada pausa de fala —
    # uma virgula chega. Cada um desses fechos vinha marcado `final`, e o
    # codigo tratava o primeiro `final` como o fim do turno: mandava a primeira
    # fatia para a Sky e, a partir dai, `turn_active` mandava deitar fora tudo
    # o que ele continuasse a dizer.
    #
    # `final` do Transcribe quer dizer «fechei esta frase», nao «esta pessoa
    # acabou de falar». Sao coisas diferentes e o codigo lia uma pela outra.
    #
    # Passa a juntar os segmentos e a esperar por silencio de verdade. Quem
    # decide o fim do turno e a AUSENCIA de fala nova, nao a presenca de um
    # fecho de frase.
    segmentos: list[str] = []
    fim_do_turno: Optional[_asyncio.Task] = None

    def texto_falado() -> str:
        """Tudo o que a pessoa disse neste turno, segmentos fechados incluidos.

        E tambem o que se mostra no ecra: antes mostrava-se so o segmento
        actual, portanto o que ja tinha sido dito desaparecia a cada pausa e
        parecia que o microfone nao estava a apanhar nada.
        """
        return " ".join([*segmentos, last_partial]).strip()

    def cancelar_fim_do_turno() -> None:
        nonlocal fim_do_turno
        if fim_do_turno is not None and not fim_do_turno.done():
            fim_do_turno.cancel()
        fim_do_turno = None

    async def finalize(send_final: bool) -> None:
        nonlocal persisted
        if persisted:
            return
        persisted = True
        message_id = None
        if page_id and turns:
            try:
                async with tenant_connection_manager.session_for(ctx) as db:
                    u = await UserRepository(db).get_by_id(str(user.id))
                    dur = int((_time.monotonic() - started) * 1000)
                    conv_id, _title, _n = await VoiceSessionService(db).persist(
                        u,
                        VoiceSessionCreate(
                            page_id=page_id,
                            turns=turns,
                            duration_ms=dur,
                            conversation_id=conversation_id,
                        ),
                    )
                    message_id = str(conv_id)
            except Exception:
                message_id = None
        if send_final:
            try:
                await send({"type": "final", "message_id": message_id})
            except Exception:
                pass

    async def do_turn(user_text: str) -> None:
        """A finalized user utterance → thinking → grounded answer → speaking+TTS."""
        nonlocal turn_active
        user_text = user_text.strip()
        if not user_text or turn_active:
            return
        turn_active = True
        barge.clear()
        try:
            turns.append(VoiceTurn(role="user", text=user_text))
            await state("thinking")
            # `space_id` **por nome**. Passado como sexto argumento posicional
            # rebentava com `TypeError` em qualquer duplo de teste escrito
            # antes de este parâmetro existir — e o efeito não era um erro
            # visível, era a sessão a ficar muda: o telemóvel com o microfone
            # aberto e nada a acontecer, para sempre. Ver o `except` abaixo.
            answer = (
                await _voice_answer(user, page_id, user_text, ctx, locale, space_id=space_id)
            ).strip()
            if answer and not barge.is_set():
                turns.append(VoiceTurn(role="sky", text=answer))
                await send({"type": "sky_text", "text": answer})  # show it on screen
                await state("speaking")
                samples = 0
                # A VOZ ESCOLHIDA, e nao so a lingua.
                #
                # Isto era um mapa lingua -> voz, cravado: um portugues ouvia
                # sempre a Camila, escolhesse o que escolhesse. O Lucas foi as
                # definicoes, escolheu, e nao ouviu diferenca — nao ouvia
                # porque nao havia.
                from src.services.vozes import voz_polly

                tts_voice = voz_polly(voice_lang, voz_escolhida)
                # Sem marcação.
                #
                # A resposta vem em markdown e ia crua para a síntese: ouvia-se
                # a Sky a ler os asteriscos e os hífenes das listas. Num
                # telemóvel é ESTE o caminho — o cliente não sintetiza nada —
                # por isso a correcção feita na app não chegava aqui.
                #
                # O texto do ecrã continua a ir em markdown (acima): quem lê
                # quer a formatação, quem ouve não.
                async for audio in provider.synthesize(speech_text(answer), tts_voice):
                    if barge.is_set():
                        break
                    await websocket.send_bytes(audio)
                    samples += len(audio) // 2  # int16 PCM @ 16 kHz
                # Hold "speaking" for the audio's real playback length. The
                # client plays it over that time, so flipping to listening when
                # the bytes finish SENDING (near-instant) would cut it off.
                secs = samples / 16000.0
                if secs > 0 and not barge.is_set():
                    try:
                        await _asyncio.wait_for(barge.wait(), timeout=secs + 0.2)
                    except _asyncio.TimeoutError:
                        pass
            # Fresh STT stream for the next turn — the current one sat idle
            # while Sky spoke and can wedge, which silently kills turn 2+.
            try:
                await provider.restart_stt()
            except Exception:
                pass
            await state("user_speaking")
        except Exception:
            # **Uma falha no turno não pode deixar a sessão muda.**
            #
            # Não havia `except` nenhum aqui. Qualquer erro a meio — o motor
            # em baixo, uma resposta vazia, um `TypeError` numa assinatura que
            # mudou — subia e a sessão ficava calada: do lado de lá é o
            # telemóvel com o microfone aberto e nada a acontecer, sem erro,
            # sem fim, até a pessoa desistir. Apanhado a 26/08 porque o
            # `test_be07_voice_ws` encravava para sempre em vez de falhar.
            #
            # Diz-se que correu mal e volta-se a ouvir. Voltar a ouvir é o que
            # importa: sem isso a sessão está viva mas inútil.
            logger.exception("voice: o turno falhou; a devolver a palavra ao utilizador")
            try:
                await send(
                    {
                        "type": "error",
                        # A frase escolhe-se na app, na língua de quem lê.
                        "code": "turn_failed",
                    }
                )
                await provider.restart_stt()
            except Exception:
                pass
            try:
                await state("user_speaking")
            except Exception:
                pass
        finally:
            turn_active = False

    async def consume_transcripts() -> None:
        """STT events from the provider → partial_transcript / end-of-turn.

        The provider owns endpointing (Transcribe for real, energy VAD in the
        stub), so a final result is the end of the user's turn."""
        nonlocal last_partial
        try:
            async for ev in provider.transcripts():
                if turn_active:
                    continue  # ignore stray STT while Sky is answering
                if muted:
                    # Silenciado. O `muted` ja impede alimentar o microfone,
                    # mas o que ficou na fila do STT continuava a passar por
                    # aqui — e podia abrir um turno depois de a pessoa ter
                    # carregado no botao. Silenciar tem de calar o que ja
                    # estava a caminho, senao o botao esconde o microfone em
                    # vez de o desligar.
                    cancelar_fim_do_turno()
                    segmentos.clear()
                    last_partial = ""
                    continue
                text = ev.get("text", "")
                # Hands-free ends the turn on Transcribe's own endpointing; in
                # push-to-talk the release ("stop") ends it, so a final is just
                # another partial to be committed on release.
                if ev.get("final") and not ptt:
                    # Fim de FRASE, nao fim de turno. Guarda-se e espera-se:
                    # se ele continuar a falar, o proximo segmento cancela a
                    # espera; se ficar calado, o turno fecha com tudo junto.
                    if text.strip():
                        segmentos.append(text.strip())
                    last_partial = ""
                    cancelar_fim_do_turno()

                    async def fechar_por_silencio() -> None:
                        try:
                            await _asyncio.sleep(SILENCIO_QUE_FECHA_O_TURNO)
                        except _asyncio.CancelledError:
                            return
                        tudo = " ".join(segmentos).strip()
                        segmentos.clear()
                        if tudo:
                            await do_turn(tudo)

                    fim_do_turno = _asyncio.create_task(fechar_por_silencio())
                elif text:
                    last_partial = text
                    # Voltou a falar: o turno ainda nao acabou.
                    cancelar_fim_do_turno()
                    # ``final`` marks where the STT closed a segment. Voice
                    # ignores it (it only renders the latest text), but
                    # dictation needs it: the next segment starts from
                    # scratch, so without knowing where one ends the client
                    # can't tell a rewrite of the current sentence from the
                    # start of the next one — and drops everything said
                    # before the first pause.
                    await send(
                        {
                            "type": "partial_transcript",
                            # O turno INTEIRO, e nao so o segmento actual. Ver
                            # `texto_falado`: mostrar so o segmento fazia
                            # desaparecer do ecra o que ja tinha sido dito.
                            "text": texto_falado(),
                            "final": bool(ev.get("final")),
                        }
                    )
        except Exception:
            pass

    stt_task = _asyncio.create_task(consume_transcripts())

    await state("connecting")
    await state("user_speaking")
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:  # a mic audio frame
                if not (muted or turn_active):  # never feed the mic during Sky's turn
                    await provider.feed_audio(msg["bytes"])
                continue
            raw = msg.get("text")
            if not raw:
                continue
            try:
                ctrl = _json.loads(raw)
            except Exception:
                continue
            if ctrl.get("type") != "control":
                continue
            action = ctrl.get("action")
            if action == "start":
                page_id = ctrl.get("page_id") or page_id
                space_id = ctrl.get("space_id") or space_id
                conversation_id = ctrl.get("conversation_id") or conversation_id
                ptt = ctrl.get("mode") == "push-to-talk"
                # Sem locale no `start` fica-se com o valor inicial, que é
                # inglês. É legítimo — clientes antigos não o mandavam — mas
                # deixa de ser calado: uma sessão inteira na língua errada
                # merece uma linha nos registos.
                if not ctrl.get("locale"):
                    logger.warning(
                        "voz: o cliente nao mandou locale no `start`; a sessao "
                        "vai ouvir e responder em %s",
                        _LINGUAS_DA_VOZ.get(locale, locale),
                    )
                locale = (ctrl.get("locale") or locale)[:2]
                # ── Uma lingua que nao conhecemos nao vira ingles calado. ──
                #
                # Isto era `.get(locale, "English")`: um locale fora do mapa
                # caia em ingles sem uma linha nos registos. No dia em que a
                # app ganhasse uma lingua e este sitio nao, a voz respondia em
                # ingles e parecia que «a lingua nao funciona».
                voice_lang = _LINGUAS_DA_VOZ.get(locale, "")
                if not voice_lang:
                    logger.warning(
                        "voz: locale %r desconhecido — conheco %s. A sessao vai "
                        "ouvir e responder em ingles.",
                        locale,
                        sorted(_LINGUAS_DA_VOZ),
                    )
                    voice_lang = "English"
                voz_escolhida = ctrl.get("voice") or voz_escolhida
                # ── A mudanca de lingua nao pode falhar em silencio. ───────
                #
                # A transcricao arranca em ingles no `accept` e e reaberta
                # aqui na lingua da app. Isto era `except Exception: pass`:
                # se a reabertura falhasse, o erro desaparecia e a sessao
                # continuava a ouvir em ingles.
                #
                # Foi o que o Lucas apanhou: *«estando a voz e a app em
                # portugues, ainda so me escutou em ingles»*. Nem ele sabia
                # porque — so sentia que nao o entendia — nem ficava nada
                # nos registos para alguem investigar.
                #
                # Continua a nao derrubar a sessao: ouvir em ingles e mau,
                # cair a meio da frase e pior. Mas passa a deixar rasto, e a
                # dizer a quem esta do outro lado o que aconteceu.
                if voice_lang != "English":
                    try:
                        await provider.start(voice_lang)
                    except Exception:
                        logger.exception(
                            "voz: nao consegui reabrir a transcricao em %s; a "
                            "sessao fica a ouvir em ingles",
                            voice_lang,
                        )
                        # Avisar quem esta a falar. Um aviso, nao um erro: a
                        # sessao continua util, so nao na lingua pedida.
                        try:
                            await send(
                                {
                                    "type": "warning",
                                    "code": "voice_language_fallback",
                                    "lang": locale,
                                    "message": "Voice is listening in English.",
                                }
                            )
                        except Exception:
                            pass
                await state("user_speaking")
            elif action == "mute":
                muted = True
                # Silenciar a meio de uma frase nao pode deixar meia frase a
                # caminho da Sky: o Lucas silenciou e a pergunta partida foi
                # na mesma. Silenciar e dizer «esquece o que eu estava a
                # dizer», e e isso que passa a fazer.
                cancelar_fim_do_turno()
                segmentos.clear()
                last_partial = ""
            elif action == "unmute":
                muted = False
            elif action == "barge_in":
                await state("user_speaking")
            elif action in ("stop", "end_turn"):
                # Push-to-talk release: commit what was transcribed as the turn.
                # (Hands-free rarely sends this; flush is a no-op for AWS.)
                #
                # O TURNO INTEIRO, e nao so o ultimo segmento. Largar o botao
                # depois de uma frase com pausas mandava so a fatia depois da
                # ultima pausa — a mesma perda que o modo maos-livres tinha,
                # pela mesma razao.
                cancelar_fim_do_turno()
                tudo = texto_falado()
                if not turn_active and tudo:
                    segmentos.clear()
                    last_partial = ""
                    await do_turn(tudo)
                else:
                    await provider.flush()
            elif action == "end":
                await state("ended")
                await finalize(send_final=True)
                break
    except WebSocketDisconnect:
        pass
    finally:
        stt_task.cancel()
        await provider.close()
        await finalize(send_final=False)  # best-effort persist on an abrupt close
        reset_current_tenant(tenant_reset)  # clear the tenant contextvar
    try:
        await websocket.close()
    except Exception:
        pass
