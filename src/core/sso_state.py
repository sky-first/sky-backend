"""Estado assinado para o fluxo OAuth/SSO.

Porque existe
-------------

O parâmetro ``state`` do OAuth servia duas funções que não estavam a ser
cumpridas: era gerado aleatoriamente, enviado ao fornecedor e **nunca
verificado no retorno** (a rota recebia-o na assinatura e ignorava-o).

Consequências, ambas reais antes deste módulo:

1. Sem proteção CSRF no fluxo de autorização.
2. Sem forma de ligar o retorno ao cliente onde o pedido começou — o
   retorno corria contra a base do cliente em que a ligação calhasse
   cair, e não contra aquele que iniciou o login.

Aqui o ``state`` passa a ser um token assinado com HMAC-SHA256 que
carrega o cliente, um nonce e o instante de emissão. No retorno
verifica-se assinatura, validade e **igualdade do cliente**.

Nota sobre o segredo: usa ``JWT_SECRET_KEY``. Uma rotação desse segredo
invalida os ``state`` em voo, mas com um TTL de 5 minutos isso é, na
prática, um punhado de logins a repetir.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from src.config.settings import settings

# Curto de propósito: um state só tem de sobreviver ao tempo que o
# utilizador leva a autenticar-se no fornecedor.
STATE_TTL_SECONDS = 300


class SSOStateError(Exception):
    """State ausente, adulterado, expirado, ou de outro cliente."""


def _secret() -> bytes:
    return str(settings.JWT_SECRET_KEY).encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    # O padding foi retirado na emissão; repor antes de descodificar.
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload_b64: str) -> str:
    return hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()


def issue_state(tenant_slug: Optional[str]) -> str:
    """Emite um state assinado para o cliente indicado.

    ``tenant_slug`` a None representa a própria plataforma — continua a
    ser assinado, para que um state de cliente não sirva na plataforma
    nem o contrário.
    """
    payload = {
        "t": tenant_slug or "",
        "n": secrets.token_urlsafe(16),
        "i": int(time.time()),
    }
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_state(state: Optional[str], expected_tenant: Optional[str]) -> None:
    """Valida o state do retorno. Levanta ``SSOStateError`` se algo não bate.

    A ordem das verificações é deliberada: assinatura primeiro, para não
    dar pistas sobre o conteúdo de um state forjado.
    """
    if not state:
        raise SSOStateError("state ausente")

    try:
        payload_b64, signature = state.split(".", 1)
    except ValueError as exc:
        raise SSOStateError("state malformado") from exc

    # compare_digest para não vazar informação pelo tempo de comparação.
    if not hmac.compare_digest(_sign(payload_b64), signature):
        raise SSOStateError("assinatura do state inválida")

    try:
        payload = json.loads(_b64d(payload_b64))
    except Exception as exc:
        raise SSOStateError("conteúdo do state ilegível") from exc

    issued_at = payload.get("i")
    if not isinstance(issued_at, int):
        raise SSOStateError("state sem instante de emissão")
    age = int(time.time()) - issued_at
    # A margem negativa cobre relógios ligeiramente à frente entre pods.
    if age > STATE_TTL_SECONDS or age < -30:
        raise SSOStateError("state expirado")

    if (payload.get("t") or "") != (expected_tenant or ""):
        # A mensagem não revela qual era o cliente do state.
        raise SSOStateError("state pertence a outro cliente")
