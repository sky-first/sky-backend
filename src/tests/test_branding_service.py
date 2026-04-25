"""Tests for src/services/branding_service.py + the route layer."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.models.user import User
from src.repositories.user import UserRepository
from src.schemas.branding import BrandingUpdate
from src.services.branding_service import BrandingService


def _bearer(user: User) -> dict:
    """Mint a bearer-header dict for a real JWT — the auth middleware
    rejects requests without it before the dependency override fires."""
    token = create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    """A user with the ``owner`` role — required for branding writes."""
    repo = UserRepository(db_session)
    user = await repo.create(
        email="owner@acme.test",
        password_hash="x",
        name="Acme Owner",
        role="owner",
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="member@acme.test",
        password_hash="x",
        name="Acme Member",
        role="member",
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_get_returns_defaults_when_no_row_exists(db_session: AsyncSession):
    """A fresh tenant must not 404 — return defaults so the FE can boot."""
    svc = BrandingService(db_session)
    cfg = await svc.get()
    assert cfg.primary_color == "#1e3a5f"
    assert cfg.radius == 10
    assert cfg.font_family == "geist"
    assert cfg.logo_url is None
    assert cfg.company_name == "SkyFirstLabs"


@pytest.mark.asyncio
async def test_update_creates_singleton_row_on_first_write(
    db_session: AsyncSession, owner_user: User
):
    svc = BrandingService(db_session)
    cfg = await svc.update(
        owner_user,
        BrandingUpdate(primary_color="#7c3aed", radius=14, company_name="Acme"),
    )
    assert cfg.primary_color == "#7c3aed"
    assert cfg.radius == 14
    assert cfg.company_name == "Acme"
    # Reading back returns the same row (no new defaults).
    cfg2 = await svc.get()
    assert cfg2.primary_color == "#7c3aed"
    assert cfg2.company_name == "Acme"


@pytest.mark.asyncio
async def test_update_patches_only_provided_fields(
    db_session: AsyncSession, owner_user: User
):
    """Sending only ``primary_color`` must not wipe the other fields."""
    svc = BrandingService(db_session)
    await svc.update(
        owner_user,
        BrandingUpdate(primary_color="#0369a1", company_name="First Save"),
    )
    await svc.update(owner_user, BrandingUpdate(radius=20))
    cfg = await svc.get()
    assert cfg.primary_color == "#0369a1"   # untouched second time
    assert cfg.company_name == "First Save"  # untouched second time
    assert cfg.radius == 20                 # newly applied


@pytest.mark.asyncio
async def test_update_records_updated_by_user_id(
    db_session: AsyncSession, owner_user: User
):
    """Audit trail — the row remembers who saved it."""
    svc = BrandingService(db_session)
    await svc.update(owner_user, BrandingUpdate(primary_color="#059669"))

    from src.models.platform_branding import PlatformBranding
    from sqlalchemy import select
    row = (await db_session.execute(select(PlatformBranding))).scalar_one()
    assert row.updated_by_user_id == owner_user.id


def test_branding_update_rejects_non_hex_primary_color():
    """Pydantic-level validation — guards against tokens like ``primary``."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BrandingUpdate(primary_color="primary")
    with pytest.raises(ValidationError):
        BrandingUpdate(primary_color="#GGGGGG")


def test_branding_update_normalizes_hex_without_leading_hash():
    """A user pasting ``1e3a5f`` (no #) gets normalized."""
    patch = BrandingUpdate(primary_color="1e3a5f")
    assert patch.primary_color == "#1e3a5f"


def test_branding_update_accepts_three_digit_hex():
    patch = BrandingUpdate(primary_color="#abc")
    assert patch.primary_color == "#abc"


def test_branding_update_rejects_unknown_font_family():
    """Only the FE's enum values are accepted server-side. Stops a stale
    FE build from POSTing ``comic-sans`` and the server silently storing
    it — the next render would fall back to the system default."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BrandingUpdate(font_family="comic-sans")  # type: ignore[arg-type]


def test_branding_update_rejects_oversized_logo():
    """The schema caps ``logo_url`` at ~1MB of base64 to prevent a 50MB
    image from reaching the JSON column."""
    from pydantic import ValidationError
    huge = "data:image/png;base64," + "A" * (1_400_001)
    with pytest.raises(ValidationError):
        BrandingUpdate(logo_url=huge)


# ---------------------------------------------------------------------------
#  Route-level tests — owner-only enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_get_branding_open_to_authed_user(async_client, member_user: User):
    """Members must be able to GET — they need it on app boot."""
    resp = await async_client.get("/api/v1/branding", headers=_bearer(member_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_color"] == "#1e3a5f"


@pytest.mark.asyncio
async def test_route_put_branding_403_for_non_owner(async_client, member_user: User):
    """Members get 403 — branding is a tenant-wide visual choice."""
    resp = await async_client.put(
        "/api/v1/branding",
        json={"primary_color": "#000000"},
        headers=_bearer(member_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_route_put_branding_200_for_owner(async_client, owner_user: User):
    resp = await async_client.put(
        "/api/v1/branding",
        json={"primary_color": "#7c3aed", "company_name": "Acme Corp"},
        headers=_bearer(owner_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_color"] == "#7c3aed"
    assert body["company_name"] == "Acme Corp"


# Schema-level hex validation is unit-tested in
# ``test_branding_update_rejects_non_hex_primary_color`` — no need for a
# parallel route-level test (the FastAPI body-validation path is
# exercised by every other route in the repo).
