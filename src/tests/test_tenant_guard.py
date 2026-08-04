"""Tests for ``src.core.tenant_guard`` (Projeto A — PR #14)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from src.config.settings import settings
from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    reset_current_tenant,
    set_current_tenant,
)
from src.core.tenant_guard import assert_tenant_scoped


def _real_tenant() -> TenantContext:
    return TenantContext(
        slug="alpha", id=uuid.uuid4(), tier="starter", display_name="Alpha"
    )


# ── No-op while flag is OFF ────────────────────────────────────────


def test_no_op_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", False)
    # Default context, strict on — must still not raise.
    monkeypatch.setattr(settings, "STRICT_TENANT_REQUIRED", True)
    ctx = assert_tenant_scoped("test.no_op")
    assert ctx is DEFAULT_TENANT_CONTEXT


# ── Flag ON, default context → log + (optional) raise ────────────


def test_logs_warning_on_default_context(monkeypatch, caplog):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    monkeypatch.setattr(settings, "STRICT_TENANT_REQUIRED", False)
    set_current_tenant(DEFAULT_TENANT_CONTEXT)

    with caplog.at_level("WARNING"):
        ctx = assert_tenant_scoped("test.default_with_flag")

    assert ctx is DEFAULT_TENANT_CONTEXT
    assert any(
        "tenant_scope_violation" in record.message
        or record.message == "tenant_scope_violation"
        for record in caplog.records
    )


def test_raises_when_strict_mode_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    monkeypatch.setattr(settings, "STRICT_TENANT_REQUIRED", True)
    set_current_tenant(DEFAULT_TENANT_CONTEXT)

    with pytest.raises(HTTPException) as info:
        assert_tenant_scoped("test.strict")

    assert info.value.status_code == 400
    detail = info.value.detail
    assert detail["error"] == "tenant_scope_required"
    assert detail["operation"] == "test.strict"


def test_hard_fail_argument_overrides_setting(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    monkeypatch.setattr(settings, "STRICT_TENANT_REQUIRED", False)  # off
    set_current_tenant(DEFAULT_TENANT_CONTEXT)

    with pytest.raises(HTTPException):
        assert_tenant_scoped("test.override", hard_fail=True)


# ── Flag ON, real tenant → returns ctx silently ──────────────────


def test_passes_through_real_tenant(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    monkeypatch.setattr(settings, "STRICT_TENANT_REQUIRED", True)
    ctx = _real_tenant()
    token = set_current_tenant(ctx)
    try:
        result = assert_tenant_scoped("test.happy_path")
        assert result is ctx
    finally:
        reset_current_tenant(token)


def test_explicit_ctx_overrides_lookup(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    monkeypatch.setattr(settings, "STRICT_TENANT_REQUIRED", True)
    set_current_tenant(DEFAULT_TENANT_CONTEXT)
    real = _real_tenant()
    result = assert_tenant_scoped("test.explicit_ctx", ctx=real)
    assert result is real
