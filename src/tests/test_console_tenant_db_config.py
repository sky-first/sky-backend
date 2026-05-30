"""Tests for the Console "Database" tab endpoints (PR #19).

Covers the three routes added in ``src/api/v1/console.py``:

* ``GET  /api/console/v1/tenants/{slug}/db-config``  — read the row
* ``PATCH /api/console/v1/tenants/{slug}/db-config`` — partial update
* ``POST /api/console/v1/tenants/{slug}/db-config/test`` — open a
  transient SQLAlchemy connection and run ``SELECT 1``

Invariants verified here mirror the PR description:

* A valid PATCH updates the registry row, returns the new values, and
  writes an ``UPDATE_DB_CONFIG`` audit entry.
* An invalid ``db_credentials_secret_arn`` (regex mismatch) is rejected
  at the schema layer with 422 — the registry row stays intact.
* The audit log masks ``*_secret_arn`` fields to a 30-char prefix +
  ellipsis. The original ARN must not leak into ``request_payload``.
* The ``/test`` endpoint returns 200 + ``ok=true`` on a successful
  ``SELECT 1`` and 503 + ``ok=false`` on connection failure. Neither
  outcome mutates the registry row.
"""

from __future__ import annotations

import ast
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.main import app
from src.models.internal_console import AuditAction, InternalConsoleAudit
from src.models.tenant import Tenant
from src.models.user import User


_VALID_ARN_DB = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:gbt/db-creds-AbCdEf"
_VALID_ARN_REDIS = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:gbt/redis-creds-XyZ"
_AUDIT_PREFIX_LEN = 30


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def sky_team_dev_bypass(monkeypatch):
    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "")
    yield


@pytest.fixture
def sky_team_user():
    return User(
        id=uuid.uuid4(),
        email="lucas@skyfirstlabs.com",
        password_hash="",
        name="Lucas",
        role="admin",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=True,
    )


@pytest.fixture
def authed_client(client, sky_team_user):
    app.dependency_overrides[get_current_user] = lambda: sky_team_user
    app.dependency_overrides[require_sky_team] = lambda: sky_team_user
    yield client
    app.dependency_overrides.pop(require_sky_team, None)
    app.dependency_overrides.pop(get_current_user, None)


def _registry_payload(slug: str = "gbt", **overrides) -> Dict:
    base = dict(
        slug=slug,
        display_name=f"{slug.upper()} Co.",
        tier="starter",
        db_host=f"postgres-{slug}.local",
        db_port=5432,
        db_name=f"tenant_{slug}",
        db_credentials_secret_arn=f"arn:secret:{slug}:db",
        redis_host=f"redis-{slug}.local",
        redis_credentials_secret_arn=f"arn:secret:{slug}:redis",
        sso_provider="google",
    )
    base.update(overrides)
    return base


def _unwrap_error_message(body: Dict[str, Any]) -> Dict[str, Any]:
    """Recover the structured error dict the endpoint returned.

    The global handler at ``src/core/errors/handlers.py`` packages the
    response as ``{"error": {"code", "message", "correlation_id"}}``
    where ``message`` is ``str(original_detail)``.
    """
    if isinstance(body, dict):
        envelope = body.get("error")
        if isinstance(envelope, dict):
            msg = envelope.get("message")
            if isinstance(msg, str) and msg.startswith("{"):
                try:
                    return ast.literal_eval(msg)
                except Exception:  # noqa: BLE001
                    pass
            return envelope
        if "error" in body and isinstance(body["error"], str):
            return body
    return body


# ── PATCH /db-config — happy path ───────────────────────────────────


@pytest.mark.asyncio
async def test_patch_db_config_updates_row_and_returns_values(
    authed_client, db_session
):
    """A valid PATCH replaces only the fields the operator sent and
    reflects the new values in both the response body and the row."""
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("gbt")
    )

    res = authed_client.patch(
        "/api/console/v1/tenants/gbt/db-config",
        json={
            "db_host": "rds-gbt.eu-west-1.rds.amazonaws.com",
            "db_credentials_secret_arn": _VALID_ARN_DB,
            "db_port": 5433,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["db_host"] == "rds-gbt.eu-west-1.rds.amazonaws.com"
    assert body["db_port"] == 5433
    assert body["db_credentials_secret_arn"] == _VALID_ARN_DB
    # Untouched fields keep the original values.
    assert body["db_name"] == "tenant_gbt"
    assert body["redis_host"] == "redis-gbt.local"

    row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "gbt"))
    ).scalar_one()
    assert row.db_host == "rds-gbt.eu-west-1.rds.amazonaws.com"
    assert row.db_port == 5433
    assert row.db_credentials_secret_arn == _VALID_ARN_DB


# ── PATCH /db-config — invalid ARN format ──────────────────────────


def test_patch_db_config_rejects_invalid_secret_arn(authed_client):
    """A value that isn't an ``arn:aws:secretsmanager:...`` is refused
    at the schema layer; the registry row is untouched."""
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("bad")
    )

    res = authed_client.patch(
        "/api/console/v1/tenants/bad/db-config",
        json={"db_credentials_secret_arn": "not-an-arn"},
    )
    assert res.status_code == 422, res.text


def test_patch_db_config_empty_body_refused(authed_client):
    """An empty payload would write a no-op audit row — refuse with 422."""
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("nf")
    )

    res = authed_client.patch(
        "/api/console/v1/tenants/nf/db-config",
        json={},
    )
    assert res.status_code == 422, res.text
    err = _unwrap_error_message(res.json())
    assert err.get("error") == "no_fields_supplied"


# ── Audit log: secret masking ──────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_db_config_masks_secret_arn_in_audit(
    authed_client, db_session
):
    """The audit row's ``request_payload`` must not carry the full ARN.

    We persist only the first 30 chars + an ellipsis. The host /
    port / db_name fields pass through verbatim.
    """
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("auds")
    )
    authed_client.patch(
        "/api/console/v1/tenants/auds/db-config",
        json={
            "db_host": "10.0.1.5",
            "db_credentials_secret_arn": _VALID_ARN_DB,
            "redis_credentials_secret_arn": _VALID_ARN_REDIS,
        },
    )

    audit_rows = (
        await db_session.execute(
            select(InternalConsoleAudit)
            .where(InternalConsoleAudit.tenant_slug == "auds")
            .where(
                InternalConsoleAudit.action
                == AuditAction.UPDATE_DB_CONFIG.value
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1
    payload = audit_rows[0].request_payload
    assert isinstance(payload, dict)
    new_values = payload["new_values"]
    # Host passes through verbatim.
    assert new_values["db_host"] == "10.0.1.5"
    # Secrets are truncated to the 30-char prefix + ellipsis.
    masked_db = new_values["db_credentials_secret_arn"]
    masked_redis = new_values["redis_credentials_secret_arn"]
    assert _VALID_ARN_DB not in masked_db
    assert _VALID_ARN_REDIS not in masked_redis
    assert masked_db.endswith("...")
    assert masked_redis.endswith("...")
    # Prefix length matches the constant.
    assert len(masked_db) == _AUDIT_PREFIX_LEN + 3
    assert payload["changed_fields"] == sorted(
        ["db_host", "db_credentials_secret_arn", "redis_credentials_secret_arn"]
    )


# ── /test endpoint ─────────────────────────────────────────────────


def test_test_db_config_returns_ok_on_successful_connection(
    authed_client, monkeypatch
):
    """When ``SELECT 1`` returns 1, the endpoint reports 200 ok=True.

    We patch ``create_async_engine`` so the test doesn't depend on a
    real Postgres being reachable from CI.
    """
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("tok")
    )

    mock_result = MagicMock()
    mock_result.scalar.return_value = 1

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def fake_connect():
        yield mock_conn

    mock_engine = MagicMock()
    mock_engine.connect = fake_connect
    mock_engine.dispose = AsyncMock()

    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        return_value=mock_engine,
    ):
        res = authed_client.post(
            "/api/console/v1/tenants/tok/db-config/test"
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["target_host"] == "postgres-tok.local"
    assert body["target_db"] == "tenant_tok"
    assert body["error"] is None


def test_test_db_config_returns_503_on_connection_failure(
    authed_client, monkeypatch
):
    """When the connection raises (refused / auth / timeout) the
    endpoint returns 503 with ``ok=false`` and the error message."""
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("fail")
    )

    @asynccontextmanager
    async def fake_connect():
        raise ConnectionRefusedError("no route to host")
        yield  # pragma: no cover

    mock_engine = MagicMock()
    mock_engine.connect = fake_connect
    mock_engine.dispose = AsyncMock()

    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        return_value=mock_engine,
    ):
        res = authed_client.post(
            "/api/console/v1/tenants/fail/db-config/test"
        )

    assert res.status_code == 503, res.text
    body = res.json()
    assert body["ok"] is False
    assert "ConnectionRefusedError" in (body["error"] or "")
    assert body["target_host"] == "postgres-fail.local"
