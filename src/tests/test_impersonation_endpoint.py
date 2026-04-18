"""
Unit tests for ADR-001 Fase 2 — impersonation endpoints.

Covers the invariants spelled out in
tests/backend/21-permissions-rbac/19-impersonation-audit/:
  - default deny (users.impersonate is False for every default role)
  - 60-min hard cap on max_minutes
  - self-impersonation rejected
  - schema validation (reason min length, mode enum, max_minutes range)
"""
from src.services.rbac_service import DEFAULT_ROLE_PERMISSIONS
from src.schemas.impersonation import (
    ImpersonationExitResponse,
    ImpersonationSessionResponse,
    ImpersonationStartRequest,
)


# ---------------------------------------------------------------------------
# Default-deny invariant — matches test B21.19.1 in the backend RBAC suite
# ---------------------------------------------------------------------------

def test_default_role_permissions_deny_users_impersonate_for_every_role():
    """
    Wave 3 + impersonation endpoint: every default role must have
    users.impersonate = False. If someone adds True by accident, this
    catches it at PR review.
    """
    for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
        assert perms.get("users.impersonate", False) is False, (
            f"Role '{role}' must not grant users.impersonate by default"
        )


# ---------------------------------------------------------------------------
# Request schema validation
# ---------------------------------------------------------------------------

def test_request_defaults_to_read_only_and_30_minutes():
    body = ImpersonationStartRequest(reason="Reproducing permission bug ticket 42")
    assert body.mode == "read_only"
    assert body.max_minutes == 30


def test_request_honors_explicit_mode_and_minutes():
    body = ImpersonationStartRequest(
        reason="Debugging widget crash reported by customer",
        mode="read_write",
        max_minutes=45,
    )
    assert body.mode == "read_write"
    assert body.max_minutes == 45


def test_request_rejects_max_minutes_above_60():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImpersonationStartRequest(reason="x" * 20, max_minutes=999)


def test_request_rejects_max_minutes_below_1():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImpersonationStartRequest(reason="x" * 20, max_minutes=0)


def test_request_rejects_short_reason():
    import pytest
    from pydantic import ValidationError

    # Reason <10 chars = not enough justification for audit log.
    with pytest.raises(ValidationError):
        ImpersonationStartRequest(reason="short")


def test_request_rejects_invalid_mode():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImpersonationStartRequest(reason="x" * 20, mode="banana")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Response schema shape
# ---------------------------------------------------------------------------

def test_session_response_has_required_fields():
    from datetime import datetime, timezone

    resp = ImpersonationSessionResponse(
        session_token="jwt-blob",
        on_behalf_of="user-xyz",
        expires_at=datetime.now(timezone.utc),
        mode="read_only",
    )
    assert resp.session_token == "jwt-blob"
    assert resp.on_behalf_of == "user-xyz"
    assert resp.mode == "read_only"


def test_exit_response_defaults_message():
    resp = ImpersonationExitResponse()
    assert "ended" in resp.message.lower()
