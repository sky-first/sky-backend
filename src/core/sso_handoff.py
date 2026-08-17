"""Entrega da sessão a uma app nativa, no fim do SSO.

O problema que resolve
----------------------
A Google **recusa esquemas próprios** (``sky://auth``) em clientes OAuth do
tipo *Web application* — só os aceita em clientes de Android e iOS. A app
mandava `redirect_uri=sky://auth`, o backend passava-o tal e qual, e a
Google respondia:

    Erro 400: invalid_request
    doesn't comply with Google's OAuth 2.0 policy for keeping apps secure

O SSO no telemóvel nunca funcionou. Só apareceu agora porque era a primeira
vez que alguém entrava por SSO no telefone — o revisor do sandbox usa
password.

A forma
-------
O fornecedor passa a receber sempre um endereço ``https`` nosso. O endereço
da app viaja dentro do ``state``, que já é assinado e verificado. No fim,
o backend reencaminha para a app.

O que NÃO se faz: mandar os tokens no endereço de retorno. Num esquema
próprio, qualquer app instalada que declare ``sky://`` pode receber esse
intent. Em vez disso vai um **código de uso único**, com 60 segundos de
vida, que a app troca por tokens num pedido normal — e que deixa de
funcionar depois da primeira troca.

Uso único é imposto no Redis com ``SET NX``: quem consumir primeiro ganha.
Se o Redis estiver em baixo, a troca falha — recusar um login é preferível
a aceitar um código que já pode ter sido usado por outra pessoa.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Dict, Optional

import redis.asyncio as aioredis

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Curto de propósito: só tem de sobreviver ao salto do browser para a app.
HANDOFF_TTL_SECONDS = 60

_PREFIX = "sso:handoff:"

_redis: Optional[aioredis.Redis] = None


def _client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis


class HandoffError(Exception):
    """Código inexistente, já usado, expirado — ou Redis indisponível."""


async def issue(payload: Dict[str, Any]) -> str:
    """Guarda ``payload`` sob um código novo e devolve-o.

    O código é opaco e tem entropia suficiente para não ser adivinhado
    dentro dos 60 segundos em que existe.
    """
    code = secrets.token_urlsafe(32)
    try:
        await _client().set(
            _PREFIX + code,
            json.dumps(payload, separators=(",", ":")),
            ex=HANDOFF_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("sso_handoff_issue_failed", extra={"error": str(exc)})
        raise HandoffError("não foi possível emitir o código de entrega") from exc
    return code


async def consume(code: str) -> Dict[str, Any]:
    """Devolve o payload e invalida o código, atomicamente.

    ``GETDEL`` faz as duas coisas num só comando: sem ele, dois pedidos em
    paralelo com o mesmo código podiam ambos ler antes de qualquer um
    apagar, e o "uso único" passava a ser uma boa intenção.
    """
    if not code:
        raise HandoffError("código ausente")
    try:
        raw = await _client().getdel(_PREFIX + code)
    except Exception as exc:  # noqa: BLE001
        # Falha fechada de propósito: sem o Redis não há como saber se
        # este código já foi usado, e aceitar às cegas é o pior dos dois.
        logger.warning("sso_handoff_consume_failed", extra={"error": str(exc)})
        raise HandoffError("não foi possível validar o código de entrega") from exc

    if raw is None:
        # Mesma mensagem para inexistente, expirado e já usado: não se
        # confirma a terceiros qual dos três é.
        raise HandoffError("código de entrega inválido ou já utilizado")
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise HandoffError("conteúdo do código de entrega ilegível") from exc


def is_app_scheme(redirect_uri: Optional[str]) -> bool:
    """``sky://auth`` sim; ``https://…`` não; vazio não.

    É isto que decide se o fluxo é o da app ou o do browser. Um endereço
    ``http(s)`` continua a ir directo ao fornecedor, como sempre foi — o
    caminho da web não muda em nada.
    """
    if not redirect_uri:
        return False
    esquema, _, resto = redirect_uri.partition("://")
    if not resto:
        return False
    return esquema.lower() not in ("http", "https")
