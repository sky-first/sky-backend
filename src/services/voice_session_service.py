"""Persist a finished voice session as a Conversation (BE-07 slice).

Server-side so it can write both the user (origin='voice') and the assistant
turns — a client cannot. The result shows up in History as a voice
conversation and reopens as a transcript.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.conversation import Conversation, Message
from src.models.user import User
from src.schemas.voice import VoiceSessionCreate
from src.services.page_service import PageService

logger = logging.getLogger(__name__)


def _title_from(turns) -> str:
    """O nome da conversa falada — a MESMA regra das escritas.

    Eram os primeiros 80 caracteres em bruto. Os outros dois caminhos que
    gravam respostas (o stream da app e o `/ai/query` + ask-ai da web) usam
    `_titulo_a_partir_de`: a primeira frase, cortada numa palavra. A mesma
    pergunta dava nomes diferentes na lista, conforme fosse dita ou escrita.
    """
    from src.services.message_service import _titulo_a_partir_de

    for t in turns:
        if t.role == "user":
            titulo = _titulo_a_partir_de(t.text)
            if titulo:
                return titulo
    return "Voice conversation"


# ── A fonte de cada resposta falada ────────────────────────────────────
#
# Uma resposta escrita guarda de onde veio (as tabelas, o SQL, as linhas) e
# mostra «ver a fonte». A falada não guardava nada: o `_voice_answer` lia só
# o texto do motor e deitava o `meta` e o `rows` fora. A mesma pergunta,
# dita, ficava sem botão.
#
# A consulta corre a meio da sessão (na cascata e na ferramenta do Sonic) e a
# conversa só se grava no fim. Este colector, um por sessão, junta as duas
# coisas: cada consulta regista a fonte e o ponto da conversa em que estava
# (quantos turnos havia); ao gravar, a fonte vai para a primeira resposta da
# Sky a partir desse ponto.
#
# Só o servidor escreve aqui. O `POST /voice/sessions` (o cliente a mandar
# turnos) NÃO aceita fontes: uma fonte forjada era SQL e linhas inventadas com
# o nosso selo.


@dataclass
class FonteFalada:
    turno: int
    pergunta: str
    meta: Dict[str, Any]
    linhas: Dict[str, Any]
    #: Onde a pergunta foi feita (ligação, projeto, modo pessoal) — o que
    #: permite voltar a correr o SQL ao abrir a fonte. As linhas NÃO se
    #: gravam (13/10/2026); `linhas` só vive em memória até ao fim da sessão.
    contexto: Dict[str, Any] = field(default_factory=dict)


def _zero() -> int:
    return 0


@dataclass
class _Colector:
    contar_turnos: Callable[[], int] = _zero
    fontes: List[FonteFalada] = field(default_factory=list)


_COLECTOR: contextvars.ContextVar[Optional[_Colector]] = contextvars.ContextVar(
    "fontes_da_sessao_de_voz", default=None
)


def abrir_fontes_da_sessao(contar_turnos: Optional[Callable[[], int]] = None) -> _Colector:
    """Começa a juntar as fontes desta sessão de voz (uma vez, à entrada).

    As tarefas criadas a seguir herdam o MESMO colector — o contexto copia a
    referência, e a lista é partilhada.
    """
    colector = _Colector()
    if contar_turnos is not None:
        colector.contar_turnos = contar_turnos
    _COLECTOR.set(colector)
    return colector


def contar_turnos_por(contar_turnos: Callable[[], int]) -> None:
    """Diz ao colector desta sessão onde estão os turnos (o Sonic tem os seus)."""
    colector = _COLECTOR.get()
    if colector is not None:
        colector.contar_turnos = contar_turnos


def registar_fonte(
    pergunta: str,
    meta: Dict[str, Any],
    linhas: Dict[str, Any],
    contexto: Optional[Dict[str, Any]] = None,
) -> None:
    """Uma consulta da voz terminou: guarda a fonte para a gravação final."""
    colector = _COLECTOR.get()
    if colector is None:
        return
    try:
        turno = int(colector.contar_turnos())
    except Exception:  # noqa: BLE001 — a fonte é um reforço, nunca cala o turno
        turno = 0
    colector.fontes.append(
        FonteFalada(
            turno=turno,
            pergunta=pergunta,
            meta=meta or {},
            # Só o que descreve as linhas — colunas, quantas, se cortou.
            linhas={
                "columns": (linhas or {}).get("columns") or [],
                "rows": [],
                "truncated": bool((linhas or {}).get("truncated")),
            },
            contexto=dict(contexto or {}),
        )
    )


def fontes_da_sessao() -> List[FonteFalada]:
    colector = _COLECTOR.get()
    return list(colector.fontes) if colector is not None else []


class VoiceSessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def persist(
        self,
        user: User,
        payload: VoiceSessionCreate,
        fontes: Optional[List[FonteFalada]] = None,
    ) -> Tuple[UUID, str, int]:
        # Gate on real page access — same rule the conversation endpoints use.
        #
        # A página também diz o PROJETO e a EQUIPA, e isso é preciso mais
        # abaixo — ver o comentário em `Conversation(...)`.
        pagina = await PageService(self.db).get_page(payload.page_id, user)

        now = datetime.now(timezone.utc)
        title = _title_from(payload.turns)

        # Append to an existing thread when the client asked voice inside an open
        # chat (and owns it); otherwise start a fresh conversation.
        conv = None
        if payload.conversation_id is not None:
            existing = await self.db.get(Conversation, payload.conversation_id)
            if existing is not None and existing.created_by == user.id:
                conv = existing
                conv.updated_at = now  # bump recency so it surfaces in "Today"
                # Como no ask-ai: uma conversa sem nome ganha o da primeira
                # pergunta, venha ela escrita ou falada.
                if not (conv.title or "").strip():
                    conv.title = title
        if conv is None:
            # ── O PROJETO e a EQUIPA, que faltavam ──────────────────
            #
            # A conversa nascia só com a página. Resultado medido em
            # produção a 09/10/2026: **todas** as conversas faladas do
            # Lucas tinham `space_id = NULL` e `crew_id = NULL`, com a
            # página certa ao lado:
            #
            #   qual que foi a faturacao  sp=None     pg=79a23caf
            #   quantos clientes (escrita) sp=9fcef9d6 pg=79a23caf
            #
            # A web lista as conversas POR PROJETO e a app lista-as por
            # página. Por isso o mesmo utilizador, no mesmo projeto, via
            # listas diferentes nos dois lados — e parecia que eram dois
            # sítios. Não eram: eram conversas órfãs.
            #
            # Vem da PÁGINA e não do cliente, de propósito: a página já
            # foi verificada contra as permissões dele na linha de cima,
            # e o projeto dela é um facto, não algo que o cliente possa
            # afirmar.
            conv = Conversation(
                page_id=payload.page_id,
                space_id=getattr(pagina, "space_id", None),
                crew_id=getattr(pagina, "crew_id", None),
                created_by=user.id,
                title=title,
                created_at=now,
                updated_at=now,
            )
            self.db.add(conv)
        await self.db.flush()  # get conv.id

        # Que resposta da Sky leva que fonte: a primeira a partir do ponto em
        # que a consulta correu. Uma resposta, uma fonte.
        fonte_do_turno: Dict[int, FonteFalada] = {}
        for fonte in fontes or []:
            for i in range(max(fonte.turno, 0), len(payload.turns)):
                if payload.turns[i].role != "user" and i not in fonte_do_turno:
                    fonte_do_turno[i] = fonte
                    break

        count = 0
        mensagens: List[Tuple[int, Message]] = []
        for i, turn in enumerate(payload.turns):
            is_user = turn.role == "user"
            msg = Message(
                conversation_id=conv.id,
                role="user" if is_user else "assistant",
                content=turn.text,
                origin="voice",
                # Session duration is attributed to the user's spoken turns.
                duration_ms=payload.duration_ms if is_user else None,
                user_id=user.id if is_user else None,
                # Stagger so the transcript reads oldest-first in turn order.
                created_at=now + timedelta(milliseconds=i * 10),
            )
            self.db.add(msg)
            mensagens.append((i, msg))
            count += 1

        if fonte_do_turno:
            from src.services.a_fonte_da_resposta import _guardar_a_fonte

            await self.db.flush()
            for i, msg in mensagens:
                fonte = fonte_do_turno.get(i)
                if fonte is None:
                    continue
                # Nunca rebenta a gravação: uma resposta sem fonte é pior do
                # que com fonte, mas melhor do que a conversa perdida.
                try:
                    async with self.db.begin_nested():
                        await _guardar_a_fonte(
                            self.db,
                            utilizador=user,
                            mensagem=msg,
                            pergunta=fonte.pergunta,
                            resposta=msg.content,
                            meta=fonte.meta,
                            linhas=fonte.linhas,
                            page_id=payload.page_id,
                            # As equipas da voz são TODAS as da pessoa no
                            # projeto (sem equipa fixa): o mesmo na reexecução.
                            contexto=fonte.contexto or {},
                        )
                except Exception as err:  # noqa: BLE001
                    msg.query_id = None  # a consulta voltou atrás com o savepoint
                    logger.warning("voz: fonte não guardada: %s", err)

        await self.db.commit()
        return conv.id, title, count
