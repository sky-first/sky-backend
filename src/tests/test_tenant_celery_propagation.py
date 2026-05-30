"""Tests for Celery → TenantContext propagation (Projeto A — PR #8)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
)
from src.workers.tenant_context_propagation import (
    _TENANT_HEADER,
    _attach_tenant_slug_to_headers,
    _reset_tenant_after_task,
    _RESET_TOKENS,
    _set_tenant_from_headers,
)


def _fresh_default():
    # Some tests previously left a non-default contextvar; reset to be
    # deterministic.
    set_current_tenant(DEFAULT_TENANT_CONTEXT)


def _fake_task(slug=None):
    """Return an object shaped like a Celery task with the given slug
    in its request headers."""
    headers = {_TENANT_HEADER: slug} if slug is not None else {}
    request = SimpleNamespace(headers=headers)
    return SimpleNamespace(request=request)


# ─── Publish side ───────────────────────────────────────────────────


def test_publish_writes_default_slug_when_no_tenant_set():
    _fresh_default()
    headers: dict = {}
    _attach_tenant_slug_to_headers(headers=headers)
    assert headers[_TENANT_HEADER] == "default"


def test_publish_writes_current_tenant_slug():
    _fresh_default()
    ctx = TenantContext(
        slug="alpha", id=uuid.uuid4(), tier="starter", display_name="A"
    )
    token = set_current_tenant(ctx)
    try:
        headers: dict = {}
        _attach_tenant_slug_to_headers(headers=headers)
        assert headers[_TENANT_HEADER] == "alpha"
    finally:
        reset_current_tenant(token)


def test_publish_is_noop_when_headers_is_none():
    # Should not raise, just return silently.
    _attach_tenant_slug_to_headers(headers=None)


# ─── Prerun: missing / default slug ─────────────────────────────────


def test_prerun_default_slug_sets_default_context():
    _fresh_default()
    task = _fake_task(slug="default")
    _set_tenant_from_headers(task_id="t1", task=task)
    try:
        assert current_tenant() is DEFAULT_TENANT_CONTEXT
    finally:
        _reset_tenant_after_task(task_id="t1", task=task)


def test_prerun_missing_headers_sets_default():
    _fresh_default()
    task = _fake_task()  # empty headers
    _set_tenant_from_headers(task_id="t-missing", task=task)
    try:
        assert current_tenant() is DEFAULT_TENANT_CONTEXT
    finally:
        _reset_tenant_after_task(task_id="t-missing", task=task)


def test_prerun_no_task_sets_default():
    _fresh_default()
    _set_tenant_from_headers(task_id="t-none", task=None)
    try:
        assert current_tenant() is DEFAULT_TENANT_CONTEXT
    finally:
        _reset_tenant_after_task(task_id="t-none", task=None)


# ─── Prerun: real slug, registry hit ────────────────────────────────


def test_prerun_real_slug_sets_loaded_context(monkeypatch):
    _fresh_default()

    fake_ctx = TenantContext(
        slug="beta",
        id=uuid.uuid4(),
        tier="foundation",
        display_name="Beta",
    )

    from src.api.middleware import tenant_resolver as tr

    # Pretend the cache is cold and the loader returns our fake ctx.
    monkeypatch.setattr(tr, "_cache_get", lambda slug: None)

    async def _fake_loader(slug):
        assert slug == "beta"
        return fake_ctx

    monkeypatch.setattr(tr, "_load_tenant_from_db", _fake_loader)

    task = _fake_task(slug="beta")
    _set_tenant_from_headers(task_id="t-beta", task=task)
    try:
        assert current_tenant().slug == "beta"
        assert current_tenant().tier == "foundation"
    finally:
        _reset_tenant_after_task(task_id="t-beta", task=task)
        assert current_tenant() is DEFAULT_TENANT_CONTEXT


# ─── Prerun: registry miss falls back to default ───────────────────


def test_prerun_unknown_slug_falls_back_to_default(monkeypatch):
    _fresh_default()

    from src.api.middleware import tenant_resolver as tr

    monkeypatch.setattr(tr, "_cache_get", lambda slug: None)

    async def _none_loader(slug):
        return None

    monkeypatch.setattr(tr, "_load_tenant_from_db", _none_loader)

    task = _fake_task(slug="ghost")
    _set_tenant_from_headers(task_id="t-ghost", task=task)
    try:
        # Workers must keep making progress — strict scoping happens
        # in the per-task code that knows it needs a real tenant.
        assert current_tenant() is DEFAULT_TENANT_CONTEXT
    finally:
        _reset_tenant_after_task(task_id="t-ghost", task=task)


# ─── Postrun safety: tokens cleaned up ─────────────────────────────


def test_postrun_drops_token_from_stash():
    _fresh_default()
    task = _fake_task(slug="default")
    _set_tenant_from_headers(task_id="t-stash", task=task)
    assert "t-stash" in _RESET_TOKENS
    _reset_tenant_after_task(task_id="t-stash", task=task)
    assert "t-stash" not in _RESET_TOKENS


def test_postrun_is_safe_on_unknown_id():
    # Should not raise even if before-side was never called for this id.
    _reset_tenant_after_task(task_id="t-never-seen", task=None)
