"""P0 invariant tests for credential leak surface (Phase 0 of RBAC plan).

These tests pin the property that no Pydantic schema returned by any
connection-related API ever exposes the underlying credential payload
(`config`, `password`, `secret`, etc.). They are intentionally schema-only
so they run fast in CI and fail loudly the moment someone widens
ConnectionResponse to include the config field.

See: sky-poc-infra/docs/architecture/RBAC_GOVERNANCE_PLAN.md (Q11)
And the integration suite: sky-poc-frontend tests/backend/21-permissions-rbac/07-credential-leak/
"""

from __future__ import annotations

import pytest

# Field names that must NEVER appear on any response schema returned to the client.
FORBIDDEN_FIELDS = {
    "config",
    "password",
    "secret",
    "credentials",
    "credential",
    "service_account_json",
    "key_file",
    "key_file_json",
    "private_key",
    "access_token",
    "refresh_token",
    "api_key",
    "client_secret",
    "connection_string",
    "dsn",
    "sasl_password",
}


def _model_field_names(model_cls) -> set[str]:
    """Return the lowercased field names of a Pydantic v1 OR v2 model class."""
    if hasattr(model_cls, "model_fields"):  # pydantic v2
        return {name.lower() for name in model_cls.model_fields.keys()}
    if hasattr(model_cls, "__fields__"):  # pydantic v1
        return {name.lower() for name in model_cls.__fields__.keys()}
    return set()


def test_connection_response_does_not_expose_credentials():
    """ConnectionResponse must not include the config / secrets field."""
    from src.schemas.connection import ConnectionResponse  # imported lazily

    fields = _model_field_names(ConnectionResponse)
    leaked = fields & FORBIDDEN_FIELDS
    assert not leaked, (
        f"ConnectionResponse exposes credential field(s): {leaked}. "
        "This is a P0 security regression. Remove the field or move it to a "
        "write-only schema."
    )


def test_connection_base_does_not_expose_credentials():
    """ConnectionBase (parent class) must also not include credentials."""
    from src.schemas.connection import ConnectionBase

    fields = _model_field_names(ConnectionBase)
    leaked = fields & FORBIDDEN_FIELDS
    assert not leaked, (
        f"ConnectionBase exposes credential field(s): {leaked}. "
        "Anything inheriting from ConnectionBase will also expose them."
    )


def test_connection_create_may_accept_config_for_writes():
    """Sanity check: ConnectionCreate is the WRITE schema and is allowed to
    accept `config`. We do not block writes — we block reads. This test
    documents the asymmetry so a future refactor doesn't accidentally
    forbid the write path too.
    """
    try:
        from src.schemas.connection import ConnectionCreate
    except ImportError:
        pytest.skip("ConnectionCreate not present in current schema module")

    fields = _model_field_names(ConnectionCreate)
    # ConnectionCreate IS allowed to take config — it's the input schema.
    # We assert nothing here; this test only documents the design.
    assert isinstance(fields, set)


def test_no_response_schema_in_connection_module_leaks_credentials():
    """Defense in depth: enumerate every public class in src.schemas.connection
    whose name ends with 'Response' and verify none of them leak credentials.
    """
    import inspect

    from src.schemas import connection as conn_module

    response_classes = [
        cls
        for name, cls in inspect.getmembers(conn_module, inspect.isclass)
        if name.endswith("Response") and cls.__module__ == conn_module.__name__
    ]
    assert response_classes, "no *Response classes found in src.schemas.connection"

    leaks: dict[str, set[str]] = {}
    for cls in response_classes:
        fields = _model_field_names(cls)
        leaked = fields & FORBIDDEN_FIELDS
        if leaked:
            leaks[cls.__name__] = leaked

    assert not leaks, f"Response schemas leak credentials: {leaks}"
