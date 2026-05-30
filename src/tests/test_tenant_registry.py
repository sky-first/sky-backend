"""Tests for the tenant registry table (Projeto A — PR #1).

This is a foundation PR: no application behaviour changes, only the
new ``tenant_registry`` table and the Pydantic schemas around it. The
tests therefore exercise:

* schema-level invariants (slug regex, unique constraints, default
  capacity shape, immutability of slug on update)
* the feature flag defaults OFF (the runtime middleware ships later
  but the default must be safe from day one)
* the ORM row round-trips correctly through the session

No HTTP routes are tested because there are none yet — PR #2 adds the
Internal Console endpoints that consume these schemas.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config.settings import settings
from src.models.tenant import DEFAULT_CAPACITY_SHAPE, Tenant, TenantTier
from src.schemas.tenant import (
    CapacityDimensions,
    TenantCreate,
    TenantRead,
    TenantUpdate,
)


# ── Helpers ──────────────────────────────────────────────────────


def _valid_tenant_payload(**overrides):
    """A complete, valid TenantCreate payload. Tests override one field
    at a time to assert that the validator catches each invariant."""
    base = dict(
        slug="gbt",
        display_name="GBT S.A.",
        tier=TenantTier.STARTER,
        db_host="postgres-gbt.tenant-data-gbt.svc.cluster.local",
        db_port=5432,
        db_name="gbt",
        db_credentials_secret_arn="arn:aws:secretsmanager:eu-west-1:0:secret:sky/clients/gbt/postgres-x",
        redis_host="redis-gbt.tenant-data-gbt.svc.cluster.local",
        redis_credentials_secret_arn="arn:aws:secretsmanager:eu-west-1:0:secret:sky/clients/gbt/redis-x",
        sso_provider="google",
    )
    base.update(overrides)
    return base


def _persist_tenant(session, **overrides) -> Tenant:
    payload = _valid_tenant_payload(**overrides)
    # The model expects strings for tier; the schema would coerce the
    # enum but we go straight to the ORM here.
    payload["tier"] = (
        overrides.get("tier", TenantTier.STARTER).value
        if isinstance(payload["tier"], TenantTier)
        else payload["tier"]
    )
    tenant = Tenant(id=uuid.uuid4(), **payload)
    session.add(tenant)
    return tenant


# ── Feature flag ─────────────────────────────────────────────────


def test_multi_tenant_enabled_defaults_off():
    """The flag must default OFF — the resolver ships later and the
    platform must stay single-tenant until PR #13 explicitly flips it."""
    assert settings.MULTI_TENANT_ENABLED is False


# ── Pydantic schemas ─────────────────────────────────────────────


class TestTenantCreate:
    def test_accepts_minimal_valid_payload(self):
        model = TenantCreate(**_valid_tenant_payload())
        assert model.slug == "gbt"
        assert model.tier == TenantTier.STARTER
        # Default capacity shape is always populated.
        assert model.capacity_limits.model_dump() == DEFAULT_CAPACITY_SHAPE

    @pytest.mark.parametrize(
        "bad_slug",
        [
            "",  # empty
            "a",  # one char (min is 2)
            "G",  # uppercase
            "with space",  # whitespace
            "under_score",  # underscore not allowed
            "x" * 51,  # too long
            "trailing-",  # technically allowed by regex but kept to flag the boundary
        ],
    )
    def test_rejects_invalid_slug(self, bad_slug):
        if bad_slug == "trailing-":
            # Regex `^[a-z0-9-]{2,50}$` does allow a trailing hyphen.
            # We assert that explicitly so a future tightening of the
            # regex breaks loudly rather than silently.
            TenantCreate(**_valid_tenant_payload(slug=bad_slug))
            return
        with pytest.raises(ValidationError):
            TenantCreate(**_valid_tenant_payload(slug=bad_slug))

    def test_rejects_invalid_tier(self):
        with pytest.raises(ValidationError):
            TenantCreate(**_valid_tenant_payload(tier="enterprise"))

    def test_db_port_clamped_to_tcp_range(self):
        with pytest.raises(ValidationError):
            TenantCreate(**_valid_tenant_payload(db_port=0))
        with pytest.raises(ValidationError):
            TenantCreate(**_valid_tenant_payload(db_port=70_000))


class TestTenantUpdate:
    def test_partial_update_allowed(self):
        TenantUpdate(display_name="GBT International S.A.")  # nothing else

    def test_suspended_at_requires_inactive(self):
        # Per the SQL check constraint mirrored in the schema validator.
        with pytest.raises(ValidationError):
            TenantUpdate(
                is_active=True,
                suspended_at="2026-05-26T10:00:00+00:00",
            )

    def test_suspended_at_with_inactive_is_fine(self):
        TenantUpdate(
            is_active=False,
            suspended_at="2026-05-26T10:00:00+00:00",
        )

    def test_slug_is_not_updatable(self):
        # Schema is configured ``extra="forbid"``: callers cannot
        # piggy-back a slug rename onto a PATCH and silently get a no-op.
        with pytest.raises(ValidationError):
            TenantUpdate.model_validate({"slug": "renamed"})


class TestCapacityDimensions:
    def test_zero_default(self):
        assert CapacityDimensions().model_dump() == DEFAULT_CAPACITY_SHAPE

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            CapacityDimensions(agents=-1)


# ── ORM round-trip ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_and_read_back(db_session):
    tenant = _persist_tenant(db_session)
    await db_session.commit()

    result = await db_session.execute(select(Tenant).where(Tenant.slug == "gbt"))
    fetched = result.scalar_one()

    assert fetched.display_name == "GBT S.A."
    assert fetched.tier == "starter"
    assert fetched.is_active is True
    assert fetched.suspended_at is None
    # Read schema accepts the ORM row directly via from_attributes.
    TenantRead.model_validate(fetched)


@pytest.mark.asyncio
async def test_slug_is_unique(db_session):
    _persist_tenant(db_session, slug="dup")
    await db_session.commit()

    _persist_tenant(db_session, slug="dup", display_name="Other")
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_custom_domain_is_unique_when_set(db_session):
    _persist_tenant(db_session, slug="a", custom_domain="sky.example.com")
    await db_session.commit()

    _persist_tenant(db_session, slug="b", custom_domain="sky.example.com")
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_custom_domain_null_allows_multiple_rows(db_session):
    # Two tenants without a custom domain must both be allowed.
    _persist_tenant(db_session, slug="a")
    _persist_tenant(db_session, slug="b")
    await db_session.commit()

    rows = (await db_session.execute(select(Tenant))).scalars().all()
    assert {t.slug for t in rows} == {"a", "b"}
