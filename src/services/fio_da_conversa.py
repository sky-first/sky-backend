"""O fio da memória da IA — uma conversa, uma memória.

O `sky-ai` guarda o histórico (`chat_history`, na base do cliente) por
``thread_id``. Quando o pedido não traz nenhum, inventa um a partir de
**pessoa + ligação** (``{user}-{connection}-stream`` no streaming). Era o
que a ``/ai/chat/stream`` (a app) e a voz faziam: nunca mandavam fio. O
efeito é que todas as conversas da mesma pessoa sobre a mesma ligação
partilhavam a memória — o «e agora o Norte?» de uma conversa nova era
respondido com o contexto de outra, aberta dias antes.

A regra, igual nos três caminhos (``/ai/chat/stream``, ``/ai/query`` e voz):

* **conversa que a pessoa pode ver** → ``{cliente}:conv:{id}``. Estável
  entre turnos, a mesma na web, na app e na voz, e com o cliente à frente
  para que dois clientes nunca possam partilhar uma chave;
* **fio livre** (o id da sessão de chat da web, que não é uma conversa) →
  ``{cliente}:fio:{id}``. Continua partilhado por quem está na mesma sala,
  que é o desenho da web (``schemas/ai.py``, ``thread_id``);
* **conversa que a pessoa NÃO pode ver** → um fio só dela. Nunca a chave da
  conversa: isso era ler a memória de uma conversa alheia pelo id;
* **nada** → ``None``, e o ``sky-ai`` faz o que sempre fez.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def _cliente(tenant_slug: Optional[str]) -> str:
    if tenant_slug:
        return tenant_slug
    from src.core.tenant_context import current_tenant

    return current_tenant().slug


def fio_da_conversa(conversation_id: Any, tenant_slug: Optional[str] = None) -> str:
    """A chave de memória de uma conversa (já verificada como visível)."""
    return f"{_cliente(tenant_slug)}:conv:{conversation_id}"


def fio_livre(thread_id: Any, tenant_slug: Optional[str] = None) -> str:
    """A chave de um fio que não é uma conversa (sessão de chat da web, voz)."""
    return f"{_cliente(tenant_slug)}:fio:{thread_id}"


def _como_uuid(valor: Any) -> Optional[UUID]:
    if valor is None:
        return None
    if isinstance(valor, UUID):
        return valor
    try:
        return UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        return None


async def _conversa_visivel(db: Any, quem: Any, conversation_id: UUID) -> bool:
    from src.repositories.conversation import ConversationRepository
    from src.services.conversation_service import ConversationService

    conv = await ConversationRepository(db).get_by_id(conversation_id)
    if conv is None or quem is None:
        return False
    return bool(await ConversationService(db)._can_view(conv, quem))  # noqa: SLF001


async def resolver_fio(
    db: Any,
    quem: Any,
    *,
    conversation_id: Any = None,
    thread_id: Any = None,
    tenant_slug: Optional[str] = None,
) -> Optional[str]:
    """O ``thread_id`` a mandar ao ``sky-ai`` para esta pergunta.

    ``conversation_id`` ganha ao ``thread_id``. Um ``thread_id`` que seja o id
    de uma conversa visível conta como essa conversa — a web responde nos
    fios com o id da conversa no ``thread_id``, a app manda-o no
    ``conversation_id``, e os dois têm de dar à mesma memória.
    """
    if conversation_id is None and not thread_id:
        return None

    for candidato in (conversation_id, thread_id):
        cid = _como_uuid(candidato)
        if cid is None:
            continue
        try:
            if await _conversa_visivel(db, quem, cid):
                return fio_da_conversa(cid, tenant_slug)
        except Exception as exc:  # noqa: BLE001 — sem fio é pior, não mudo
            logger.warning("fio da conversa não resolvido (%s): %s", cid, exc)

    if thread_id:
        return fio_livre(thread_id, tenant_slug)
    # Conversa pedida mas não visível: um fio só desta pessoa.
    quem_id = getattr(quem, "id", None) or "anon"
    return fio_livre(f"{quem_id}:{conversation_id}", tenant_slug)


async def fio_da_voz(ctx: Any, quem: Any, conversation_id: Any, sessao_id: Any) -> str:
    """O fio de uma sessão de voz.

    Aberta dentro de uma conversa (o `start` traz ``conversation_id``), a voz
    continua a memória dessa conversa — a mesma chave que a escrita usa. Sem
    conversa, a sessão tem o seu próprio fio: os turnos dela lembram-se uns dos
    outros e de mais nada. Antes não ia fio nenhum e a voz partilhava a
    memória de todo o chat da pessoa naquela ligação.

    Nunca levanta: um fio que falha cai no da sessão, que isola na mesma.
    """
    slug = getattr(ctx, "slug", None) or _cliente(None)
    da_sessao = fio_livre(f"voz:{sessao_id}", slug)
    if not conversation_id:
        return da_sessao
    try:
        from src.config.tenant_connection_manager import tenant_connection_manager

        async with tenant_connection_manager.session_for(ctx) as db:
            return (
                await resolver_fio(db, quem, conversation_id=conversation_id, tenant_slug=slug)
                or da_sessao
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("voz: fio da conversa não resolvido: %s", exc)
        return da_sessao
