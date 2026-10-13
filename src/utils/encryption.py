"""Encryption utilities for sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) from the
`cryptography` library. The encryption key should come from an environment
variable (ENCRYPTION_KEY) that is provisioned via Azure Key Vault in
production, or generated locally for development.

In production (Phase 4 of RBAC plan), this should be replaced with
Azure Key Vault CMK (Customer Managed Keys) for per-tenant key isolation.
For the MVP, a single Fernet key per deploy is sufficient.
"""

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from src.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


# The encryption key. In production this comes from the secret store via
# ExternalSecret. For local dev, generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#
# Lido a cada chamada (e não só no import) para que um pod/teste que defina a
# variável depois do import não fique preso ao valor antigo.
def _chave() -> Optional[str]:
    return os.environ.get("ENCRYPTION_KEY") or None


#: Ambientes onde ainda se aceita gravar credenciais em claro quando falta a
#: chave — e só com aviso. Fora desta lista (staging, production, qualquer
#: valor desconhecido) recusa-se: falhar fechado.
_AMBIENTES_SEM_CHAVE_PERMITIDA = frozenset({"development", "dev", "local", "test", "testing"})


class EncryptionKeyMissingError(ServiceUnavailableError):
    """Recusa gravar credenciais sem cifra fora de dev/test (503).

    Antes, sem ``ENCRYPTION_KEY``, o ``encrypt_dict`` devolvia o dicionário
    tal como veio e as passwords iam para a base EM CLARO, sem erro nenhum.
    """

    def __init__(
        self,
        message: str = (
            "ENCRYPTION_KEY não está configurada: recuso gravar credenciais de "
            "ligação sem cifra neste ambiente."
        ),
    ):
        super().__init__(message)


def _ambiente() -> str:
    try:
        from src.config.settings import settings

        return (settings.ENVIRONMENT or "").strip().lower()
    except Exception:  # noqa: BLE001
        return (os.environ.get("ENVIRONMENT") or "").strip().lower()


def texto_claro_permitido() -> bool:
    """True só em dev/test: único caso em que falta de chave não é fatal."""
    return _ambiente() in _AMBIENTES_SEM_CHAVE_PERMITIDA


def _get_fernet() -> Optional[Fernet]:
    """Get a Fernet instance, or None if no key is configured."""
    chave = _chave()
    if not chave:
        return None
    try:
        return Fernet(chave.encode())
    except Exception:
        # Key might not be valid base64 — derive a valid Fernet key from it via SHA256
        derived = base64.urlsafe_b64encode(hashlib.sha256(chave.encode()).digest())
        return Fernet(derived)


def encrypt_dict(data: Dict[str, Any], key: str = "") -> Dict[str, Any]:
    """
    Encrypt a dictionary's values.

    The dict is JSON-serialized and encrypted as a single blob stored under
    {"__encrypted": "<base64>"}. Already-encrypted input is returned as-is
    (idempotent — never double-encrypts).

    **Falha fechado.** Sem ``ENCRYPTION_KEY``:
      * em development/test devolve o dict em claro, com aviso alto;
      * em qualquer outro ambiente levanta ``EncryptionKeyMissingError``.
    Um erro ao cifrar levanta sempre — nunca se grava em claro por engano.

    Args:
        data: Dictionary to encrypt (e.g. connection config with passwords)
        key: Unused — kept for backward compatibility. Uses ENCRYPTION_KEY env.
    """
    if is_encrypted(data):
        return data

    f = _get_fernet()
    if not f:
        if texto_claro_permitido():
            logger.warning(
                "encryption.PLAINTEXT: ENCRYPTION_KEY em falta — a gravar "
                "credenciais EM CLARO (só permitido em ENVIRONMENT=%s). "
                "Nunca usar isto fora de desenvolvimento/testes.",
                _ambiente() or "?",
            )
            return data
        logger.error(
            "encryption.refused: ENCRYPTION_KEY em falta em ENVIRONMENT=%s — "
            "credenciais NÃO gravadas",
            _ambiente() or "?",
        )
        raise EncryptionKeyMissingError()

    try:
        plaintext = json.dumps(data).encode("utf-8")
        ciphertext = f.encrypt(plaintext)
    except Exception as exc:
        # Só o tipo: a mensagem pode trazer pedaços do payload.
        logger.error("encryption.failed: %s", type(exc).__name__)
        raise
    return {"__encrypted": ciphertext.decode("utf-8")}


def decrypt_dict(data: Dict[str, Any], key: str = "") -> Dict[str, Any]:
    """
    Decrypt a dictionary previously encrypted by encrypt_dict.

    If the dict has "__encrypted" key, decrypts it. Otherwise returns as-is
    (handles legacy plaintext data gracefully).

    Args:
        data: Dictionary to decrypt
        key: Unused — kept for backward compatibility.

    Returns:
        Decrypted dictionary, or original if not encrypted / no key.
    """
    if "__encrypted" not in data:
        # Legacy plaintext data — return as-is
        return data

    f = _get_fernet()
    if not f:
        logger.warning(
            "encryption.decrypt_failed: data is encrypted but no ENCRYPTION_KEY configured"
        )
        return data

    try:
        ciphertext = data["__encrypted"].encode("utf-8")
        plaintext = f.decrypt(ciphertext)
        return json.loads(plaintext)
    except InvalidToken:
        logger.error("encryption.decrypt_failed: invalid token (wrong key?)")
        return data
    except Exception as exc:
        logger.error("encryption.decrypt_failed: %s", exc)
        return data


def is_encrypted(data: Any) -> bool:
    """Check if a dict is encrypted (has __encrypted key)."""
    return isinstance(data, dict) and "__encrypted" in data
