"""Persist a finished voice session as a Conversation (BE-07 slice).

Server-side so it can write both the user (origin='voice') and the assistant
turns — a client cannot. The result shows up in History as a voice
conversation and reopens as a transcript.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.conversation import Conversation, Message
from src.models.user import User
from src.schemas.voice import VoiceSessionCreate
from src.services.page_service import PageService


def _title_from(turns) -> str:
    for t in turns:
        if t.role == "user":
            return t.text.strip()[:80]
    return "Voice conversation"


class VoiceSessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def persist(self, user: User, payload: VoiceSessionCreate) -> Tuple[UUID, str, int]:
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

        count = 0
        for i, turn in enumerate(payload.turns):
            is_user = turn.role == "user"
            self.db.add(
                Message(
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
            )
            count += 1

        await self.db.commit()
        return conv.id, title, count
