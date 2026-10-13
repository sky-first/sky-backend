"""Onde vive a password do papel ``wt_<slug>`` na base ``sky_world``.

**Nunca na base do cliente.** A config da ligação «Dados públicos» guarda só
uma referência (``credential_ref``); quem precisa de se ligar (o conector
``sky-world`` do backend, e o sky-ai) resolve-a aqui, com cache de 5 min.

Dois modos (``WORLD_CREDENTIAL_BACKEND``):

- ``aws``   — Secrets Manager, segredo ``<WORLD_TENANT_SECRET_PREFIX><slug>``
  com ``{"username", "password"}``. É o de produção. O pod precisa de
  ``GetSecretValue``/``CreateSecret``/``PutSecretValue``/``DeleteSecret``
  nesse prefixo (IRSA; ver o runbook do PR de infra).
- ``local`` — password derivada do ``ENCRYPTION_KEY`` por HMAC. Não guarda
  nada; serve para desenvolvimento e testes, e recusa-se a correr em
  produção.

A referência só é aceite se for **exactamente** a do cliente em contexto
(S15): uma ligação re-apontada para o segredo de outro cliente rebenta
antes de chegar ao Secrets Manager.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Dict, Optional, Tuple

from src.config.settings import settings
from src.services.fontes_sistema.catalogo import FonteInvalidaError, papel_do_cliente

logger = logging.getLogger(__name__)

_TTL_S = 300.0
_cache: Dict[str, Tuple[float, Tuple[str, str]]] = {}


class CredencialRecusadaError(PermissionError):
    """A referência não é a do cliente em contexto, ou o modo não é válido."""


def ref_do_cliente(slug: str) -> str:
    papel_do_cliente(slug)  # valida o slug
    return f"{settings.WORLD_TENANT_SECRET_PREFIX}{slug}"


def validar_ref(ref: Optional[str], slug: Optional[str]) -> str:
    """A referência tem de ser a do cliente em contexto. Devolve-a.

    Sem cliente em contexto (plataforma) não há referência válida nenhuma:
    a ligação gerida só existe nas bases dos clientes.
    """
    if not slug:
        raise CredencialRecusadaError("sem cliente em contexto para resolver a credencial")
    try:
        esperado = ref_do_cliente(slug)
    except FonteInvalidaError as exc:
        raise CredencialRecusadaError(str(exc)) from exc
    if not ref or not hmac.compare_digest(str(ref), esperado):
        raise CredencialRecusadaError("credential_ref não pertence a este cliente")
    return esperado


def _modo() -> str:
    modo = (settings.WORLD_CREDENTIAL_BACKEND or "aws").strip().lower()
    if modo not in ("aws", "local"):
        raise CredencialRecusadaError(f"WORLD_CREDENTIAL_BACKEND desconhecido: {modo!r}")
    if modo == "local" and getattr(settings, "is_production", False):
        raise CredencialRecusadaError("WORLD_CREDENTIAL_BACKEND=local não é permitido em produção")
    return modo


def _slug_da_ref(ref: str) -> str:
    return ref[len(settings.WORLD_TENANT_SECRET_PREFIX) :]


def _derivada(slug: str) -> str:
    chave = (settings.ENCRYPTION_KEY or settings.JWT_SECRET_KEY or "").encode()
    mac = hmac.new(chave, f"sky_world:{slug}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def nova_password(slug: str) -> str:
    """Uma password nova para ``wt_<slug>``: aleatória (aws) ou derivada (local)."""
    if _modo() == "local":
        return _derivada(slug)
    return secrets.token_urlsafe(32)


def _cliente_sm():
    import boto3  # type: ignore[import-untyped]

    return boto3.client("secretsmanager", region_name=settings.AWS_REGION)


def ler(ref: str, *, sem_cache: bool = False) -> Tuple[str, str]:
    """``(utilizador, password)`` da referência. Cache de 5 min."""
    agora = time.monotonic()
    if not sem_cache:
        guardado = _cache.get(ref)
        if guardado and agora - guardado[0] < _TTL_S:
            return guardado[1]
    slug = _slug_da_ref(ref)
    if _modo() == "local":
        valor = (papel_do_cliente(slug), _derivada(slug))
    else:
        resposta = _cliente_sm().get_secret_value(SecretId=ref)
        blob = json.loads(resposta["SecretString"])
        valor = (blob["username"], blob["password"])
    _cache[ref] = (agora, valor)
    return valor


def guardar(ref: str, utilizador: str, password: str) -> None:
    """Grava (ou substitui) o segredo. No modo local não há nada a gravar."""
    _cache.pop(ref, None)
    if _modo() == "local":
        return
    corpo = json.dumps({"username": utilizador, "password": password})
    sm = _cliente_sm()
    try:
        sm.put_secret_value(SecretId=ref, SecretString=corpo)
    except sm.exceptions.ResourceNotFoundException:
        sm.create_secret(
            Name=ref,
            SecretString=corpo,
            Description="Papel só-leitura de um cliente na base sky_world (fontes do sistema)",
            Tags=[{"Key": "sky:componente", "Value": "fontes-do-sistema"}],
        )


def apagar(ref: str) -> None:
    """Apaga o segredo (destruição do cliente, S20). Idempotente."""
    _cache.pop(ref, None)
    if _modo() == "local":
        return
    sm = _cliente_sm()
    try:
        sm.delete_secret(SecretId=ref, ForceDeleteWithoutRecovery=True)
    except sm.exceptions.ResourceNotFoundException:
        return


def esquecer_cache() -> None:
    _cache.clear()
