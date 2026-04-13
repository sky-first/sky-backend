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

logger = logging.getLogger(__name__)

# The encryption key. In production this comes from Azure Key Vault via
# ExternalSecret. For local dev, generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_ENCRYPTION_KEY: Optional[str] = os.environ.get("ENCRYPTION_KEY")


def _get_fernet() -> Optional[Fernet]:
    """Get a Fernet instance, or None if no key is configured."""
    if not _ENCRYPTION_KEY:
        return None
    try:
        return Fernet(_ENCRYPTION_KEY.encode() if isinstance(_ENCRYPTION_KEY, str) else _ENCRYPTION_KEY)
    except Exception:
        # Key might not be valid base64 — derive a valid Fernet key from it via SHA256
        derived = base64.urlsafe_b64encode(
            hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
        )
        return Fernet(derived)


def encrypt_dict(data: Dict[str, Any], key: str = "") -> Dict[str, Any]:
    """
    Encrypt a dictionary's values.

    If ENCRYPTION_KEY is set, the dict is JSON-serialized and encrypted as a
    single blob stored under {"__encrypted": "<base64>"}. If not set, returns
    the original dict unchanged (backward compatible with existing plaintext
    data).

    Args:
        data: Dictionary to encrypt (e.g. connection config with passwords)
        key: Unused — kept for backward compatibility. Uses ENCRYPTION_KEY env.

    Returns:
        Dict with encrypted payload, or original dict if no key configured.
    """
    f = _get_fernet()
    if not f:
        logger.debug("encryption.skip: no ENCRYPTION_KEY configured")
        return data

    try:
        plaintext = json.dumps(data).encode("utf-8")
        ciphertext = f.encrypt(plaintext)
        return {"__encrypted": ciphertext.decode("utf-8")}
    except Exception as exc:
        logger.error("encryption.failed: %s", exc)
        return data


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
        logger.warning("encryption.decrypt_failed: data is encrypted but no ENCRYPTION_KEY configured")
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


def is_encrypted(data: Dict[str, Any]) -> bool:
    """Check if a dict is encrypted (has __encrypted key)."""
    return "__encrypted" in data
