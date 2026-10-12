"""O portão dos WebSockets em tempo real — uma regra, três salas.

O ``/ws/chat/{page}`` ganhou-o no #751. O ``/presence/{crew}`` e o
``/cursor/{contexto}`` só verificavam o token: qualquer pessoa com um token
válido, de qualquer cliente, via quem estava online numa equipa e seguia os
cursores de qualquer sala cujo id conhecesse.

O WebSocket não passa pelo middleware HTTP de tenant, por isso aqui faz-se o
que o REST faz por nós:

1. token de acesso válido, e não revogado pelo logout → senão ``4001``;
2. cliente resolvido pelo ``tid`` assinado, com a pertença verificada ao vivo
   (o mesmo portão da voz) → senão ``1008``;
3. a pessoa existe na base DESSE cliente → senão ``4001``;
4. a regra de acesso da sala (``verificar``) → senão ``1008``.

``1008`` é «policy violation»: o token é bom, a sala é que não é desta
pessoa (ou não existe). O cliente NÃO deve voltar a ligar num 1008.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from src.core.security import verify_token

logger = logging.getLogger(__name__)

WS_CLOSE_UNAUTHENTICATED = 4001
WS_CLOSE_POLICY = 1008


def _open_session(ctx):
    """Sessão na base do cliente ``ctx``. Costura para os testes."""
    from src.config.tenant_connection_manager import tenant_connection_manager

    return tenant_connection_manager.session_for(ctx)


@dataclass
class Admitido:
    """Quem entrou: o utilizador (da base do cliente) e o cliente."""

    user: Any
    ctx: Any

    @property
    def user_id(self) -> str:
        return str(self.user.id)


#: ``verificar(db, user) -> bool`` — a regra de acesso da sala.
Verificar = Callable[[Any, Any], Awaitable[bool]]


async def autorizar_ws(
    token: str,
    verificar: Verificar,
    *,
    abrir_sessao: Optional[Callable[[Any], Any]] = None,
    rotulo: str = "ws",
) -> tuple[Optional[Admitido], Optional[int]]:
    """``(Admitido, None)`` quando pode entrar; ``(None, close_code)`` quando não.

    Falha fechada: qualquer excepção a verificar o acesso dá ``1008``.
    """
    from src.api.v1.voice import _resolve_voice_tenant
    from src.core.exceptions import ForbiddenError, NotFoundError
    from src.core.tenant_context import reset_current_tenant, set_current_tenant
    from src.core.token_blocklist import is_token_revoked
    from src.repositories.user import UserRepository

    abrir = abrir_sessao or _open_session

    try:
        payload = verify_token(token, token_type="access")
    except Exception:
        return None, WS_CLOSE_UNAUTHENTICATED
    user_id = payload.get("sub") if isinstance(payload, dict) else None
    if not user_id:
        return None, WS_CLOSE_UNAUTHENTICATED
    try:
        user_uuid = UUID(str(user_id))
    except (ValueError, TypeError):
        return None, WS_CLOSE_UNAUTHENTICATED
    iat = payload.get("iat")
    if iat is not None and await is_token_revoked(str(user_id), int(iat)):
        return None, WS_CLOSE_UNAUTHENTICATED

    try:
        ctx = await _resolve_voice_tenant(payload)
    except Exception:
        ctx = None
    if ctx is None:
        # Token de aparelho cujo cliente já não existe ou a pessoa já não
        # pertence — o REST dá 403 no mesmo caso.
        return None, WS_CLOSE_POLICY

    reset = set_current_tenant(ctx)
    try:
        async with abrir(ctx) as db:
            user = await UserRepository(db).get_by_id(user_uuid)
            if user is None or getattr(user, "deleted_at", None) is not None:
                return None, WS_CLOSE_UNAUTHENTICATED
            try:
                if not await verificar(db, user):
                    return None, WS_CLOSE_POLICY
            except (NotFoundError, ForbiddenError):
                return None, WS_CLOSE_POLICY
    except Exception as exc:  # noqa: BLE001 — falha fechada
        logger.warning("%s: access check failed: %s", rotulo, exc)
        return None, WS_CLOSE_POLICY
    finally:
        reset_current_tenant(reset)

    return Admitido(user=user, ctx=ctx), None


def _como_uuid(valor: Any) -> Optional[UUID]:
    try:
        return UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        return None


async def pode_ver_pagina(db: Any, user: Any, page_id: Any) -> bool:
    """A regra do REST (``PageService.get_page``): dono, membro da página,
    da equipa (página de equipa) ou do projeto (página de projeto)."""
    from src.services.page_service import PageService

    pid = _como_uuid(page_id)
    if pid is None:
        return False
    await PageService(db).get_page(pid, user)  # NotFound/Forbidden → recusa
    return True


async def e_membro_da_equipa(db: Any, user: Any, crew_id: Any) -> bool:
    """Membro da equipa — a mesma linha que dá acesso a uma página de equipa."""
    from src.repositories.crew import CrewMemberRepository

    cid = _como_uuid(crew_id)
    if cid is None:
        return False
    return await CrewMemberRepository(db).get_by_crew_and_user(cid, user.id) is not None


async def e_membro_do_projeto(db: Any, user: Any, space_id: Any) -> bool:
    """Membro do projeto — a mesma linha que dá acesso a uma página de projeto."""
    from src.repositories.space import SpaceMemberRepository

    sid = _como_uuid(space_id)
    if sid is None:
        return False
    return await SpaceMemberRepository(db).get_by_space_and_user(sid, user.id) is not None
