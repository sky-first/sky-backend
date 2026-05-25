"""Short-lived HMAC-signed tokens for backend → AI-service agent runs.

Why not JWT:
  JWT's flexibility (alg negotiation, optional claim semantics, large
  ecosystem of slightly different libraries) is a liability for an
  internal service-to-service token where both sides are under our
  control. A plain HMAC-SHA256 envelope over a compact JSON payload is
  smaller, easier to audit (this file is ~90 non-blank lines), and has
  no alg-confusion attack surface.

Wire format:
    <base64url(payload_json)>.<base64url(hmac_sha256(payload_json))>

Both halves use base64url WITHOUT padding (RFC 4648 §5) so the token is
safe to carry in URLs and headers without further escaping.

Typical use:

    from src.core.agent_token import (
        AgentTokenClaims, sign_agent_token, verify_agent_token,
    )

    claims = AgentTokenClaims(
        identity_type="service_principal",
        identity_id=str(sp.id),
        space_id=str(space.id),
        crew_id=None,
        agent_id=str(agent.id),
        attributed_to_user_id=str(agent.created_by),
        exp=0,  # filled in by ttl_seconds
    )
    token = sign_agent_token(claims, key=primary_key, ttl_seconds=300)

    # On the AI service:
    verified = verify_agent_token(token, keys=[primary_key, previous_key])
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

# Required claim names. Must be present in every decoded payload.
_REQUIRED_CLAIMS = frozenset({"identity_type", "identity_id", "exp"})

# Identity values we accept. Everything else must be rejected at construction
# time so a malicious caller cannot sneak a third type past the signer.
_VALID_IDENTITY_TYPES = frozenset({"user", "service_principal"})


# ─── Exceptions ───────────────────────────────────────────────────────────

class AgentTokenError(Exception):
    """Base class for all agent-token verification failures."""


class AgentTokenInvalid(AgentTokenError):
    """Token is malformed (wrong number of parts, non-base64, empty)."""


class AgentTokenTampered(AgentTokenError):
    """Signature does not match any trusted key."""


class AgentTokenExpired(AgentTokenError):
    """Token's `exp` is in the past (or exactly now)."""


class AgentTokenMissingClaim(AgentTokenError):
    """A required claim is absent from the payload."""


# ─── Claims ───────────────────────────────────────────────────────────────

@dataclass
class AgentTokenClaims:
    """Payload carried inside a signed agent token.

    Construction validates the identity_type and identity_id up front so
    a misconfigured caller can never emit a token that the verifier would
    otherwise have to reject. `exp` is validated loosely here (just type);
    expiry decisions happen at verify time.
    """

    identity_type: str           # 'user' | 'service_principal'
    identity_id: str             # UUID string
    space_id: Optional[str]
    crew_id: Optional[str]
    agent_id: Optional[str]
    exp: int                     # unix epoch seconds
    attributed_to_user_id: Optional[str] = field(default=None)

    def __post_init__(self):
        if self.identity_type not in _VALID_IDENTITY_TYPES:
            raise ValueError(
                f"identity_type must be one of {sorted(_VALID_IDENTITY_TYPES)}, "
                f"got {self.identity_type!r}"
            )
        if not self.identity_id or not isinstance(self.identity_id, str):
            raise ValueError("identity_id must be a non-empty string")
        if not isinstance(self.exp, int):
            raise ValueError("exp must be an int (unix epoch seconds)")


# ─── Encoding helpers ─────────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    # Reject anything outside the base64url alphabet up front. Python's
    # base64.urlsafe_b64decode is lenient by default (silently drops invalid
    # chars), which would let a malformed token squeak through as empty bytes.
    if not data or not all(
        c.isalnum() or c in "-_" for c in data
    ):
        raise ValueError(f"non-base64url characters in {data!r}")
    # Add back the padding stripped on encode
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _canonical_payload(claims: AgentTokenClaims) -> bytes:
    """Serialise claims deterministically so signatures are stable."""
    # sort_keys + compact separators = one and only one representation.
    return json.dumps(asdict(claims), sort_keys=True, separators=(",", ":")).encode("utf-8")


# ─── Sign ─────────────────────────────────────────────────────────────────

def sign_agent_token(
    claims: AgentTokenClaims,
    *,
    key: bytes,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Serialise and HMAC-SHA256 sign a claims object.

    If `ttl_seconds` is given, `claims.exp` is overwritten with
    `now + ttl_seconds` (so callers don't have to compute it themselves).
    Otherwise the caller's exp is used as-is.
    """
    if ttl_seconds is not None:
        claims = AgentTokenClaims(
            **{**asdict(claims), "exp": int(time.time()) + ttl_seconds}
        )
    payload = _canonical_payload(claims)
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(sig)}"


# ─── Verify ───────────────────────────────────────────────────────────────

def verify_agent_token(token: str, *, keys: List[bytes]) -> AgentTokenClaims:
    """Decode and validate a token against one or more trusted keys.

    `keys` is a list so callers can pass the primary key plus a short list
    of previous keys during rotation windows. Any key in the list that
    produces a matching signature is accepted; order does not matter for
    correctness.
    """
    if not keys:
        # Explicit: empty trust list is always rejected. Without this guard,
        # the constant-time loop below would just fall through to Tampered,
        # but Invalid is the clearer contract error for a misconfigured
        # caller.
        raise AgentTokenInvalid("no trusted keys supplied")

    if not token or "." not in token:
        raise AgentTokenInvalid("token must be '<payload>.<signature>'")

    parts = token.split(".")
    if len(parts) != 2:
        raise AgentTokenInvalid("token must have exactly two parts")

    payload_b64, sig_b64 = parts
    try:
        payload_bytes = _b64url_decode(payload_b64)
        provided_sig = _b64url_decode(sig_b64)
    except (ValueError, base64.binascii.Error) as err:
        raise AgentTokenInvalid(f"payload or signature not base64url: {err}") from None

    # Constant-time compare against every trusted key. Any match accepts.
    matched = False
    for key in keys:
        expected = hmac.new(key, payload_bytes, hashlib.sha256).digest()
        # hmac.compare_digest is explicitly constant-time
        if hmac.compare_digest(expected, provided_sig):
            matched = True
            break
    if not matched:
        raise AgentTokenTampered("signature did not match any trusted key")

    # Signature was valid — now decode and validate claims.
    try:
        raw = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise AgentTokenInvalid(f"payload is not valid JSON: {err}") from None

    if not isinstance(raw, dict):
        raise AgentTokenInvalid("payload must be a JSON object")

    missing = _REQUIRED_CLAIMS - raw.keys()
    if missing:
        raise AgentTokenMissingClaim(
            f"required claim(s) missing from token: {sorted(missing)}"
        )

    # Expiration. Strict `>`: a token whose exp equals now() is expired —
    # removes a one-second race where a sender and receiver disagree on the
    # boundary.
    if raw["exp"] <= int(time.time()):
        raise AgentTokenExpired(f"token exp={raw['exp']} has passed")

    # Build claims through the dataclass so identity_type/id validation
    # applies to incoming tokens too. Unknown fields in the payload are
    # silently ignored (they are not required to pass through, and
    # explicitly-typed consumers should not see them).
    try:
        return AgentTokenClaims(
            identity_type=raw["identity_type"],
            identity_id=raw["identity_id"],
            space_id=raw.get("space_id"),
            crew_id=raw.get("crew_id"),
            agent_id=raw.get("agent_id"),
            exp=raw["exp"],
            attributed_to_user_id=raw.get("attributed_to_user_id"),
        )
    except ValueError as err:
        raise AgentTokenInvalid(f"payload failed validation: {err}") from None
