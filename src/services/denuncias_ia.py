"""Reportar uma resposta da IA (15/10/2026).

A política *AI-Generated Content* da Google Play obriga uma app com chatbot a
deixar reportar, dentro da app, conteúdo gerado que seja ofensivo. A app
móvel tem «Reportar resposta» em cada resposta da Sky e em cada descoberta.

Duas regras, e são o ponto:

* **A mesma porta que a leitura.** Só se reporta o que se pode ver: uma
  mensagem passa por ``MessageService._load_viewable_conversation`` (a regra
  da lista de mensagens) e uma descoberta por
  ``InsightFeedService._scoped_row`` (a regra do feed). Inexistente e proibido
  dão o mesmo ``NotFoundError`` — um 403 confirmava que o alvo existe.
* **Só conteúdo da IA.** Uma mensagem de uma pessoa não é conteúdo gerado; o
  sítio para isso é outro (a moderação da equipa), e misturar os dois enchia
  esta tabela de ruído.

Guarda-se uma cópia do texto reportado (``conteudo``): a resposta pode ser
apagada depois, e uma denúncia sem o que foi denunciado não serve a ninguém.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.ai import MOTIVOS_DE_DENUNCIA, AIContentReport
from src.models.conversation import Message
from src.models.user import User

logger = logging.getLogger(__name__)

#: Tecto da cópia guardada. Uma resposta normal cabe folgada; isto só trava
#: uma resposta anómala de encher a tabela.
_MAX_CONTEUDO = 8000


class AlvoInvalido(ValueError):
    """O pedido não diz UM alvo, ou o alvo não é conteúdo da IA."""


async def reportar(
    db: AsyncSession,
    user: User,
    *,
    message_id: Optional[UUID],
    finding_id: Optional[UUID],
    motivo: str,
    texto: Optional[str],
) -> AIContentReport:
    if (message_id is None) == (finding_id is None):
        raise AlvoInvalido("Indique exactamente um alvo: message_id ou finding_id.")
    if motivo not in MOTIVOS_DE_DENUNCIA:
        raise AlvoInvalido("Motivo desconhecido.")

    query_id: Optional[UUID] = None
    if message_id is not None:
        conteudo, query_id = await _a_resposta(db, user, message_id)
    else:
        conteudo = await _a_descoberta(db, user, finding_id)

    linha = AIContentReport(
        user_id=user.id,
        message_id=message_id,
        finding_id=finding_id,
        query_id=query_id,
        motivo=motivo,
        texto=(texto or None),
        conteudo=(conteudo or "")[:_MAX_CONTEUDO] or None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(linha)
    await db.commit()
    await db.refresh(linha)
    # Sem o texto nem o conteúdo no log: podem levar dados do cliente.
    logger.warning(
        "AI content reported (report_id=%s, message_id=%s, finding_id=%s, motivo=%s, user_id=%s)",
        linha.id,
        message_id,
        finding_id,
        motivo,
        user.id,
    )
    return linha


async def _a_resposta(db: AsyncSession, user: User, message_id: UUID) -> tuple[str, Optional[UUID]]:
    from src.services.message_service import MessageService

    msg = await db.get(Message, message_id)
    if msg is None or msg.deleted_at is not None:
        raise NotFoundError("Message not found")
    # Levanta NotFoundError quando a pessoa não pode ver a conversa.
    await MessageService(db)._load_viewable_conversation(msg.conversation_id, user)
    if msg.role != "assistant":
        raise AlvoInvalido("Só se reportam respostas da IA.")
    return msg.content or "", msg.query_id


async def _a_descoberta(db: AsyncSession, user: User, finding_id: UUID) -> str:
    from src.services.insight_feed_service import InsightFeedService

    linha = await InsightFeedService(db)._scoped_row(user.id, str(finding_id))
    if linha is None:
        raise NotFoundError("Insight not found")
    achado = linha[0]
    return "\n\n".join(p for p in (achado.title, achado.description) if p)
