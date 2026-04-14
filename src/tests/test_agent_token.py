"""Tests for src/core/agent_token.py — HMAC-signed short-lived tokens
used for backend → AI-service authentication of agent runs.

Red phase for Phase 1 iteration 1.2. Every test here starts failing
until the module is implemented.

Threat model covered:
  - Tampered payloads must be rejected
  - Tampered signatures must be rejected
  - Expired tokens must be rejected
  - Wrong key must be rejected
  - Missing required claims must be rejected
  - Key rotation: primary and one previous key both accepted
  - Clock-skew boundary behaviour is predictable

The module intentionally avoids JWT. JWT's flexibility (multiple algs,
optional claims, varied libraries) is a liability for an internal
service-to-service token where we control both sides. Plain HMAC-SHA256
over a compact JSON payload is smaller and easier to audit.
"""

import base64
import json
import time

import pytest

from src.core.agent_token import (
    AgentTokenClaims,
    AgentTokenExpired,
    AgentTokenInvalid,
    AgentTokenMissingClaim,
    AgentTokenTampered,
    sign_agent_token,
    verify_agent_token,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

PRIMARY_KEY = b"primary-secret-for-tests-must-be-32-bytes-or-longer-ok-ok-ok"
PREVIOUS_KEY = b"rotating-previous-secret-for-tests-must-also-be-32-bytes-long"
WRONG_KEY = b"attacker-guess-key-must-be-32-bytes-or-longer-for-realism-here"


def _base_claims(**overrides) -> AgentTokenClaims:
    """Build a valid set of claims with 5-minute expiry."""
    defaults = dict(
        identity_type="user",
        identity_id="11111111-1111-1111-1111-111111111111",
        space_id="22222222-2222-2222-2222-222222222222",
        crew_id=None,
        agent_id="33333333-3333-3333-3333-333333333333",
        attributed_to_user_id=None,
        exp=int(time.time()) + 300,
    )
    defaults.update(overrides)
    return AgentTokenClaims(**defaults)


# ─── Happy path ───────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_sign_then_verify_returns_same_claims(self):
        claims = _base_claims()
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])

        assert verified.identity_type == claims.identity_type
        assert verified.identity_id == claims.identity_id
        assert verified.space_id == claims.space_id
        assert verified.crew_id == claims.crew_id
        assert verified.agent_id == claims.agent_id
        assert verified.exp == claims.exp

    def test_token_is_plain_ascii_string(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        assert isinstance(token, str)
        assert token.isascii()

    def test_token_has_two_dot_separated_parts(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        assert token.count(".") == 1  # payload.signature

    def test_service_principal_identity_round_trips(self):
        claims = _base_claims(
            identity_type="service_principal",
            attributed_to_user_id="44444444-4444-4444-4444-444444444444",
        )
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])
        assert verified.identity_type == "service_principal"
        assert verified.attributed_to_user_id == "44444444-4444-4444-4444-444444444444"


# ─── Tampering ────────────────────────────────────────────────────────────


class TestTampering:
    def test_flipped_payload_byte_rejected(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        payload_b64, sig_b64 = token.split(".")
        # Flip one character in the middle of the payload
        tampered = payload_b64[:-2] + ("A" if payload_b64[-2] != "A" else "B") + payload_b64[-1]
        with pytest.raises(AgentTokenTampered):
            verify_agent_token(f"{tampered}.{sig_b64}", keys=[PRIMARY_KEY])

    def test_flipped_signature_byte_rejected(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        payload_b64, sig_b64 = token.split(".")
        tampered_sig = sig_b64[:-2] + ("A" if sig_b64[-2] != "A" else "B") + sig_b64[-1]
        with pytest.raises(AgentTokenTampered):
            verify_agent_token(f"{payload_b64}.{tampered_sig}", keys=[PRIMARY_KEY])

    def test_wrong_key_rejected(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        with pytest.raises(AgentTokenTampered):
            verify_agent_token(token, keys=[WRONG_KEY])

    def test_empty_token_rejected(self):
        with pytest.raises(AgentTokenInvalid):
            verify_agent_token("", keys=[PRIMARY_KEY])

    def test_malformed_token_rejected(self):
        with pytest.raises(AgentTokenInvalid):
            verify_agent_token("only-one-part", keys=[PRIMARY_KEY])

    def test_three_parts_rejected(self):
        with pytest.raises(AgentTokenInvalid):
            verify_agent_token("a.b.c", keys=[PRIMARY_KEY])

    def test_non_base64_parts_rejected(self):
        with pytest.raises(AgentTokenInvalid):
            verify_agent_token("!!!.???", keys=[PRIMARY_KEY])


# ─── Expiration ───────────────────────────────────────────────────────────


class TestExpiration:
    def test_expired_token_rejected(self):
        claims = _base_claims(exp=int(time.time()) - 1)  # 1s past
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        with pytest.raises(AgentTokenExpired):
            verify_agent_token(token, keys=[PRIMARY_KEY])

    def test_long_past_expiry_rejected(self):
        claims = _base_claims(exp=1)  # 1970
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        with pytest.raises(AgentTokenExpired):
            verify_agent_token(token, keys=[PRIMARY_KEY])

    def test_exp_exactly_now_rejected(self):
        # Boundary: exp equal to current second is expired (strictly greater)
        claims = _base_claims(exp=int(time.time()))
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        with pytest.raises(AgentTokenExpired):
            verify_agent_token(token, keys=[PRIMARY_KEY])

    def test_not_yet_expired_accepted(self):
        claims = _base_claims(exp=int(time.time()) + 60)
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])
        assert verified.exp == claims.exp


# ─── Key rotation ─────────────────────────────────────────────────────────


class TestKeyRotation:
    def test_token_signed_with_previous_key_accepted_during_rotation(self):
        token = sign_agent_token(_base_claims(), key=PREVIOUS_KEY)
        # Primary is the new key; previous still trusted
        verified = verify_agent_token(token, keys=[PRIMARY_KEY, PREVIOUS_KEY])
        assert verified.identity_id.startswith("11111111")

    def test_token_signed_with_primary_still_verifies(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY, PREVIOUS_KEY])
        assert verified.identity_id.startswith("11111111")

    def test_token_signed_with_unknown_key_rejected(self):
        token = sign_agent_token(_base_claims(), key=WRONG_KEY)
        with pytest.raises(AgentTokenTampered):
            verify_agent_token(token, keys=[PRIMARY_KEY, PREVIOUS_KEY])

    def test_empty_keys_list_always_rejects(self):
        token = sign_agent_token(_base_claims(), key=PRIMARY_KEY)
        with pytest.raises(AgentTokenInvalid):
            verify_agent_token(token, keys=[])


# ─── Missing claims ───────────────────────────────────────────────────────


class TestMissingClaims:
    def test_missing_identity_id_rejected_at_sign(self):
        # Sign-side validation: don't let a caller build a bad token
        with pytest.raises((TypeError, ValueError)):
            AgentTokenClaims(
                identity_type="user",
                identity_id=None,  # type: ignore
                space_id=None,
                crew_id=None,
                agent_id=None,
                exp=int(time.time()) + 300,
            )

    def test_tampered_payload_removes_required_claim(self):
        # Craft a payload manually with missing identity_id and re-sign
        # to simulate a malicious sender who also knows a key: we still
        # want verify to reject if the claim is absent.
        import hashlib
        import hmac
        payload = {
            "identity_type": "user",
            # identity_id intentionally missing
            "space_id": None,
            "crew_id": None,
            "agent_id": None,
            "exp": int(time.time()) + 300,
        }
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
        sig = hmac.new(PRIMARY_KEY, payload_bytes, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
        token = f"{payload_b64}.{sig_b64}"

        with pytest.raises(AgentTokenMissingClaim):
            verify_agent_token(token, keys=[PRIMARY_KEY])

    def test_invalid_identity_type_rejected(self):
        with pytest.raises(ValueError):
            AgentTokenClaims(
                identity_type="root",  # not user or service_principal
                identity_id="x",
                space_id=None,
                crew_id=None,
                agent_id=None,
                exp=int(time.time()) + 300,
            )


# ─── Optional claims ──────────────────────────────────────────────────────


class TestOptionalClaims:
    def test_crew_id_without_space_id_allowed(self):
        claims = _base_claims(space_id=None, crew_id="55555555-5555-5555-5555-555555555555")
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])
        assert verified.crew_id == "55555555-5555-5555-5555-555555555555"
        assert verified.space_id is None

    def test_both_space_and_crew_id_allowed(self):
        claims = _base_claims(
            space_id="22222222-2222-2222-2222-222222222222",
            crew_id="55555555-5555-5555-5555-555555555555",
        )
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])
        assert verified.space_id and verified.crew_id

    def test_agent_id_is_optional(self):
        # Some calls (e.g. one-off admin probes) do not tie to a specific agent row
        claims = _base_claims(agent_id=None)
        token = sign_agent_token(claims, key=PRIMARY_KEY)
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])
        assert verified.agent_id is None


# ─── TTL helper ───────────────────────────────────────────────────────────


class TestTTL:
    def test_ttl_helper_sets_future_expiry(self):
        """sign_agent_token can also accept a ttl_seconds shortcut."""
        token = sign_agent_token(
            _base_claims(exp=0),  # exp here will be overridden by ttl_seconds
            key=PRIMARY_KEY,
            ttl_seconds=60,
        )
        verified = verify_agent_token(token, keys=[PRIMARY_KEY])
        now = int(time.time())
        assert verified.exp > now
        assert verified.exp <= now + 61
